import duckdb
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
SEASONS = {"2011-12": "1112", "2012-13": "1213",
           "2013-14": "1314", "2014-15": "1415",
           "2015-16": "1516", "2016-17": "1617",
           "2017-18": "1718", "2018-19": "1819",
           "2019-20": "1920", "2020-21": "2021",
           "2021-22": "2122", "2022-23": "2223",
           "2023-24": "2324", "2024-25": "2425",
           "2025-26": "2526", "2026-27": "2627"
           }

def download_season(label, code, force=True):
    dest = DATA_DIR / f"EPL {label} Season.csv"
    if dest.exists() and not force:
        return
    url = f"https://www.football-data.co.uk/mmz4281/{code}/E0.csv"
    urllib.request.urlretrieve(url, dest)
    print(f"Downloaded {label} season to {dest}")

def main():
    con = duckdb.connect("football.duckdb")  # saves your work to a file
    # con.execute(f"SET data_directory='{DATA_DIR}'")

    # Ensure the data directory exists before downloading
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("Looking in:", DATA_DIR)
    print("Found:", [p.name for p in DATA_DIR.glob("*.csv")])
    # At this point, all CSV files for the specified seasons should be downloaded into the data directory.

    # Move the download step after ensuring the data directory exists
    for label, code in SEASONS.items():
        download_season(label, code, force=True)

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
    """).show(max_width=200)

if __name__ == "__main__":
    main()