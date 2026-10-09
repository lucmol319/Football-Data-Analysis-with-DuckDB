import urllib.request
import duckdb
from constants import DATA_DIR, DB_PATH, CURRENT_SEASON, SEASONS, MATCHES_PER_SEASON
from pathlib import Path

# Handles season labels and codes
def season_label(start):
    """2011 -> '2011-12'"""
    return f"{start}-{str(start + 1)[-2:]}"

# Conversion between season start year and football-data.co.uk season code
def season_code(start):
    """2011 -> '1112' (the code football-data.co.uk uses in its URLs)"""
    return f"{str(start)[-2:]}{str(start + 1)[-2:]}"

def download_season(start, refresh=False):
    """Download one season's CSV. Skips files that already exist unless refresh=True."""
    label = season_label(start)
    dest = DATA_DIR / f"EPL {label} Season.csv"

    if dest.exists() and not refresh:
        return False
    url = f"https://www.football-data.co.uk/mmz4281/{season_code(start)}/E0.csv"

    try:
        urllib.request.urlretrieve(url, dest)
    except OSError as err:  # covers network errors and HTTP errors
        print(f"Could not download {label}: {err}")
        return False
    return True

def download_all():
    """Loading and processing the data into DuckDB."""

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = 0

    for start in SEASONS:
        # Finished seasons never change, so only the current one is refreshed.
        if download_season(start, refresh=(start == CURRENT_SEASON)):
            downloaded += 1
    print(f"Downloaded or refreshed {downloaded} season file(s).")

def load_raw(con):
    """Load every CSV into one table, all columns as text."""

    pattern = (DATA_DIR / "*.csv").as_posix()
    con.sql(f"""
        CREATE OR REPLACE TABLE raw_matches AS
        SELECT *
        FROM read_csv(
            '{pattern}',
            union_by_name = true,
            filename = true,
            all_varchar = true
        )
    """)

def build_matches(con):
    """Clean the raw table: proper types, consistent dates, a season column."""

    con.sql(r"""
        CREATE OR REPLACE TABLE matches AS
        SELECT
            regexp_extract(filename, 'EPL (\d{4}-\d{2}) Season', 1) AS season,
            COALESCE(
                try_strptime(Date, '%d/%m/%Y'),
                try_strptime(Date, '%d/%m/%y')
            )::DATE AS match_date,
            HomeTeam AS home_team,
            AwayTeam AS away_team,
            TRY_CAST(FTHG AS INTEGER) AS home_goals,
            TRY_CAST(FTAG AS INTEGER) AS away_goals,
            FTR AS result,
            TRY_CAST(HS AS INTEGER) AS home_shots,
            TRY_CAST("AS" AS INTEGER) AS away_shots,
            TRY_CAST(B365H AS DOUBLE) AS odds_home,
            TRY_CAST(B365D AS DOUBLE) AS odds_draw,
            TRY_CAST(B365A AS DOUBLE) AS odds_away
        FROM raw_matches
        WHERE HomeTeam IS NOT NULL
    """)

    raw = con.sql("SELECT COUNT(*) FROM raw_matches").fetchone()[0]
    clean = con.sql("SELECT COUNT(*) FROM matches").fetchone()[0]
    print(f"Loaded {raw} raw rows, kept {clean} ({raw - clean} blank rows removed).")

def build_season_summary(con):
    """
    One row per season: the table that charts.py reads.
    Builds a season_summary table with one row per season: goals, win, draw, and away-win rates, and an is_complete flag (true when a season has 380 matches).
    That keeps the 2026-27 season, which has only 50 matches so far, out of the trend automatically.
    """

    # The f in the SQL string allows us to inject the MATCHES_PER_SEASON constant directly into the query.
    con.sql(f"""
        CREATE OR REPLACE TABLE season_summary AS
        SELECT
            season,
            COUNT(*) AS matches,
            COUNT(*) = {MATCHES_PER_SEASON} AS is_complete,
            AVG(home_goals) AS avg_home_goals,
            AVG(away_goals) AS avg_away_goals,
            AVG(home_goals - away_goals) AS home_goal_edge,
            AVG(CASE WHEN result = 'H' THEN 1.0 ELSE 0 END) AS home_win_rate,
            AVG(CASE WHEN result = 'D' THEN 1.0 ELSE 0 END) AS draw_rate,
            AVG(CASE WHEN result = 'A' THEN 1.0 ELSE 0 END) AS away_win_rate
        FROM matches
        GROUP BY season
        ORDER BY season
    """)

def report_home_advantage(con):
    """Reporting functions for analyzing the cleaned data."""
    con.sql("""
        SELECT
            season,
            matches,
            ROUND(avg_home_goals, 2) AS avg_home_goals,
            ROUND(avg_away_goals, 2) AS avg_away_goals,
            ROUND(home_goal_edge, 2) AS home_goal_edge,
            ROUND(home_win_rate, 3) AS home_win_rate
        FROM season_summary
        ORDER BY season
    """).show(max_width=200)

