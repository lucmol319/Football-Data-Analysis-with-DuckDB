import duckdb
con = duckdb.connect("football.duckdb", read_only=True)
print("Extra Test")
con.sql("""
    SELECT season, COUNT(*) AS matches, COUNT(odds_home) AS with_odds
    FROM matches GROUP BY season ORDER BY season
""").show(max_width=200)