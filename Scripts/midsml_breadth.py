"""
MidSmallcap 400 Breadth & Regime Engine.

Computes breadth and regime dynamics specifically for the NIFTY MIDSML 400 universe
(NSE Market Cap ranks 101 to 500), where active swing traders hunt.

Tracks:
- Advances / Declines %
- % Above 10, 20, 50, 200 EMA
- Count of stocks near 52-week highs (within 15%)
- 1-session and 5-session delta momentum
- Automated Regimes: Bull Expansion, Top Warning, Correction, Capitulation Washout, Breadth Thrust
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import duckdb
import pandas as pd

try:
    from config import DB_PATH
except ModuleNotFoundError:
    from Scripts.config import DB_PATH  # type: ignore


def classify_midsml_regime(
    adv_pct: float,
    abv_10_pct: float,
    abv_50_pct: float,
    abv_200_pct: float,
    delta_5d: float = 0.0,
    yest_adv_pct: float | None = None,
) -> dict[str, str]:
    """Automated MidSmallcap 400 Regime & Stance classification."""
    if adv_pct <= 16.0 or (yest_adv_pct is not None and yest_adv_pct <= 16.0 and abv_10_pct <= 20.0):
        regime = "CAPITULATION WASHOUT"
        regime_tone = "bad"
        regime_icon = "⚡"
        status_desc = "90% Down Day / Panic Liquidation Zone"
        stance = "🛡️ DEFENSIVE / HIGH CASH (Washout seen; wait for Breadth Thrust or higher low)"
    elif abv_10_pct >= 55.0 and abv_50_pct >= 50.0 and adv_pct >= 50.0:
        regime = "BULL EXPANSION"
        regime_tone = "good"
        regime_icon = "🟢"
        status_desc = "Healthy broad-based institutional participation"
        stance = "🚀 FULL SWING EXPOSURE (High win-rate breakout environment)"
    elif abv_50_pct < 45.0 and abv_200_pct < 50.0:
        regime = "CORRECTION / DOWNTREND"
        regime_tone = "bad"
        regime_icon = "🔴"
        status_desc = "Majority of mid/small-caps in Stage 4 decline"
        stance = "🛡️ 70-80% CASH (Protect capital; breakouts prone to failure)"
    elif abv_10_pct < 35.0 or delta_5d < -10.0 or abv_50_pct < 50.0:
        regime = "TOP WARNING / DIVERGING"
        regime_tone = "neutral"
        regime_icon = "🟡"
        status_desc = "Internal momentum breaking down; leadership contracting"
        stance = "⚠️ TIGHTEN STOPS / CUT EXPOSURE (Avoid new breakout entries)"
    else:
        regime = "SELECTIVE / NEUTRAL"
        regime_tone = "neutral"
        regime_icon = "⚪"
        status_desc = "Mixed market conditions; stock-specific action"
        stance = "⚖️ SELECTIVE RISK (Strict pivot entry, 3-5% stops)"

    badge = f"{regime_icon} {regime}"
    return {
        "regime": regime,
        "badge": badge,
        "regime_icon": regime_icon,
        "regime_tone": regime_tone,
        "status_desc": status_desc,
        "stance": stance,
    }


def query_midsml_breadth(
    db_path: Path | str | None = None,
    trade_date: str | None = None,
    con: Any | None = None,
) -> dict[str, Any]:
    """
    Compute point-in-time breadth metrics and multi-session momentum for NIFTY MIDSML 400.
    """
    target_path = Path(db_path) if db_path is not None else DB_PATH
    own_con = False
    if con is None:
        if not target_path.exists():
            return {}
        con = duckdb.connect(str(target_path), read_only=True)
        own_con = True

    try:
        # Determine target date
        if trade_date is None:
            max_d = con.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()[0]
            if max_d is None:
                return {}
            target_date_str = pd.to_datetime(max_d).strftime("%Y-%m-%d")
        else:
            target_date_str = str(pd.to_datetime(trade_date).date())

        # Get last 6 distinct trade dates ending at target_date_str
        dates_df = con.execute(
            """
            SELECT DISTINCT trade_date 
            FROM indicators_daily 
            WHERE trade_date <= ?
            ORDER BY trade_date DESC 
            LIMIT 6
            """,
            [target_date_str],
        ).fetchdf()

        if dates_df.empty:
            return {}

        date_list = [pd.to_datetime(d).strftime("%Y-%m-%d") for d in dates_df["trade_date"].tolist()]
        today_str = date_list[0]
        yest_str = date_list[1] if len(date_list) > 1 else None
        d5_str = date_list[-1] if len(date_list) >= 5 else None

        # Compute metrics across these dates for ranks 101 to 500
        sql = """
        WITH ranked AS (
            SELECT 
                symbol,
                market_cap_cr,
                ROW_NUMBER() OVER (ORDER BY market_cap_cr DESC) as mcap_rank
            FROM stocks_master
            WHERE market_cap_cr IS NOT NULL
              AND symbol NOT LIKE '%-RE' AND symbol NOT LIKE '%_RE'
        )
        SELECT 
            i.trade_date,
            r.mcap_rank,
            i.symbol,
            i.close_price,
            i.ema_10,
            i.ema_20,
            i.ema_50,
            i.ema_200,
            i.away_52w_high_pct,
            (p.close_price - p.prev_close) as chg
        FROM indicators_daily i
        JOIN ranked r ON r.symbol = i.symbol
        LEFT JOIN prices_daily p ON p.symbol = i.symbol AND p.trade_date = i.trade_date
        WHERE i.trade_date IN ({})
          AND r.mcap_rank BETWEEN 101 AND 500
        """.format(", ".join(f"'{d}'" for d in date_list))

        raw_df = con.execute(sql).fetchdf()
        if raw_df.empty:
            return {}

        raw_df["trade_date_str"] = pd.to_datetime(raw_df["trade_date"]).dt.strftime("%Y-%m-%d")

        stats_by_date: dict[str, dict[str, Any]] = {}
        for d_str in date_list:
            sub = raw_df[raw_df["trade_date_str"] == d_str]
            total = len(sub)
            if total == 0:
                continue
            adv = int((sub["chg"] > 0).sum())
            dec = int((sub["chg"] < 0).sum())
            adv_pct = round(100.0 * adv / total, 1)
            abv_10 = round(100.0 * (sub["close_price"] > sub["ema_10"]).sum() / total, 1)
            abv_20 = round(100.0 * (sub["close_price"] > sub["ema_20"]).sum() / total, 1)
            abv_50 = round(100.0 * (sub["close_price"] > sub["ema_50"]).sum() / total, 1)
            abv_200 = round(100.0 * (sub["close_price"] > sub["ema_200"]).sum() / total, 1)
            near_52w = int((sub["away_52w_high_pct"] >= -15.0).sum())
            stats_by_date[d_str] = {
                "date": d_str,
                "total": total,
                "adv": adv,
                "dec": dec,
                "adv_pct": adv_pct,
                "abv_10ema": abv_10,
                "abv_20ema": abv_20,
                "abv_50ema": abv_50,
                "abv_200ema": abv_200,
                "near_52w": near_52w,
            }

        t_stat = stats_by_date.get(today_str, {})
        y_stat = stats_by_date.get(yest_str, {}) if yest_str else {}
        d5_stat = stats_by_date.get(d5_str, {}) if d5_str else {}

        if not t_stat:
            return {}

        # Deltas
        chg_adv_1d = round(t_stat["adv_pct"] - y_stat.get("adv_pct", t_stat["adv_pct"]), 1)
        chg_10_1d = round(t_stat["abv_10ema"] - y_stat.get("abv_10ema", t_stat["abv_10ema"]), 1)
        chg_50_1d = round(t_stat["abv_50ema"] - y_stat.get("abv_50ema", t_stat["abv_50ema"]), 1)
        chg_200_1d = round(t_stat["abv_200ema"] - y_stat.get("abv_200ema", t_stat["abv_200ema"]), 1)
        chg_52w_1d = int(t_stat["near_52w"] - y_stat.get("near_52w", t_stat["near_52w"]))

        chg_10_5d = round(t_stat["abv_10ema"] - d5_stat.get("abv_10ema", t_stat["abv_10ema"]), 1)
        chg_50_5d = round(t_stat["abv_50ema"] - d5_stat.get("abv_50ema", t_stat["abv_50ema"]), 1)
        chg_52w_5d = int(t_stat["near_52w"] - d5_stat.get("near_52w", t_stat["near_52w"]))

        # Query Nifty MIDSML 400 and Smallcap index returns for today and yesterday
        idx_q = """
        SELECT index_name, return_1d_pct, return_5d_pct
        FROM index_daily
        WHERE trade_date = ?
          AND UPPER(index_name) IN ('NIFTY MIDSML 400', 'NIFTY SMALLCAP 500', 'NIFTY 50')
        """
        idx_rows = con.execute(idx_q, [today_str]).fetchdf()
        idx_ret: dict[str, float] = {}
        for _, ir in idx_rows.iterrows():
            idx_ret[ir["index_name"].upper()] = float(ir["return_1d_pct"] or 0.0)

        reg_info = classify_midsml_regime(
            adv_pct=t_stat["adv_pct"],
            abv_10_pct=t_stat["abv_10ema"],
            abv_50_pct=t_stat["abv_50ema"],
            abv_200_pct=t_stat["abv_200ema"],
            delta_5d=chg_10_5d,
            yest_adv_pct=y_stat.get("adv_pct") if y_stat else None,
        )

        return {
            "trade_date": today_str,
            "as_of": today_str,
            "universe": "NIFTY MIDSML 400 (Ranks 101-500)",
            "universe_size": int(t_stat.get("total", 400)),
            "adv_pct": float(t_stat.get("adv_pct", 0.0)),
            "abv_200_pct": float(t_stat.get("abv_200ema", 0.0)),
            "regime": reg_info["regime"],
            "badge": reg_info["badge"],
            "regime_icon": reg_info["regime_icon"],
            "regime_tone": reg_info["regime_tone"],
            "status_desc": reg_info["status_desc"],
            "stance": reg_info["stance"],
            "metrics": t_stat,
            "yesterday": y_stat,
            "deltas_1d": {
                "adv_pct": chg_adv_1d,
                "abv_10ema": chg_10_1d,
                "abv_50ema": chg_50_1d,
                "abv_200ema": chg_200_1d,
                "near_52w": chg_52w_1d,
            },
            "deltas_5d": {
                "abv_10ema": chg_10_5d,
                "abv_50ema": chg_50_5d,
                "near_52w": chg_52w_5d,
            },
            "indices": {
                "midsml400_ret_1d": idx_ret.get("NIFTY MIDSML 400"),
                "smallcap500_ret_1d": idx_ret.get("NIFTY SMALLCAP 500"),
                "nifty50_ret_1d": idx_ret.get("NIFTY 50"),
            },
        }
    finally:
        if own_con:
            con.close()


def _clean_val(val: float | int | None, deadband: float = 0.05) -> float:
    if val is None:
        return 0.0
    try:
        f = float(val)
        if abs(f) < deadband:
            return 0.0
        return f
    except (ValueError, TypeError):
        return 0.0


def format_midsml_breadth_barometer(breadth_data: dict[str, Any]) -> str:
    """Format clean, high-impact Telegram breadth barometer text block."""
    if not breadth_data:
        return "🧭 *MIDSML 400 BREADTH:* Data unavailable."

    if "metrics" in breadth_data:
        m = breadth_data["metrics"]
        y = breadth_data.get("yesterday", {})
        d1 = breadth_data.get("deltas_1d", {})
        d5 = breadth_data.get("deltas_5d", {})
        idx = breadth_data.get("indices", {})
        d_str = pd.to_datetime(breadth_data["trade_date"]).strftime("%d-%b-%Y")
        icon = breadth_data.get("regime_icon", "🧭")
        regime = breadth_data.get("regime", "NEUTRAL")
        stance = breadth_data.get("stance", "")
    else:
        m = {
            "adv": breadth_data.get("advancers", 0),
            "dec": breadth_data.get("decliners", 0),
            "adv_pct": breadth_data.get("adv_pct", 0.0),
            "abv_10ema": breadth_data.get("abv_10_pct", 0.0),
            "abv_50ema": breadth_data.get("abv_50_pct", 0.0),
            "abv_200ema": breadth_data.get("abv_200_pct", 0.0),
            "near_52w": breadth_data.get("near_52w_highs", 0),
        }
        y = {}
        d1 = {"abv_10ema": breadth_data.get("delta_1d", 0.0)}
        d5 = {"abv_10ema": breadth_data.get("delta_5d", 0.0)}
        idx = {"midsml400_ret_1d": breadth_data.get("midsml_ret")}
        d_str = pd.to_datetime(breadth_data.get("as_of", "today")).strftime("%d-%b-%Y")
        reg_obj = breadth_data.get("regime")
        if isinstance(reg_obj, dict):
            icon = reg_obj.get("regime_icon", "🧭")
            regime = reg_obj.get("regime", "NEUTRAL")
            stance = reg_obj.get("stance", "")
        else:
            icon = breadth_data.get("regime_icon", "🧭")
            regime = str(breadth_data.get("regime", "NEUTRAL"))
            stance = str(breadth_data.get("stance", ""))

    midsml_ret = _clean_val(idx.get("midsml400_ret_1d"))
    if idx.get("midsml400_ret_1d") is not None:
        sign = "+" if midsml_ret > 0 else ""
        midsml_str = f" · MidSml400: {sign}{midsml_ret:.2f}%" if midsml_ret != 0.0 else " · MidSml400: 0.00%"
    else:
        midsml_str = ""

    y_adv = f"(Yesterday: {y['adv_pct']:.1f}% 💥)" if y.get("adv_pct", 100) <= 18.0 else f"(Prev: {y.get('adv_pct', 0):.1f}%)" if y else ""

    d1_10 = _clean_val(d1.get("abv_10ema", 0))
    d5_10 = _clean_val(d5.get("abv_10ema", 0))
    d1_50 = _clean_val(d1.get("abv_50ema", 0))
    d1_200 = _clean_val(d1.get("abv_200ema", 0))
    d1_52w = int(round(_clean_val(d1.get("near_52w", 0))))
    d5_52w = int(round(_clean_val(d5.get("near_52w", 0))))

    sign_10 = "+" if d1_10 >= 0 else ""
    sign_50 = "+" if d1_50 >= 0 else ""
    sign_200 = "+" if d1_200 >= 0 else ""
    sign_52w = "+" if d1_52w >= 0 else ""

    lines = [
        f"{icon} *MIDSML 400 BREADTH BAROMETER* (`{d_str}`)",
        f"• *Regime:* `{regime}`{midsml_str}",
        f"• *Adv / Dec:* `{m['adv']} Adv / {m['dec']} Dec` ({m['adv_pct']:.1f}% Adv) {y_adv}".rstrip(),
        "• *Moving Average Support (400 Growth Stocks):*",
        f"  - `>10 EMA:` *{m['abv_10ema']:.1f}%* ({sign_10}{d1_10:.1f} pts | 5d: {d5_10:+.1f} pts)",
        f"  - `>50 EMA:` *{m['abv_50ema']:.1f}%* ({sign_50}{d1_50:.1f} pts | Bull threshold: 50%)",
        f"  - `>200 EMA:` *{m['abv_200ema']:.1f}%* ({sign_200}{d1_200:.1f} pts)",
        f"• *Leaders Near 52W High (<=15%):* `{m['near_52w']}` stocks ({d1_52w:+d} / 5d: {d5_52w:+d})",
        f"• *Desk Stance:* {stance}",
    ]
    return "\n".join(lines)


build_midsml_breadth_barometer = format_midsml_breadth_barometer


if __name__ == "__main__":
    data = query_midsml_breadth()
    print(format_midsml_breadth_barometer(data))