def build_match_probabilities(con):
    """Turn Bet365 decimal odds into probabilities for each match.

    1 / odds gives a raw probability, but the three raw numbers add up to more
    than 1 (the bookmaker's margin). Dividing each by the total removes the margin.
    """
    con.sql("""
        CREATE OR REPLACE TABLE match_probabilities AS
        WITH implied AS (
            SELECT
                season, match_date, home_team, away_team, result,
                1.0 / odds_home AS raw_home,
                1.0 / odds_draw AS raw_draw,
                1.0 / odds_away AS raw_away
            FROM matches
            WHERE odds_home > 1 AND odds_draw > 1 AND odds_away > 1
              AND result IN ('H', 'D', 'A')
        )
        SELECT
            season, match_date, home_team, away_team, result,
            raw_home + raw_draw + raw_away AS booksum,
            raw_home / (raw_home + raw_draw + raw_away) AS p_home,
            raw_draw / (raw_home + raw_draw + raw_away) AS p_draw,
            raw_away / (raw_home + raw_draw + raw_away) AS p_away
        FROM implied
    """)


def build_forecast_scores(con):
    """Score the odds as forecasts, and compare against a simple baseline.

    Brier score = average squared error of the probabilities (lower is better).
    The baseline always predicts the overall long-run H/D/A frequencies.
    """
    con.sql("""
        CREATE OR REPLACE TABLE forecast_scores AS
        WITH base AS (
            SELECT
                AVG((result = 'H')::INTEGER) AS b_home,
                AVG((result = 'D')::INTEGER) AS b_draw,
                AVG((result = 'A')::INTEGER) AS b_away
            FROM match_probabilities
        ),
        scored AS (
            SELECT
                m.result,
                m.booksum,
                CASE WHEN p_home >= p_draw AND p_home >= p_away THEN 'H'
                     WHEN p_away >= p_draw THEN 'A'
                     ELSE 'D' END AS favourite,
                POWER(p_home - (result = 'H')::INTEGER, 2)
                    + POWER(p_draw - (result = 'D')::INTEGER, 2)
                    + POWER(p_away - (result = 'A')::INTEGER, 2) AS brier_odds,
                POWER(b_home - (result = 'H')::INTEGER, 2)
                    + POWER(b_draw - (result = 'D')::INTEGER, 2)
                    + POWER(b_away - (result = 'A')::INTEGER, 2) AS brier_baseline
            FROM match_probabilities m, base
        )
        SELECT
            COUNT(*) AS matches,
            AVG((favourite = result)::INTEGER) AS favourite_win_rate,
            AVG(brier_odds) AS brier_odds,
            AVG(brier_baseline) AS brier_baseline,
            AVG(booksum - 1) AS avg_bookmaker_margin
        FROM scored
    """)


def build_calibration(con):
    """Group predictions into probability bands and compare with what happened."""
    con.sql("""
        CREATE OR REPLACE TABLE calibration AS
        WITH long_form AS (
            SELECT 'Home win' AS outcome, p_home AS p, (result = 'H')::INTEGER AS happened
            FROM match_probabilities
            UNION ALL
            SELECT 'Draw', p_draw, (result = 'D')::INTEGER FROM match_probabilities
            UNION ALL
            SELECT 'Away win', p_away, (result = 'A')::INTEGER FROM match_probabilities
        )
        SELECT
            outcome,
            FLOOR(p * 10) / 10 AS bin_start,
            COUNT(*) AS n,
            AVG(p) AS avg_predicted,
            AVG(happened) AS actual_rate
        FROM long_form
        GROUP BY outcome, bin_start
        ORDER BY outcome, bin_start
    """)


def report_forecast_scores(con):
    con.sql("""
        SELECT
            matches,
            ROUND(favourite_win_rate, 3) AS favourite_win_rate,
            ROUND(brier_odds, 4) AS brier_odds,
            ROUND(brier_baseline, 4) AS brier_baseline,
            ROUND(avg_bookmaker_margin, 3) AS avg_bookmaker_margin
        FROM forecast_scores
    """).show(max_width=200)

def main():
    download_all()
    con = duckdb.connect(str(DB_PATH))  # saves your work to a file
    load_raw(con)
    build_matches(con)
    build_season_summary(con)
    report_home_advantage(con)

    """
    Loads the Bet365 odds columns (B365H, B365D, B365A) into the matches table. It builds three new tables:
    match_probabilities has the margin-free probabilities for each match.
    forecast_scores has the favourite’s win rate, the average bookmaker margin, and a Brier score (lower is better) for the odds, compared with a baseline that always predicts the long-run home, draw, and away frequencies.
    calibration groups predictions into 10-point bands and compares predicted with actual frequencies.
    """
    build_match_probabilities(con)
    build_forecast_scores(con)
    build_calibration(con)
    report_forecast_scores(con)
    con.close()

if __name__ == "__main__":
    main()