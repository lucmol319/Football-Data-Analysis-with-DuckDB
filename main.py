import duckdb
print(duckdb.sql("SELECT 42 AS answer"))

con = duckdb.connect("football.duckdb")  # saves your work to a file

"""
Create or replace the raw_matches table by reading all CSV files in the data directory
data/*.csv reads every CSV file in the folder.
union_by_name = true lines columns up by name, so it still works if one season has extra columns the other lacks.
filename = true adds a column saying which file each row came from. You'll use this to get the season.
all_varchar = true loads everything as text, which avoids type errors when files are inconsistent. You convert the types in the next step.
"""
con.sql("""
    CREATE OR REPLACE TABLE raw_matches AS
    SELECT *
    FROM read_csv(
        'data/*.csv',
        union_by_name = true,
        filename = true,
        all_varchar = true
    )
""")

con.sql("SELECT filename, COUNT(*) AS rows FROM raw_matches GROUP BY filename").show()

con.sql("""
    CREATE OR REPLACE TABLE matches AS
    SELECT
        filename,
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

con.sql("""
    SELECT
        filename,
        COUNT(*) AS matches,
        ROUND(AVG(home_goals), 2) AS avg_home_goals,
        ROUND(AVG(away_goals), 2) AS avg_away_goals,
        ROUND(AVG(CASE WHEN result = 'H' THEN 1.0 ELSE 0 END), 3) AS home_win_rate
    FROM matches
    GROUP BY filename
    ORDER BY filename
""").show()

duckdb.sql("""
    SELECT HomeTeam, AwayTeam, FTHG, FTAG, FTR
    FROM read_csv('https://www.football-data.co.uk/mmz4281/2526/E0.csv')
    LIMIT 10
""").show()