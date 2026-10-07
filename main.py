import urllib.request
from pathlib import Path
import duckdb

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "football.duckdb"

# A season is identified by the year it starts: 2011 means 2011-12.
FIRST_SEASON = 2011
CURRENT_SEASON = 2026  # still in progress, so it is re-downloaded every run
SEASONS = range(FIRST_SEASON, CURRENT_SEASON + 1)

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
            TRY_CAST("AS" AS INTEGER) AS away_shots
        FROM raw_matches
        WHERE HomeTeam IS NOT NULL
    """)

    raw = con.sql("SELECT COUNT(*) FROM raw_matches").fetchone()[0]
    clean = con.sql("SELECT COUNT(*) FROM matches").fetchone()[0]
    print(f"Loaded {raw} raw rows, kept {clean} ({raw - clean} blank rows removed).")

# Reporting functions for analyzing the cleaned data
def report_home_advantage(con):
    con.sql("""
        SELECT
            season,
            COUNT(*) AS matches,
            ROUND(AVG(home_goals), 2) AS avg_home_goals,
            ROUND(AVG(away_goals), 2) AS avg_away_goals,
            ROUND(AVG(home_goals - away_goals), 2) AS home_goal_edge,
            ROUND(AVG(CASE WHEN result = 'H' THEN 1.0 ELSE 0 END), 3) AS home_win_rate
        FROM matches
        GROUP BY season
        ORDER BY season
    """).show(max_width=200)

# Split into small functions (download, load, clean, report)
def main():
    download_all()
    con = duckdb.connect(str(DB_PATH))  # saves your work to a file
    load_raw(con)
    build_matches(con)
    report_home_advantage(con)
    con.close()


if __name__ == "__main__":
    main()