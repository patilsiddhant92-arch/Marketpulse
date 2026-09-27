"""Evidence engine (spec §5, §7.6): studies history so the app can say what happened before.

    from Scripts.evidence import build_evidence_tables, write_evidence_tables
    tables = build_evidence_tables(con)            # read-only connection (or a dict of frames)
    write_evidence_tables(out_con, tables)         # CREATE OR REPLACE each table

Tables (column docs in each module's docstring):

  setup_outcomes            one row per setup identity: fill, stop, R path, 1R/2R, MAE/MFE, context
  setup_outcome_stats       queue × environment × group quadrant (+ 'all' rollups); n < 30 => insufficient sample
  environment_calibration   outcomes per environment state + the §6.1.5 ship gate
  market_env_daily          standardisable environment vector per session (+ forward MidSml400 returns)
  market_analogs            10 nearest past sessions per session (excl. the latest 60), forward outcomes
  market_analog_validation  analog-mean vs realised forward returns (n printed)
  big_move_events           eligible big moves (UC / +30 % in 20 / +50 % in 60), mcap >= ₹1,000 Cr at T-1, catalysts
  big_move_features         long: event_id × role (event/control) × offset (T-1/5/20/60) × feature → value
  big_move_controls         matched controls (date + Industry + mcap quintile)
  big_move_lift             lift per feature (all / train / test, purged split) with n
  big_move_precision        precision of rules over eligible stock-days (test period) vs base rate
  big_move_paths            median feature path T-60…T+20, movers vs controls
  big_move_catalyst_stats   catalyst shares
  big_move_group_stats      big movers by taxonomy level (Broad Sector / Sector / Broad Industry / Industry)
  group_entry_study         forward excess return after a group enters Leading
  pre_move_watch            last 60 sessions: stock-days matching >= 2 top traits (research label)
  evidence_meta             run metadata (sources, fallbacks, timings, row counts)
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from .analogs import add_analog_ordinals, analog_validation, environment_vectors, market_analogs
from .big_moves import build_big_moves, stock_day_frame
from .common import attach_context, environment_states, fmt_json, group_states, mcap_basis_summary, pit_mcap, LEVELS
from .loaders import load_frames
from .outcomes import aggregate_setup_outcomes, compute_setup_outcomes, environment_calibration
from .setups import SETUP_COLUMNS, assign_identity, historical_setups_from_indicators

log = logging.getLogger(__name__)

TABLES = (
    "setup_outcomes", "setup_outcome_stats", "environment_calibration", "market_env_daily", "market_analogs",
    "market_analog_validation", "big_move_events", "big_move_features", "big_move_controls", "big_move_lift",
    "big_move_precision", "big_move_paths", "big_move_catalyst_stats", "big_move_group_stats", "group_entry_study",
    "pre_move_watch", "evidence_meta",
)
INDEXES = {
    "setup_outcomes": [("idx_setup_outcomes_queue_date", "queue, signal_date"), ("idx_setup_outcomes_symbol", "symbol")],
    "market_analogs": [("idx_market_analogs_date", "as_of_date")],
    "big_move_events": [("idx_big_move_events_date", "event_date"), ("idx_big_move_events_id", "event_id")],
    "big_move_features": [("idx_big_move_features_id", "event_id")],
    "pre_move_watch": [("idx_pre_move_watch_date", "trade_date")],
}
HISTORICAL_QUEUES = ("darvas_squeeze", "vcp", "momentum")
LAST_RUN: dict[str, Any] = {}

__all__ = ["TABLES", "build_evidence_tables", "write_evidence_tables", "compute_setup_outcomes",
           "historical_setups_from_indicators", "LAST_RUN"]


def _setups_from_setup_daily(sd: pd.DataFrame | None, sessions: pd.Series) -> pd.DataFrame | None:
    if sd is None or sd.empty or "queue" not in sd.columns:
        return None
    s = sd.copy()
    if "timeframe" in s.columns:
        s = s.loc[s["timeframe"].fillna("D").astype(str) == "D"]
    keep = [c for c in SETUP_COLUMNS if c in s.columns]
    s = s[keep].copy()
    s["source"] = "setup_daily"
    if "setup_id" not in s.columns or s["setup_id"].isna().any():
        s = assign_identity(s.drop(columns=[c for c in ("setup_id", "first_seen", "setup_age_sessions") if c in s.columns]),
                            sessions)
    return s


def build_evidence_tables(con_or_frames: Any, *, derived_con: duckdb.DuckDBPyConnection | None = None,
                          pr_dir: Path | None = None, cache_dir: Path | None = None, horizon: int = 20,
                          analog_dates: list | None = None) -> dict[str, pd.DataFrame]:
    """Build all evidence tables. `con_or_frames`: a DuckDB connection (read-only is fine) or the dict
    returned by `loaders.load_frames`. `analog_dates` limits market-analog queries (tests)."""
    timings: dict[str, float] = {}
    t0 = time.time()

    def lap(name: str, start: float) -> None:
        timings[name] = round(time.time() - start, 2)
        log.info("evidence: %s %.1fs", name, timings[name])

    s = time.time()
    frames = con_or_frames if isinstance(con_or_frames, dict) else load_frames(con_or_frames, derived_con, pr_dir, cache_dir)
    lap("load", s)
    meta = dict(frames.get("meta", {}))
    ind = frames["indicators"]
    if not (ind["symbol"].is_monotonic_increasing and ind.groupby("symbol", sort=False)["trade_date"].is_monotonic_increasing.all()):
        ind = ind.sort_values(["symbol", "trade_date"])
    ind = ind.reset_index(drop=True)
    if not isinstance(con_or_frames, dict):
        frames["indicators"] = None  # one copy only (memory)
    sessions = pd.Series(sorted(ind["trade_date"].unique()))
    master = frames.get("stocks_master")
    pr = frames.get("pr")

    s = time.time()
    mc = pit_mcap(ind, pr_mcap=pr["mcap"] if pr else None, reference=frames.get("security_reference_daily"), master=master)
    ind["mcap_cr"] = mc["mcap_cr"].to_numpy()
    ind["mcap_basis"] = mc["mcap_basis"].to_numpy()
    meta["mcap_basis_rows"] = mcap_basis_summary(mc)
    lap("mcap", s)

    env = environment_states(frames.get("regime_daily"), frames.get("breadth_daily"))
    group_levels = {lv: group_states(frames.get("group_daily"), frames.get("sector_rotation"), lv) for lv in LEVELS}
    meta["env_source"] = env["env_source"].iloc[0] if len(env) else None
    meta["quadrant_source"] = group_levels["Industry"]["quadrant_source"].iloc[0] if len(group_levels["Industry"]) else None

    # ---- setups and outcomes
    s = time.time()
    daily = _setups_from_setup_daily(frames.get("setup_daily"), sessions)
    have = set(daily["queue"].unique()) if daily is not None else set()
    want = tuple(q for q in HISTORICAL_QUEUES if q not in have)
    hist = historical_setups_from_indicators(ind, master, queues=want, sessions=sessions) if want else None
    setups = pd.concat([x for x in (daily, hist) if x is not None and not x.empty], ignore_index=True) if (
        (daily is not None and not daily.empty) or (hist is not None and not hist.empty)) else pd.DataFrame(columns=SETUP_COLUMNS)
    meta["setup_sources"] = ({f"{q}:{src}": int(v) for (q, src), v in setups.groupby(["queue", "source"]).size().items()}
                             if not setups.empty else {})
    lap("setups", s)

    s = time.time()
    carry = [c for c in ("source", "features") if c in setups.columns]
    out = compute_setup_outcomes(setups, ind, horizon=horizon, sessions=sessions, carry=carry)
    snap = ind[["symbol", "trade_date", "rs_percentile", "rvol", "range_50d_pct", "delivery_pct", "mcap_cr", "mcap_basis",
                "avg_traded_value_cr_20d"]].rename(columns={"trade_date": "signal_date", "range_50d_pct": "base_depth_pct",
                                                            "avg_traded_value_cr_20d": "adv_cr"})
    out = out.merge(snap, on=["symbol", "signal_date"], how="left")
    out = attach_context(out, "signal_date", env, group_levels["Industry"], master)
    out = add_analog_ordinals(out)
    lap("outcomes", s)
    stats = aggregate_setup_outcomes(out)
    calib = environment_calibration(out)

    # ---- market analogs
    s = time.time()
    envv = environment_vectors(ind, frames.get("breadth_daily"), frames["index_daily"], sessions)
    analogs = market_analogs(envv, verdicts=env if meta.get("env_source") == "regime_daily.verdict" else None,
                             query_dates=analog_dates)
    validation = analog_validation(analogs, envv)
    lap("market_analogs", s)

    # ---- big moves
    import gc
    del setups, daily, hist, snap
    gc.collect()
    s = time.time()
    sd = stock_day_frame(ind, mcap=mc, master=master, reference=frames.get("security_reference_daily"), env=env,
                         group_levels=group_levels, deals=frames.get("deals"), pr=pr,
                         events_tbl=frames.get("security_events"), corp_actions=frames.get("corporate_actions"))
    lap("stock_day_features", s)
    s = time.time()
    bm = build_big_moves(sd, pr=pr, events_tbl=frames.get("security_events"), corp_actions=frames.get("corporate_actions"),
                         deals=frames.get("deals"), group_levels=group_levels, index_daily=frames["index_daily"],
                         sessions=sessions)
    all_events = bm.pop("_all_events")
    ev = bm["big_move_events"]
    ev["verdict_then"] = ev["environment_state"] if meta.get("env_source") == "regime_daily.verdict" else None
    if master is not None and "security_name" in master.columns:
        ev["security_name"] = ev["symbol"].map(master.drop_duplicates("symbol").set_index("symbol")["security_name"])
    meta["big_move_candidates"] = int(len(all_events))
    meta["big_move_eligible"] = int(all_events["eligible"].sum())
    meta["big_move_mcap_basis"] = mcap_basis_summary(bm["big_move_events"])
    lap("big_moves", s)

    tables: dict[str, pd.DataFrame] = {
        "setup_outcomes": out, "setup_outcome_stats": stats, "environment_calibration": calib,
        "market_env_daily": envv, "market_analogs": analogs, "market_analog_validation": validation, **bm,
    }
    timings["total"] = round(time.time() - t0, 2)
    meta["timings_s"] = timings
    meta["rows"] = {k: int(len(v)) for k, v in tables.items()}
    meta["sessions"] = {"first": str(sessions.iloc[0].date()), "last": str(sessions.iloc[-1].date()), "n": int(len(sessions))}
    meta["pr_archive"] = None if pr is None else {"files": int(len(pr["files"])), "mcap_rows": int(len(pr["mcap"])),
                                                  "board_meetings": int(len(pr["board_meetings"]))}
    tables["evidence_meta"] = pd.DataFrame({"key": list(meta), "value": [fmt_json(v) for v in meta.values()]})
    LAST_RUN.clear()
    LAST_RUN.update(meta)
    return tables


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if str(out[c].dtype) in ("float32",):
            out[c] = out[c].astype("float64")
        if str(out[c].dtype).startswith("datetime64"):
            out[c] = out[c].astype("datetime64[us]")  # DuckDB TIMESTAMP (not TIMESTAMP_NS)
        if out[c].dtype == object or str(out[c].dtype) in ("str", "string"):
            sample = out[c].dropna().head(50)
            if len(sample) and all(isinstance(x, (list, tuple)) for x in sample):
                continue
            if len(sample) and all(isinstance(x, (bool, np.bool_)) for x in sample):
                out[c] = out[c].astype("boolean")
            elif len(sample) and all(isinstance(x, pd.Timestamp) for x in sample):
                out[c] = pd.to_datetime(out[c]).astype("datetime64[us]")
            elif len(sample) and all(isinstance(x, (int, float, np.integer, np.floating)) for x in sample):
                out[c] = pd.to_numeric(out[c], errors="coerce")
            else:
                out[c] = out[c].astype("object").where(out[c].notna(), None).map(lambda x: x if x is None else str(x))
    return out


def write_evidence_tables(con: duckdb.DuckDBPyConnection, tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    """CREATE OR REPLACE each table (never touches other tables). Returns row counts."""
    counts = {}
    for name, df in tables.items():
        if name.startswith("_") or df is None:
            continue
        view = f"_ev_{name}"
        if df.shape[1] == 0:
            df = pd.DataFrame({"_empty": pd.Series(dtype="object")})
        con.register(view, _prepare(df))
        try:
            con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM {view}')
        finally:
            con.unregister(view)
        for idx, cols in INDEXES.get(name, []):
            con.execute(f'CREATE INDEX IF NOT EXISTS {idx} ON "{name}" ({cols})')
        counts[name] = int(len(df))
    return counts
