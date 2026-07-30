import sys
from pathlib import Path

print("WARNING: This is a legacy one-off patch script from the original MarketPulse folder.")
print("It is no longer needed for normal use (build_database.py already contains the sector rotation fix).")
print("Exiting without making changes.")
sys.exit(0)

# --- original code kept below for reference only ---
# (It used to surgically replace a buggy build_sector_rotation implementation.)

old_path = Path("d:/Sid/MarketPulse/Scripts/build_database.py")
if not old_path.exists():
    sys.exit(0)

with open(old_path, 'r') as f:
    lines = f.readlines()

out_lines = []
for i, line in enumerate(lines):
    if line.startswith('def build_sector_rotation'):
        break
    out_lines.append(line)

new_code = """def build_sector_rotation(indicators: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    base = indicators.merge(
        master[["symbol", "broad_sector", "sector", "broad_industry", "industry"]],
        on="symbol",
        how="left",
    )
    frames = []
    levels = {
        "Broad Sector": "broad_sector",
        "Sector": "sector",
        "Broad Industry": "broad_industry",
        "Industry": "industry",
    }
    for level_name, col in levels.items():
        d = base.dropna(subset=[col]).copy()
        d = d[d[col].astype(str).str.strip() != ""]
        if d.empty:
            continue
        grouped = d.groupby(["trade_date", col]).apply(
            lambda g: pd.Series(
                {
                    "stocks": g["symbol"].nunique(),
                    "return_5d_pct": g["return_5d_pct"].mean(),
                    "return_1m_pct": g["return_1m_pct"].mean(),
                    "return_3m_pct": g["return_3m_pct"].mean(),
                    "rs_percentile": g["rs_percentile"].mean(),
                    "above_10ema_pct": (g["close_price"] > g["ema_10"]).mean() * 100,
                    "above_50ema_pct": (g["close_price"] > g["ema_50"]).mean() * 100,
                    "above_200ema_pct": (g["close_price"] > g["ema_200"]).mean() * 100,
                    "near_52w_highs": g["near_52w_high"].sum(),
                    "vcp_candidates": g["is_vcp"].sum(),
                    "turnover_cr": g["turnover_cr"].sum(),
                }
            ),
            include_groups=False,
        ).reset_index().rename(columns={col: "group_name"})
        grouped["level"] = level_name
        grouped["rotation_score"] = (
            grouped["rs_percentile"].fillna(0) * 0.40
            + grouped["above_50ema_pct"].fillna(0) * 0.25
            + grouped["above_200ema_pct"].fillna(0) * 0.20
            + grouped["return_1m_pct"].fillna(0).clip(-20, 20) * 0.75
        )
        grouped["rotation_rank"] = grouped.groupby("trade_date")["rotation_score"].rank(ascending=False, method="min")
        grouped = grouped.sort_values(["group_name", "trade_date"])
        grouped["rank_change_5d"] = grouped.groupby("group_name")["rotation_rank"].shift(5) - grouped["rotation_rank"]
        grouped["rank_change_20d"] = grouped.groupby("group_name")["rotation_rank"].shift(20) - grouped["rotation_rank"]
        grouped["score_change_5d"] = grouped.groupby("group_name")["rotation_score"].diff(5)
        grouped["turnover_1d_cr"] = grouped["turnover_cr"]
        grouped["turnover_5d_cr"] = grouped.groupby("group_name")["turnover_cr"].transform(lambda s: s.rolling(5, min_periods=1).sum())
        grouped["turnover_20d_cr"] = grouped.groupby("group_name")["turnover_cr"].transform(lambda s: s.rolling(20, min_periods=1).sum())
        grouped["rotation_state"] = np.select(
            [
                (grouped["rotation_rank"] <= 5) & (grouped["score_change_5d"] >= 0),
                (grouped["rank_change_5d"] >= 5) & (grouped["score_change_5d"] > 0),
                (grouped["rank_change_5d"] >= 2) & (grouped["score_change_5d"] > 0),
                (grouped["rotation_rank"] <= 8) & (grouped["score_change_5d"] < 0),
                (grouped["rotation_rank"] > 8) & (grouped["score_change_5d"] <= 0),
            ],
            ["Leading", "Emerging", "Improving", "Weakening", "Lagging"],
            default="Neutral",
        )
        frames.append(grouped)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def make_screener_results(indicators: pd.DataFrame, master: pd.DataFrame, deals: pd.DataFrame | None = None, sector_rotation: pd.DataFrame | None = None) -> pd.DataFrame:
    latest_date = indicators["trade_date"].max()
    latest = indicators[indicators["trade_date"] == latest_date].merge(
        master[["symbol", "market_cap_cr", "band", "broad_sector", "sector", "broad_industry", "industry"]],
        on="symbol",
        how="left",
    )
"""

for i, line in enumerate(lines):
    if line.startswith('    latest_deals = pd.DataFrame(columns=["symbol"'):
        out_lines.append(new_code)
        out_lines.extend(lines[i:])
        break

with open('d:/Sid/MarketPulse/Scripts/build_database.py', 'w') as f:
    f.writelines(out_lines)
