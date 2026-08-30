"""Fixed-width table specifications for the desktop EOD desk."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    label: str
    width_px: int
    align: str = "left"
    group: str = ""


SWING_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("symbol", "SYMBOL", 88, group="Identity"),
    ColumnSpec("state", "STATE", 72, group="Setup"),
    ColumnSpec("total_score", "SCORE", 48, "right", "Setup"),
    ColumnSpec("sector", "SECTOR", 112, group="Identity"),
    ColumnSpec("trigger_price", "TRIGGER", 72, "right", "Action"),
    ColumnSpec("invalidation_price", "INVALID", 72, "right", "Risk"),
    ColumnSpec("distance_to_trigger_pct", "DIST", 56, "right", "Risk"),
    ColumnSpec("reward_to_risk", "R:R", 48, "right", "Risk"),
    ColumnSpec("market_cap_cr", "MCAP", 64, "right", "Identity"),
    ColumnSpec("event_risk", "EVENT", 64, group="Action"),
    ColumnSpec("actions", "360 / TV", 72, "center", "Action"),
)


SCREENER_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("symbol", "SYMBOL", 88, group="Identity"),
    ColumnSpec("sector", "SECTOR", 112, group="Identity"),
    ColumnSpec("market_cap_cr", "MCAP", 64, "right", "Identity"),
    ColumnSpec("setup_class", "STATE", 64, group="Setup"),
    ColumnSpec("rs_percentile", "RS", 44, "right", "Setup"),
    ColumnSpec("rs_vs_nifty_63d", "VS NIFTY 63D", 64, "right", "Setup"),
    ColumnSpec("distance_below_52w", "52W %", 56, "right", "Setup"),
    ColumnSpec("rvol", "RVOL", 48, "right", "Setup"),
    ColumnSpec("quality_score", "FUNDA", 48, "right", "Quality"),
    ColumnSpec("roe", "ROE", 48, "right", "Quality"),
    ColumnSpec("revenue_cagr_3y", "REV 3Y", 52, "right", "Quality"),
    ColumnSpec("debt_to_equity", "D/E", 44, "right", "Quality"),
    ColumnSpec("promoter_pledge_pct", "PLEDGE", 48, "right", "Quality"),
    ColumnSpec("delivery_delta", "DELIV Δ", 52, "right", "Flow"),
    ColumnSpec("clientele", "CLIENTELE", 80, group="Flow"),
    ColumnSpec("deal_net_10s_cr", "NET 10S", 56, "right", "Flow"),
    ColumnSpec("actions", "360 / TV", 72, "center", "Action"),
)


def fixed_table_css() -> str:
    """Return the active table CSS contract; details stay in the drawer."""
    return """
    .mp-table-shell .q-table {
      table-layout: fixed !important;
      width: 1040px !important;
      min-width: 768px !important;
    }
    .mp-table-shell .q-table th,
    .mp-table-shell .q-table td {
      height: 28px;
      padding: 2px 6px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .mp-table-shell .q-table thead tr {
      position: sticky;
      top: 0;
      z-index: 2;
    }
    """


__all__ = ["ColumnSpec", "SCREENER_COLUMNS", "SWING_COLUMNS", "fixed_table_css"]
