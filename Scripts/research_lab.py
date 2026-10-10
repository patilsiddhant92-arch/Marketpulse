"""CLI: precompute the Research tab's evidence studies (HarkPro/10-tab-research.md §§11-13).

    python Scripts/research_lab.py [--db <market.duckdb>] [--out <research_lab.duckdb>]

Reads the market DB READ-ONLY and writes small derived tables to --out (default: research_lab.duckdb
next to the market DB, which the API reads; MP_RESEARCH_DB_PATH overrides). --out may also be a copy of
the market DB. Tables:

  research_lab_meta        key/value: version, study_end, built_at, source sessions
  research_regime_daily    one row per session: EW market, Choppiness / ER / ADX, breakout follow-through,
                           point-in-time percentiles, regime quadrant, forward outcomes
  research_size_daily      EW large / mid / small indices (index study)
  research_big_movers      stocks that doubled (low -> peak) in the 12 months to the study end + ladder
  research_caught          first fresh fire per preset per big mover
  research_precision       fresh-fire precision per preset (+50% within 120 sessions)
  research_premove_events  early lifts with 30 traits and their outcome
  research_signal_log      the live Desk signal log (App/services/research_signals.py): NEVER rebuilt whole.
                           New setup_daily signals are inserted once; only their 5/10/20-session grades are
                           refreshed. --skip-signals leaves it alone.

The other tables are rebuilt whole. The API falls back to computing in-process when the tables are missing or
built for another study end.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from App.services import db  # noqa: E402
from App.services import research_bigmove as bigmove  # noqa: E402
from App.services import research_lab as lab  # noqa: E402
from App.services import research_premove as premove  # noqa: E402
from App.services import research_regime as regime  # noqa: E402
from App.services import research_signals as signals  # noqa: E402


def build(out: Path, with_signals: bool = True) -> dict[str, int]:
    """Compute every study from the market DB (db.market_db_path()) and write them to `out`; then log and
    grade the Desk signals (research_signal_log) unless `with_signals` is False."""
    t0 = time.time()
    with db.market_conn() as con:
        end = lab.study_end(con, None)
        if end is None:
            raise SystemExit("market DB has no sessions")
        latest = db.latest_session(con)
        tables: dict[str, pd.DataFrame] = {}
        tables["research_regime_daily"] = regime.compute_daily(con, end)
        tables["research_size_daily"] = regime.compute_size_daily(con, end)
        movers, caught = bigmove.compute_movers(con, end)
        tables["research_big_movers"] = movers
        tables["research_caught"] = caught
        tables["research_precision"] = bigmove.compute_precision(con, end)
        tables["research_premove_events"] = premove.compute_events(con, end)
    if out.resolve() == db.market_db_path().resolve():
        raise SystemExit("--out must not be the live market DB (open read-only); use a copy or the sidecar")
    meta = pd.DataFrame({"key": ["version", "study_end", "latest_session", "built_at", "seconds"],
                         "value": [str(lab.BUILD_VERSION), end.isoformat(), latest.isoformat() if latest else "",
                                   datetime.now(timezone.utc).isoformat(timespec="seconds"), f"{time.time() - t0:.1f}"]})
    out.parent.mkdir(parents=True, exist_ok=True)
    w = duckdb.connect(str(out))
    try:
        w.execute("BEGIN")
        for name, df in {**tables, "research_lab_meta": meta}.items():
            df = df.copy()
            for c in df.columns:
                if df[c].dtype == object:
                    nn = df[c].dropna()
                    if len(nn) and all(isinstance(x, (pd.Timestamp, datetime)) for x in nn):
                        df[c] = pd.to_datetime(df[c])
                    else:
                        df[c] = df[c].where(df[c].notna(), None)
            w.register("_df", df)
            w.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _df")
            w.unregister("_df")
        w.execute("COMMIT")
    finally:
        w.close()
    counts = {k: int(len(v)) for k, v in tables.items()}
    if with_signals:
        counts.update(update_signal_log(out, tables["research_regime_daily"]))
    return counts


def update_signal_log(out: Path, regime_daily: pd.DataFrame | None = None) -> dict[str, int]:
    """Insert new setup_daily signals into research_signal_log (in `out`) and refresh their grades."""
    ew = None
    if regime_daily is not None and len(regime_daily) and "ew_index" in regime_daily:
        ew = regime_daily.set_index(pd.to_datetime(regime_daily.trade_date)).ew_index
    with db.market_conn() as con:
        w = duckdb.connect(str(out))
        try:
            w.execute("BEGIN")
            res = signals.update(con, w, ew)
            w.execute("COMMIT")
        except Exception:
            w.execute("ROLLBACK")
            raise
        finally:
            w.close()
    return {"research_signal_log": res["total"], "signals_added": res["added"], "signals_graded": res["graded"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="market DB (default: MP_DB_PATH or Database/marketpulse.duckdb)")
    ap.add_argument("--out", help="output DB (default: research_lab.duckdb next to the market DB)")
    ap.add_argument("--skip-signals", action="store_true", help="do not log / grade the Desk signals")
    a = ap.parse_args(argv)
    if a.db:
        os.environ["MP_DB_PATH"] = a.db
    out = Path(a.out) if a.out else lab.sidecar_path()
    t = time.time()
    counts = build(out, with_signals=not a.skip_signals)
    for k, v in counts.items():
        print(f"{k:28s} {v:8d} rows")
    print(f"wrote {out} in {time.time() - t:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
