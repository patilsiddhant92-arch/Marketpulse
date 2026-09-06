"""Trade Journal & Performance Analytics Engine for MarketPulse."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from nicegui import ui


def calculate_trade_metrics(df: pd.DataFrame) -> dict[str, Any]:
    """Calculate institutional performance stats from closed journal trades."""
    if df.empty:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "wins": 0,
            "losses": 0,
            "profit_factor": 0.0,
            "total_pnl_inr": 0.0,
            "avg_r": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "expectancy_r": 0.0,
            "best_trade_inr": 0.0,
            "worst_trade_inr": 0.0,
        }

    closed = df[df["status"].astype(str).str.lower().isin(["closed", "sold"]) | df["exit_price"].notna()].copy()
    if closed.empty:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "wins": 0,
            "losses": 0,
            "profit_factor": 0.0,
            "total_pnl_inr": 0.0,
            "avg_r": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "expectancy_r": 0.0,
            "best_trade_inr": 0.0,
            "worst_trade_inr": 0.0,
        }

    closed["entry_price"] = pd.to_numeric(closed["entry_price"], errors="coerce").fillna(0)
    closed["exit_price"] = pd.to_numeric(closed["exit_price"], errors="coerce").fillna(0)
    closed["quantity"] = pd.to_numeric(closed["quantity"], errors="coerce").fillna(0)
    closed["stop_loss"] = pd.to_numeric(closed["stop_loss"], errors="coerce").fillna(0)

    # Realized PnL
    closed["pnl_inr"] = (closed["exit_price"] - closed["entry_price"]) * closed["quantity"]
    closed["pnl_pct"] = (closed["exit_price"] - closed["entry_price"]) / closed["entry_price"].replace(0, pd.NA) * 100

    # R-multiple achieved
    risk_per_share = (closed["entry_price"] - closed["stop_loss"]).abs()
    closed["r_achieved"] = (closed["exit_price"] - closed["entry_price"]) / risk_per_share.replace(0, pd.NA)
    closed["r_achieved"] = closed["r_achieved"].fillna(closed["pnl_pct"] / 5.0)  # fallback 5% normalized R

    wins = closed[closed["pnl_inr"] > 0]
    losses = closed[closed["pnl_inr"] < 0]

    gross_profit = wins["pnl_inr"].sum()
    gross_loss = abs(losses["pnl_inr"].sum())
    total_trades = len(closed)
    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0.0
    loss_rate = 100.0 - win_rate

    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.9 if gross_profit > 0 else 0.0)

    avg_win_r = float(wins["r_achieved"].mean()) if not wins.empty else 0.0
    avg_loss_r = abs(float(losses["r_achieved"].mean())) if not losses.empty else 0.0
    expectancy_r = ((win_rate / 100.0) * avg_win_r) - ((loss_rate / 100.0) * avg_loss_r)

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "wins": len(wins),
        "losses": len(losses),
        "profit_factor": round(profit_factor, 2),
        "total_pnl_inr": round(float(closed["pnl_inr"].sum()), 0),
        "avg_r": round(float(closed["r_achieved"].mean()), 2) if not closed.empty else 0.0,
        "avg_win_r": round(avg_win_r, 2),
        "avg_loss_r": round(avg_loss_r, 2),
        "expectancy_r": round(expectancy_r, 2),
        "best_trade_inr": round(float(closed["pnl_inr"].max()), 0) if not closed.empty else 0.0,
        "worst_trade_inr": round(float(closed["pnl_inr"].min()), 0) if not closed.empty else 0.0,
    }


def query_journal_records(user_db: Path) -> pd.DataFrame:
    """Read full trade journal table."""
    try:
        with duckdb.connect(str(user_db), read_only=True) as db:
            df = db.execute(
                """
                SELECT id, trade_date, symbol, trade_type, setup_type,
                       entry_price, quantity, stop_loss, target,
                       position_size, risk_amount, r_multiple_target,
                       status, exit_date, exit_price, exit_reason, mistake_tag, notes
                FROM trade_journal
                ORDER BY coalesce(exit_date, trade_date) DESC
                """
            ).fetchdf()
            return df
    except Exception:
        return pd.DataFrame()


def log_trade_entry(
    user_db: Path,
    *,
    symbol: str,
    entry_price: float,
    quantity: float,
    stop_loss: float = 0.0,
    target: float = 0.0,
    setup_type: str = "VCP",
    exit_price: float | None = None,
    exit_date: str | None = None,
    mistake_tag: str | None = None,
    notes: str = "",
) -> bool:
    """Insert or log a trade into trade_journal."""
    try:
        pos_size = entry_price * quantity
        risk_amt = abs(entry_price - stop_loss) * quantity if stop_loss else 0.0
        risk_pct = abs(entry_price - stop_loss) / entry_price * 100 if (entry_price and stop_loss) else 0.0
        r_tgt = (abs(target - entry_price) / abs(entry_price - stop_loss)) if (target and stop_loss and entry_price != stop_loss) else 0.0
        status = "Closed" if exit_price is not None else "Open"
        row_id = int(pd.Timestamp.now().value // 1_000_000)

        with duckdb.connect(str(user_db)) as db:
            db.execute(
                """
                INSERT INTO trade_journal (
                    id, created_at, updated_at, trade_date, symbol, trade_type, setup_type,
                    entry_price, quantity, stop_loss, target, position_size, risk_amount,
                    risk_pct, reward_pct, r_multiple_target, status, exit_date, exit_price,
                    exit_reason, notes, mistake_tag
                )
                VALUES (
                    ?, now(), now(), current_date, ?, 'Buy', ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, 0, ?, ?, ?, ?,
                    'Target or Stop', ?, ?
                )
                """,
                [
                    row_id, symbol.upper(), setup_type,
                    entry_price, quantity, stop_loss, target, pos_size, risk_amt,
                    risk_pct, r_tgt, status, exit_date, exit_price, notes, mistake_tag,
                ],
            )
        return True
    except Exception:
        return False
