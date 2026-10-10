import duckdb

"""
Loads the Bet365 odds columns (B365H, B365D, B365A) into the matches table. It builds three new tables:
match_probabilities has the margin-free probabilities for each match.
forecast_scores has the favourite's win rate, the average bookmaker margin, and a Brier score (lower is better) for the odds, compared with a baseline that always predicts the long-run home, draw, and away frequencies.
calibration groups predictions into 10-point bands and compares predicted with actual frequencies.
"""

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