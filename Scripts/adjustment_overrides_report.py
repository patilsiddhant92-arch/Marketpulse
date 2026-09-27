"""Read-only review list for price gaps that no corporate action explains.

Lists every open (``confidence == 'unconfirmed'``) adjustment row -- ``unexplained_gap`` rows and
unconfirmed mcap issue-size jumps -- with the ratio, the raw close before / on the date, and the
nearest corporate-action text within +/- N days (the DB ``corporate_actions`` table plus any
non-adjusting bc rows such as demergers or rights). Ends with a ready-to-paste YAML stub for
``Input/reference/adjustments_override.yaml``, fully commented out: pick one line per gap
after checking it, uncomment it, and fill in the note. Nothing is written anywhere.

Gaps already marked ``kind: ignore`` in the YAML come back as ``confidence 'reviewed'`` and are
not listed.

Usage:
  python Scripts/adjustment_overrides_report.py [--db PATH] [--root PATH] [--from-db] [--window 30]

By default ``adjust_prices`` is recomputed read-only against the PR zips / mcap files under
``--root`` (no parse cache is read or written), so the list reflects the YAML on disk now.
``--from-db`` uses the stored ``price_adjustments`` table instead (fast, as of the last build).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from config import DB_PATH, ROOT_DIR

OPEN_CONFIDENCE = "unconfirmed"
REPORT_COLUMNS = ["symbol", "ex_date", "kind", "ratio", "prev_date", "prev_close", "close",
                  "nearest_action_date", "action_days_off", "nearest_action"]


def _tables(con) -> set[str]:
    return {row[0] for row in con.execute("SHOW TABLES").fetchall()}


def _read(db_path: Path, name: str, sql: str | None = None) -> pd.DataFrame:
    with duckdb.connect(str(db_path), read_only=True) as con:
        if name not in _tables(con):
            return pd.DataFrame()
        return con.execute(sql or f'SELECT * FROM "{name}"').fetchdf()


def _action_texts(adjustments: pd.DataFrame, corporate_actions: pd.DataFrame) -> pd.DataFrame:
    """(symbol, ex_date, text) for every known corporate action: corporate_actions rows plus the
    bc/mcap rows of the reconciled frame (anything that is not itself an open row under review)."""
    frames = []
    if corporate_actions is not None and not corporate_actions.empty:
        ca = corporate_actions.copy()
        desc = ca["description"].astype("string").fillna("") if "description" in ca.columns else pd.Series("", index=ca.index)
        kind = ca["action_type"].astype("string").fillna("") if "action_type" in ca.columns else pd.Series("", index=ca.index)
        text = [f"{k}: {d}".strip(": ") if d else str(k) for k, d in zip(kind, desc)]
        frames.append(pd.DataFrame({"symbol": ca["symbol"], "ex_date": ca["ex_date"], "text": text}))
    if adjustments is not None and not adjustments.empty:
        adj = adjustments[(adjustments["kind"] != "unexplained_gap") & (adjustments["confidence"] != OPEN_CONFIDENCE)]
        if not adj.empty:
            desc = adj["description"].astype("string").fillna("")
            text = [f"{k} ({s}): {d}".rstrip(": ") for k, s, d in zip(adj["kind"], adj["source"], desc)]
            frames.append(pd.DataFrame({"symbol": adj["symbol"], "ex_date": adj["ex_date"], "text": text}))
    if not frames:
        return pd.DataFrame(columns=["symbol", "ex_date", "text"])
    out = pd.concat(frames, ignore_index=True)
    out["symbol"] = out["symbol"].astype(str).str.upper()
    out["ex_date"] = pd.to_datetime(out["ex_date"], errors="coerce")
    return out.dropna(subset=["ex_date"])


def build_report(prices: pd.DataFrame, adjustments: pd.DataFrame, corporate_actions: pd.DataFrame | None,
                 window_days: int = 30) -> pd.DataFrame:
    if adjustments is None or adjustments.empty:
        return pd.DataFrame(columns=REPORT_COLUMNS)
    open_rows = adjustments[adjustments["confidence"] == OPEN_CONFIDENCE].copy()
    if open_rows.empty:
        return pd.DataFrame(columns=REPORT_COLUMNS)
    open_rows["ex_date"] = pd.to_datetime(open_rows["ex_date"], errors="coerce")
    px = prices[["symbol", "trade_date", "close_price"]].copy()
    px["trade_date"] = pd.to_datetime(px["trade_date"], errors="coerce")
    by_symbol = {s: g.sort_values("trade_date") for s, g in px.groupby("symbol", sort=False)}
    actions = _action_texts(adjustments, corporate_actions)
    actions_by_symbol = {s: g for s, g in actions.groupby("symbol", sort=False)}
    records = []
    for _, r in open_rows.sort_values(["symbol", "ex_date"]).iterrows():
        sym, ex = str(r["symbol"]).upper(), r["ex_date"]
        rows = by_symbol.get(sym, px.iloc[0:0])
        before = rows[rows["trade_date"] < ex].tail(1)
        on = rows[rows["trade_date"] == ex].head(1)
        near_text, near_date, days_off = "", pd.NaT, None
        cand = actions_by_symbol.get(sym)
        if cand is not None and pd.notna(ex):
            delta = (cand["ex_date"] - ex).dt.days
            cand = cand.assign(_d=delta, _abs=delta.abs())
            cand = cand[cand["_abs"] <= window_days].sort_values(["_abs", "ex_date"])
            if not cand.empty:
                best = cand.iloc[0]
                near_text, near_date, days_off = str(best["text"]), best["ex_date"], int(best["_d"])
        records.append({
            "symbol": sym,
            "ex_date": ex,
            "kind": r["kind"],
            "ratio": float(r["factor"]) if pd.notna(r["factor"]) else None,
            "prev_date": before["trade_date"].iloc[0] if not before.empty else pd.NaT,
            "prev_close": float(before["close_price"].iloc[0]) if not before.empty else None,
            "close": float(on["close_price"].iloc[0]) if not on.empty else None,
            "nearest_action_date": near_date,
            "action_days_off": days_off,
            "nearest_action": near_text,
        })
    return pd.DataFrame(records, columns=REPORT_COLUMNS)


def _q(text: str) -> str:
    return '"' + str(text).replace("\\", "/").replace('"', "'") + '"'


def yaml_stub(report: pd.DataFrame) -> str:
    """Commented-out override lines, three alternatives per gap. Nothing is a recommendation:
    the analyst checks the gap and uncomments at most one line."""
    lines = [
        "# --- adjustments_override.yaml stub (all commented out; uncomment ONE line per gap after review) ---",
        "# factor: pre-ex price multiplier (e.g. 0.5 for a 1:1 bonus / 2-for-1 split); verify before using.",
    ]
    for _, r in report.iterrows():
        day = pd.Timestamp(r["ex_date"]).date().isoformat()
        ratio = f"{r['ratio']:.4f}" if r["ratio"] is not None and pd.notna(r["ratio"]) else "?"
        ctx = f"gap {ratio}"
        if r["nearest_action"]:
            ctx += f"; near {r['nearest_action']} ({int(r['action_days_off']):+d}d)"
        lines.append(f"# {r['symbol']} {day}: {ctx}")
        lines.append(f"# - {{symbol: {r['symbol']}, ex_date: {day}, factor: {ratio}, note: {_q('TODO verify: ' + ctx)}}}")
        lines.append(f"# - {{symbol: {r['symbol']}, ex_date: {day}, kind: ignore, note: {_q('reviewed: genuine move; ' + ctx)}}}")
        lines.append(f"# - {{symbol: {r['symbol']}, ex_date: {day}, kind: demerger, note: {_q('demerger; ' + ctx)}}}")
    return "\n".join(lines)


def _fmt(v, digits=2) -> str:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return "-"
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def _recompute(db_path: Path, root: Path, prices: pd.DataFrame) -> pd.DataFrame:
    from price_adjustment import actions_from_corporate_actions_table, adjust_prices, drop_stale_adjustment_columns

    corp = _read(db_path, "corporate_actions")
    extra = None
    if not corp.empty:
        try:
            extra = actions_from_corporate_actions_table(corp)
        except Exception as exc:  # noqa: BLE001 - report continues without them
            print(f"Warning: corporate_actions unusable ({exc}); ignoring them.")
    raw = drop_stale_adjustment_columns(prices)
    # cache_dir=None: strictly read-only (no parse cache under Input/archive).
    _, adjustments = adjust_prices(raw, root, extra_actions=extra, cache_dir=None)
    return adjustments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(DB_PATH), help="DuckDB file (opened read-only).")
    parser.add_argument("--root", default=str(ROOT_DIR), help="Project root holding Input/ (PR zips, mcap, overrides).")
    parser.add_argument("--from-db", action="store_true", help="Use the stored price_adjustments table instead of recomputing.")
    parser.add_argument("--window", type=int, default=30, help="Days either side to search for corporate-action text (default 30).")
    args = parser.parse_args(argv)

    db_path, root = Path(args.db), Path(args.root)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 1
    prices = _read(db_path, "prices_daily")
    if prices.empty:
        print("prices_daily is empty or missing.")
        return 1
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    if args.from_db:
        adjustments = _read(db_path, "price_adjustments")
        source = "stored price_adjustments table"
    else:
        adjustments = _recompute(db_path, root, prices)
        source = f"adjust_prices recomputed against {root}"
    corp = _read(db_path, "corporate_actions")
    report = build_report(prices, adjustments, corp, window_days=args.window)

    print("=== Open price gaps needing review (READ-ONLY; nothing is written) ===")
    print(f"DB: {db_path}\nSource: {source}\nOpen rows: {len(report)}\n")
    if report.empty:
        print("No unconfirmed gaps. Nothing to review.")
        return 0
    table = report.assign(**{c: report[c].map(_fmt) for c in ("ex_date", "prev_date", "nearest_action_date")})
    table["ratio"] = report["ratio"].map(lambda v: _fmt(v, 4))
    table["prev_close"] = report["prev_close"].map(_fmt)
    table["close"] = report["close"].map(_fmt)
    table["action_days_off"] = report["action_days_off"].map(lambda v: "-" if v is None or pd.isna(v) else f"{int(v):+d}")
    table["nearest_action"] = report["nearest_action"].map(lambda s: (s[:70] + "...") if len(s) > 73 else s)
    print(table.to_string(index=False))
    print()
    print(yaml_stub(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
