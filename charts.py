import math
from pathlib import Path
import duckdb
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import numpy as np

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "football.duckdb"
OUTPUT_DIR = BASE_DIR / "output"

def load_complete_seasons():
    """Read finished seasons from the season_summary table built by main.py."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows = con.sql("""
        SELECT season, matches, home_win_rate
        FROM season_summary
        WHERE is_complete
        ORDER BY season
    """).fetchall()
    con.close()
    return rows

def plot_home_win_rate(rows):
    """
    Reads season_summary from football.duckdb and saves a chart of home win rate by season to output/home_win_rate_by_season.png.
    It includes the average across seasons, a note on 2020-21, and error bars.
    """
    seasons = [r[0] for r in rows]
    matches = [r[1] for r in rows]
    rate = [r[2] for r in rows]

    # Rough 95% margin of error: how much a win rate can wobble from luck alone
    # in a sample of this size.
    margin = [1.96 * math.sqrt(p * (1 - p) / n) for p, n in zip(rate, matches)]
    average = sum(rate) / len(rate)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.errorbar(seasons, rate, yerr=margin, fmt="o-", capsize=3,
                label="Home win rate (with rough 95% margin of error)")
    ax.axhline(average, linestyle="--", color="gray",
               label=f"Average across seasons ({average:.1%})")

    if "2020-21" in seasons:
        i = seasons.index("2020-21")
        ax.annotate("Mostly played\nwithout fans", xy=(i, rate[i]),
                    xytext=(45, -40), textcoords="offset points",
                    ha="left", arrowprops=dict(arrowstyle="->"))

    ax.set_title("Premier League home win rate by season")
    ax.set_ylabel("Share of matches won by the home team")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_ylim(0.28, 0.55)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="lower left")
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    OUTPUT_DIR.mkdir(exist_ok=True)
    dest = OUTPUT_DIR / "home_win_rate_by_season.png"
    fig.savefig(dest, dpi=150, bbox_inches="tight")
    print(f"Saved chart to {dest}")

def load_calibration(min_matches=30):
    """Probability bands with enough matches to be worth plotting."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows = con.sql(f"""
        SELECT outcome, n, avg_predicted, actual_rate
        FROM calibration
        WHERE n >= {min_matches}
        ORDER BY outcome, bin_start
    """).fetchall()
    con.close()
    return rows

def plot_calibration(rows):
    """If odds are well calibrated, points sit on the diagonal line."""
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", label="Perfect calibration")

    for outcome in ["Home win", "Draw", "Away win"]:
        pts = [r for r in rows if r[0] == outcome]
        if not pts:
            continue
        ax.plot([r[2] for r in pts], [r[3] for r in pts], "-", alpha=0.4)
        ax.scatter([r[2] for r in pts], [r[3] for r in pts],
                   s=[r[1] ** 0.5 * 6 for r in pts], label=outcome)

    ax.set_title("Bet365 odds as forecasts: predicted vs actual")
    ax.set_xlabel("Probability implied by the odds")
    ax.set_ylabel("How often it actually happened")
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")

    # Saves output/odds_calibration.png. If the odds are well calibrated, the points sit on the dashed diagonal.
    # Bigger dots mean more matches, and bands with fewer than 30 matches are dropped.
    OUTPUT_DIR.mkdir(exist_ok=True)
    dest = OUTPUT_DIR / "odds_calibration.png"
    fig.savefig(dest, dpi=150, bbox_inches="tight")
    print(f"Saved chart to {dest}")

def load_team_gaps(min_seasons=5):
    """Average gap per season for teams with enough full seasons."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows = con.sql(f"""
        SELECT team, AVG(goal_diff_vs_shots) AS avg_gap, COUNT(*) AS seasons
        FROM team_seasons
        WHERE is_full_season
        GROUP BY team
        HAVING COUNT(*) >= {min_seasons}
        ORDER BY avg_gap
    """).fetchall()
    con.close()
    return rows


def plot_team_gaps(rows, show_each_end=10):
    """Bar chart of the teams furthest above and below their shot-based expectation."""
    if len(rows) > show_each_end * 2:
        rows = rows[:show_each_end] + rows[-show_each_end:]
    labels = [f"{r[0]} ({r[2]})" for r in rows]
    gaps = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(9, 8))
    colours = ["tab:green" if g >= 0 else "tab:red" for g in gaps]
    ax.barh(labels, gaps, color=colours)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title("Goal difference vs what shots suggest, average per season")
    ax.set_xlabel("Goals per season above (+) or below (-) the shot-based expectation")
    ax.grid(axis="x", alpha=0.3)
    fig.text(0.01, 0.01, "Number of full seasons in brackets. Shots are a crude measure "
             "(no shot quality), so read this as a clue, not a verdict.", fontsize=8)

    OUTPUT_DIR.mkdir(exist_ok=True)
    dest = OUTPUT_DIR / "team_gap_vs_shots.png"
    fig.savefig(dest, dpi=150, bbox_inches="tight")
    print(f"Saved chart to {dest}")


def load_persistence():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows = con.sql("SELECT gap, next_gap FROM performance_persistence").fetchall()
    con.close()
    return rows


def plot_persistence(rows):
    """If over-performance were a lasting skill, points would slope upward."""
    x = np.array([r[0] for r in rows])
    y = np.array([r[1] for r in rows])
    r_value = np.corrcoef(x, y)[0, 1]
    slope, intercept = np.polyfit(x, y, 1)

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(x, y, alpha=0.6)
    xs = np.array([x.min(), x.max()])
    ax.plot(xs, slope * xs + intercept, color="tab:red",
            label=f"Trend line (correlation {r_value:.2f})")
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.axvline(0, color="gray", linewidth=0.8)
    ax.set_title("Does beating your shot numbers carry over to next season?")
    ax.set_xlabel("Gap this season (goal difference vs shots)")
    ax.set_ylabel("Gap the following season")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")

    OUTPUT_DIR.mkdir(exist_ok=True)
    dest = OUTPUT_DIR / "gap_persistence.png"
    fig.savefig(dest, dpi=150, bbox_inches="tight")
    print(f"Saved chart to {dest}")

def main():
    # Question 1: Home win rate
    rows = load_complete_seasons()
    if not rows:
        print("No complete seasons found. Run main.py first.")
        return
    plot_home_win_rate(rows)

    # Question 2: Calibration
    calibration_rows = load_calibration()
    if calibration_rows:
        plot_calibration(calibration_rows)

    # Question 3: Team gaps and performance persistence
    team_gaps = load_team_gaps()
    if team_gaps:
        plot_team_gaps(team_gaps)
    persistence = load_persistence()
    if len(persistence) >= 3:
        plot_persistence(persistence)

if __name__ == "__main__":
    main()