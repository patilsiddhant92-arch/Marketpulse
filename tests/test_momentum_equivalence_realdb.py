"""Momentum scanner parity vs the OLD endpoint SQL on the live DB (read-only).

Run: MP_DB_PATH=<live db> pytest -m realdb tests/test_momentum_equivalence_realdb.py

`old_sql` below is the old `/api/screener/momentum` query builder copied verbatim from
App/api/server.py at d871ff9 (f-string interpolation and all — it only ever runs here, on
fixed test parameters). The v2 service must return the same symbols in the same order.
"""
from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

import duckdb
import pytest

from App.services import db, momentum

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.realdb


def _live_db() -> Path:
    env = os.environ.get("MP_DB_PATH", "").strip()
    return Path(env) if env else ROOT / "Database" / "marketpulse.duckdb"


def old_sql(lookback_days=20, min_mcap_cr=1000.0, min_volume=1000000.0, min_avg_volume_20d=0.0, max_52w_away_pct=25.0,
            min_52w_low_pct=50.0, cmp_gt_10=True, cmp_gt_200=True, ohlc_gt_10=False, ohlc_gt_20=False, ema10_gt_20=True,
            ema20_gt_50=True, ema50_gt_100=True, ema100_gt_200=True, sma50_gt_150=False, sma150_gt_200=False,
            sma_cmp_gt_50=False, sma_cmp_gt_150_200=False, sma200_rising=False, delivery_thrust=False, coiling_nr7=False,
            weekly_rsi_60=False, limit=300):
    # ---- verbatim from d871ff9:App/api/server.py get_momentum_screener (debug_symbol omitted) ----
    trigger_where = [
        "i.close_price > 15.0",  # Penny stock cutoff
    ]
    if min_mcap_cr > 0:
        trigger_where.append(f"COALESCE(m.market_cap_cr, 0.0) >= {min_mcap_cr}")
    if min_volume > 0:
        trigger_where.append(f"i.volume >= {min_volume}")
    elif min_avg_volume_20d > 0:
        trigger_where.append(f"i.volume >= {min_avg_volume_20d}")
    if max_52w_away_pct < 99.0:
        trigger_where.append(f"i.away_52w_high_pct >= -{abs(max_52w_away_pct)}")
    if min_52w_low_pct > 0:
        trigger_where.append(f"COALESCE(i.away_52w_low_pct, 999.0) >= {min_52w_low_pct}")
    if cmp_gt_10:
        trigger_where.append("(i.away_10ema_pct IS NOT NULL AND i.away_10ema_pct >= 0)")
    if cmp_gt_200:
        trigger_where.append("(i.ema_200 IS NULL OR i.close_price > i.ema_200)")
    if ohlc_gt_10:
        trigger_where.append("(i.ema_10 IS NOT NULL AND i.open_price > i.ema_10 AND i.high_price > i.ema_10 AND i.low_price > i.ema_10 AND i.close_price > i.ema_10)")
    if ohlc_gt_20:
        trigger_where.append("(i.ema_20 IS NOT NULL AND i.open_price > i.ema_20 AND i.high_price > i.ema_20 AND i.low_price > i.ema_20 AND i.close_price > i.ema_20)")
    if ema10_gt_20:
        trigger_where.append("(i.ema_10 IS NULL OR i.ema_20 IS NULL OR i.ema_10 > i.ema_20)")
    if ema20_gt_50:
        trigger_where.append("(i.ema_20 IS NULL OR i.ema_50 IS NULL OR i.ema_20 > i.ema_50)")
    if ema50_gt_100:
        trigger_where.append("(i.ema_50 IS NULL OR i.ema_100 IS NULL OR i.ema_50 > i.ema_100)")
    if ema100_gt_200:
        trigger_where.append("(i.ema_100 IS NULL OR i.ema_200 IS NULL OR i.ema_100 > i.ema_200)")
    if sma50_gt_150:
        trigger_where.append("(i.sma_50 IS NULL OR i.sma_150 IS NULL OR i.sma_50 > i.sma_150)")
    if sma150_gt_200:
        trigger_where.append("(i.sma_150 IS NULL OR i.sma_200 IS NULL OR i.sma_150 > i.sma_200)")
    if sma_cmp_gt_50:
        trigger_where.append("(i.sma_50 IS NULL OR i.close_price > i.sma_50)")
    if sma_cmp_gt_150_200:
        trigger_where.append("((i.sma_150 IS NULL OR i.close_price > i.sma_150) AND (i.sma_200 IS NULL OR i.close_price > i.sma_200))")
    if sma200_rising:
        trigger_where.append("(i.sma_200_rising IS TRUE)")
    if delivery_thrust:
        trigger_where.append("(i.delivery_spike = true AND i.price_up_delivery_up = true)")
    current_where = [
        "c.close_price > 15.0",  # Penny stock cutoff
    ]
    if min_mcap_cr > 0:
        current_where.append(f"COALESCE(m.market_cap_cr, 0.0) >= {min_mcap_cr}")
    if min_avg_volume_20d > 0:
        current_where.append(f"c.avg_volume_20d >= {min_avg_volume_20d}")
    if max_52w_away_pct < 99.0:
        current_where.append(f"c.away_52w_high_pct >= -{abs(max_52w_away_pct)}")
    if min_52w_low_pct > 0:
        current_where.append(f"COALESCE(c.away_52w_low_pct, 999.0) >= {min_52w_low_pct}")
    if cmp_gt_10:
        current_where.append("(c.away_10ema_pct IS NOT NULL AND c.away_10ema_pct >= 0)")
    if cmp_gt_200:
        current_where.append("(c.ema_200 IS NULL OR c.close_price > c.ema_200)")
    if ema10_gt_20:
        current_where.append("(c.ema_10 IS NULL OR c.ema_20 IS NULL OR c.ema_10 > c.ema_20)")
    if ema20_gt_50:
        current_where.append("(c.ema_20 IS NULL OR c.ema_50 IS NULL OR c.ema_20 > c.ema_50)")
    if ema50_gt_100:
        current_where.append("(c.ema_50 IS NULL OR c.ema_100 IS NULL OR c.ema_50 > c.ema_100)")
    if ema100_gt_200:
        current_where.append("(c.ema_100 IS NULL OR c.ema_200 IS NULL OR c.ema_100 > c.ema_200)")
    if sma50_gt_150:
        current_where.append("(c.sma_50 IS NULL OR c.sma_150 IS NULL OR c.sma_50 > c.sma_150)")
    if sma150_gt_200:
        current_where.append("(c.sma_150 IS NULL OR c.sma_200 IS NULL OR c.sma_150 > c.sma_200)")
    if sma_cmp_gt_50:
        current_where.append("(c.sma_50 IS NULL OR c.close_price > c.sma_50)")
    if sma_cmp_gt_150_200:
        current_where.append("((c.sma_150 IS NULL OR c.close_price > c.sma_150) AND (c.sma_200 IS NULL OR c.close_price > c.sma_200))")
    if sma200_rising:
        current_where.append("(c.sma_200_rising IS TRUE)")
    if delivery_thrust:
        current_where.append("(c.close_price > c.ema_20)")
    if coiling_nr7:
        current_where.append("((c.nr7 = true OR c.inside_bar = true) AND COALESCE(c.vcp_score, 0) >= 40)")
    if weekly_rsi_60:
        current_where.append("(c.rsi_14 >= 60 AND COALESCE(c.rsi_14_w, 50) >= 60)")
    return f"""
        WITH dates AS (
            SELECT DISTINCT trade_date FROM indicators_daily
            ORDER BY trade_date DESC LIMIT {lookback_days}
        ),
        bounds AS (
            SELECT min(trade_date) AS min_d, max(trade_date) AS max_d FROM dates
        ),
        trigger_hits AS (
            SELECT i.symbol, max(i.trade_date) AS trigger_date,
                   bool_or(COALESCE(i.delivery_spike, false)) AS trigger_delivery_spike
            FROM indicators_daily i
            JOIN bounds b ON i.trade_date BETWEEN b.min_d AND b.max_d
            JOIN stocks_master m USING(symbol)
            WHERE {' AND '.join(trigger_where)}
            GROUP BY i.symbol
        )
        SELECT
            c.symbol,
            trigger_hits.trigger_date,
            COALESCE(m.sector, 'General') AS sector,
            COALESCE(m.industry, m.sector, 'General') AS industry,
            c.rs_percentile AS rs_percentile,
            ROUND(c.away_10ema_pct, 2) AS away_10ema_pct,
            CASE
                WHEN c.away_10ema_pct >= 0 AND c.away_10ema_pct <= 2 THEN '0_2%'
                WHEN c.away_10ema_pct > 2 AND c.away_10ema_pct <= 5 THEN '2_5%'
                WHEN c.away_10ema_pct > 5 AND c.away_10ema_pct <= 10 THEN '5_10%'
                WHEN c.away_10ema_pct > 10 THEN '10%+'
                ELSE 'Below 10EMA'
            END AS bucket
        FROM indicators_daily c
        JOIN trigger_hits USING(symbol)
        JOIN bounds b ON c.trade_date = b.max_d
        LEFT JOIN stocks_master m ON c.symbol = m.symbol
        WHERE {' AND '.join(current_where)}
        ORDER BY
            CASE
                WHEN c.away_10ema_pct >= 0 AND c.away_10ema_pct <= 2 THEN 1
                WHEN c.away_10ema_pct > 2 AND c.away_10ema_pct <= 5 THEN 2
                WHEN c.away_10ema_pct > 5 AND c.away_10ema_pct <= 10 THEN 3
                WHEN c.away_10ema_pct > 10 THEN 4
                ELSE 5
            END ASC,
            c.away_10ema_pct ASC
        LIMIT {limit}
    """


