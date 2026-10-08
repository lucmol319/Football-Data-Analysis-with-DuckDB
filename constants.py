from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "football.duckdb"

FIRST_SEASON = 2011 # A season is identified by the year it starts: 2011 means 2011-12.
CURRENT_SEASON = 2026  # still in progress, so it is re-downloaded every run
SEASONS = range(FIRST_SEASON, CURRENT_SEASON + 1)
MATCHES_PER_SEASON = 380  # 20 teams x 19 opponents