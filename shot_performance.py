from constants import MATCHES_PER_TEAM

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

def build_team_tables(con):
    """Question 3: compare each team's goals with what its shots would suggest.

    team_matches: one row per team per match (home and away rows stacked).
    team_seasons: one row per team per season, with the shot-based comparison.
    """
    con.sql("""
        CREATE OR REPLACE TABLE team_matches AS
        WITH played AS (
            SELECT *
            FROM matches
            WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL
              AND home_shots IS NOT NULL AND away_shots IS NOT NULL
        )
        SELECT season, match_date, home_team AS team, away_team AS opponent,
               TRUE AS is_home,
               home_goals AS goals_for, away_goals AS goals_against,
               home_shots AS shots_for, away_shots AS shots_against,
               CASE result WHEN 'H' THEN 3 WHEN 'D' THEN 1 ELSE 0 END AS points
        FROM played
        UNION ALL
        SELECT season, match_date, away_team, home_team,
               FALSE,
               away_goals, home_goals,
               away_shots, home_shots,
               CASE result WHEN 'A' THEN 3 WHEN 'D' THEN 1 ELSE 0 END
        FROM played
    """)

    # goal_diff_vs_shots: actual goal difference minus the goal difference you
    # would expect if every shot were worth the league's average goals per shot.
    # Positive = scored more / conceded fewer than the shots suggest.
    con.sql(f"""
        CREATE OR REPLACE TABLE team_seasons AS
        WITH league AS (
            SELECT season,
                   SUM(goals_for)::DOUBLE / SUM(shots_for) AS league_goals_per_shot
            FROM team_matches
            GROUP BY season
        ),
        agg AS (
            SELECT season, team,
                   COUNT(*) AS games,
                   SUM(points) AS points,
                   SUM(goals_for) AS goals_for,
                   SUM(goals_against) AS goals_against,
                   SUM(shots_for) AS shots_for,
                   SUM(shots_against) AS shots_against
            FROM team_matches
            GROUP BY season, team
        )
        SELECT
            a.season, a.team, a.games, a.points,
            a.goals_for, a.goals_against, a.shots_for, a.shots_against,
            a.games = {MATCHES_PER_TEAM} AS is_full_season,
            a.goals_for - a.goals_against AS goal_diff,
            (a.shots_for - a.shots_against) * l.league_goals_per_shot AS shot_based_goal_diff,
            (a.goals_for - a.goals_against)
                - (a.shots_for - a.shots_against) * l.league_goals_per_shot AS goal_diff_vs_shots
        FROM agg a
        JOIN league l USING (season)
    """)

    # Does over-performing one season carry over to the next?
    con.sql("""
        CREATE OR REPLACE TABLE performance_persistence AS
        SELECT
            t.team,
            t.season,
            t.goal_diff_vs_shots AS gap,
            n.season AS next_season,
            n.goal_diff_vs_shots AS next_gap
        FROM team_seasons t
        JOIN team_seasons n
          ON t.team = n.team
         AND CAST(SUBSTR(n.season, 1, 4) AS INTEGER)
             = CAST(SUBSTR(t.season, 1, 4) AS INTEGER) + 1
        WHERE t.is_full_season AND n.is_full_season
    """)


def report_shot_performance(con):
    print("Biggest over- and under-performers vs their shots (one season):")
    con.sql("""
        (SELECT season, team, goal_diff,
                ROUND(shot_based_goal_diff, 1) AS shot_based_goal_diff,
                ROUND(goal_diff_vs_shots, 1) AS goal_diff_vs_shots
         FROM team_seasons WHERE is_full_season
         ORDER BY goal_diff_vs_shots DESC LIMIT 5)
        UNION ALL
        (SELECT season, team, goal_diff,
                ROUND(shot_based_goal_diff, 1),
                ROUND(goal_diff_vs_shots, 1)
         FROM team_seasons WHERE is_full_season
         ORDER BY goal_diff_vs_shots ASC LIMIT 5)
    """).show(max_width=200)

    print("Does the gap carry over to the next season?")
    con.sql("""
        SELECT COUNT(*) AS team_season_pairs,
               ROUND(CORR(gap, next_gap), 3) AS correlation
        FROM performance_persistence
    """).show(max_width=200)