def old_buckets_tv(df) -> str:
    """Verbatim from d871ff9 (buckets_tv)."""
    buckets_tv_parts = []
    if not df.empty and "bucket" in df.columns:
        for b_label in ["0_2%", "2_5%", "5_10%", "10%+"]:
            b_syms = df[df["bucket"] == b_label]["symbol"].dropna().unique().tolist()
            if b_syms:
                tv_formatted = [f"NSE:{s.replace('-', '_')}" for s in b_syms]
                buckets_tv_parts.append(f"###{b_label}," + ",".join(tv_formatted))
    return ",".join(buckets_tv_parts)


# Default + the old UI's preset buttons and toggles (as the old React UI sent them).
SMA = dict(sma50_gt_150=True, sma150_gt_200=True, sma_cmp_gt_50=True, sma_cmp_gt_150_200=True, sma200_rising=True)
NO_EMA = dict(ema10_gt_20=False, ema20_gt_50=False, ema50_gt_100=False, ema100_gt_200=False)
CASES = {
    "default": {},
    "sma_template": {**SMA, **NO_EMA},
    "breakouts": {"max_52w_away_pct": 5.0, **NO_EMA},
    "delivery": {"delivery_thrust": True},
    "coiling": {"coiling_nr7": True, "max_52w_away_pct": 15.0},
    "mtf": {"weekly_rsi_60": True},
    "avg20d": {"min_volume": 0.0, "min_avg_volume_20d": 2_500_000.0},
    "ohlc": {"ohlc_gt_10": True, "ohlc_gt_20": True, "lookback_days": 5},
    "lookback1": {"lookback_days": 1},
    "clear": {"cmp_gt_10": False, "cmp_gt_200": False, **NO_EMA, "max_52w_away_pct": 99.0, "min_52w_low_pct": 0.0,
              "min_mcap_cr": 0.0, "min_volume": 0.0},
}


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    path = _live_db()
    if not path.exists():
        pytest.skip("live market DB not available")
    mp = pytest.MonkeyPatch()
    mp.setenv("MP_DB_PATH", str(path))
    db.clear_cache()
    con = duckdb.connect(str(path), read_only=True)
    yield con
    con.close()
    mp.undo()


@pytest.mark.parametrize("case", list(CASES))
def test_symbols_and_order_match_old_sql(live, case):
    kw = CASES[case]
    old = live.execute(old_sql(**kw)).fetchdf()
    params = momentum.Params(**{k: v for k, v in kw.items() if k in asdict(momentum.Params())})
    res = momentum.run(None, params)
    new_syms = [r["symbol"] for r in res.rows]
    old_syms = old["symbol"].tolist()
    if len(old_syms) < 300:  # the old LIMIT 300 truncated silently; v2 returns everything
        assert new_syms == old_syms, (case, set(old_syms) ^ set(new_syms))
        assert res.extra["buckets_tv"] == old_buckets_tv(old), case
    else:
        assert new_syms[:300] == old_syms, case
    assert [r["bucket"] for r in res.rows[: len(old)]] == old["bucket"].tolist()
    assert [str(r["trigger_date"]) for r in res.rows[: len(old)]] == [str(d.date()) for d in old["trigger_date"]]
