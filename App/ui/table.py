"""Fixed-width table specifications for the desktop EOD desk."""

from __future__ import annotations

from dataclasses import dataclass, replace

try:
    from App.ui.columns import (
        GLOBAL_COLUMNS,
        ColumnContract,
        get_column_contract,
        get_column_label,
        get_quasar_column_def,
        table_min_width_px,
    )
except ModuleNotFoundError:
    from ui.columns import (  # type: ignore
        GLOBAL_COLUMNS,
        ColumnContract,
        get_column_contract,
        get_column_label,
        get_quasar_column_def,
        table_min_width_px,
    )


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    label: str
    width_px: int
    align: str = "left"
    group: str = ""
    wrap: bool = False
    responsive_priority: int = 1


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


# Shared contracts for the dynamic DataFrame tables. The legacy swing and
# screener tuples above remain stable because other tests and pages use their
# approved totals; these named contracts govern the live renderer.
_COLUMN_CONTRACTS: dict[str, ColumnSpec] = {
    "symbol": ColumnSpec("symbol", "SYMBOL", 112, group="Identity"),
    "symbols": ColumnSpec("symbols", "SYMBOLS", 260, group="Identity", wrap=True, responsive_priority=0),
    "symbol_list": ColumnSpec("symbol_list", "SYMBOL LIST", 260, group="Identity", wrap=True, responsive_priority=0),
    "symbol_preview": ColumnSpec("symbol_preview", "SYMBOL PREVIEW", 260, group="Identity", wrap=True, responsive_priority=0),
    "state": ColumnSpec("state", "STATE", 96, group="Setup"),
    "candidate_state": ColumnSpec("candidate_state", "STATE", 96, group="Setup"),
    "setup_class": ColumnSpec("setup_class", "STATE", 96, group="Setup"),
    "rotation_state": ColumnSpec("rotation_state", "ROTATION", 112, group="Setup"),
    "vcp_state": ColumnSpec("vcp_state", "VCP", 104, group="Setup"),
    "sector_state": ColumnSpec("sector_state", "SECTOR STATE", 120, group="Setup"),
    "industry_state": ColumnSpec("industry_state", "INDUSTRY STATE", 128, group="Setup"),
    "setup": ColumnSpec("setup", "SETUP", 120, group="Setup"),
    "sector": ColumnSpec("sector", "SECTOR", 176, group="Identity", wrap=True),
    "broad_sector": ColumnSpec("broad_sector", "BROAD SECTOR", 176, group="Identity", wrap=True),
    "industry": ColumnSpec("industry", "INDUSTRY", 176, group="Identity", wrap=True),
    "broad_industry": ColumnSpec("broad_industry", "BROAD INDUSTRY", 176, group="Identity", wrap=True),
    "group_name": ColumnSpec("group_name", "GROUP", 176, group="Identity", wrap=True),
    "change_type": ColumnSpec("change_type", "CHANGE", 128, group="Context", wrap=True),
    "why_now": ColumnSpec("why_now", "WHY NOW", 200, group="Context", wrap=True, responsive_priority=0),
    "latest_change": ColumnSpec("latest_change", "LATEST CHANGE", 200, group="Context", wrap=True, responsive_priority=0),
    "risk_summary": ColumnSpec("risk_summary", "RISK SUMMARY", 200, group="Risk", wrap=True, responsive_priority=0),
    "warning_reasons": ColumnSpec("warning_reasons", "WARNINGS", 200, group="Risk", wrap=True, responsive_priority=0),
    "blocking_reasons": ColumnSpec("blocking_reasons", "BLOCKERS", 200, group="Risk", wrap=True, responsive_priority=0),
    "notes": ColumnSpec("notes", "NOTES", 200, group="Context", wrap=True, responsive_priority=0),
    "tags": ColumnSpec("tags", "TAGS", 160, group="Context", wrap=True, responsive_priority=0),
    "status": ColumnSpec("status", "STATUS", 96, group="Context"),
    "side": ColumnSpec("side", "SIDE", 80, group="Flow"),
    "band": ColumnSpec("band", "BAND", 72, group="Risk"),
    "band_fmt": ColumnSpec("band_fmt", "BAND", 72, "center", "Risk"),
    "ticket_flow": ColumnSpec("ticket_flow", "TICKET 🏛️", 88, "right", "Flow"),
    "away_10ema": ColumnSpec("away_10ema", "10 EMA %", 76, "right", "Setup"),
    "trigger_price": ColumnSpec("trigger_price", "TRIGGER", 88, "right", "Action"),
    "invalidation_price": ColumnSpec("invalidation_price", "INVALID", 88, "right", "Risk"),
    "first_resistance": ColumnSpec("first_resistance", "RESISTANCE", 96, "right", "Risk"),
    "close_price": ColumnSpec("close_price", "CLOSE", 88, "right", "Market"),
    "distance_to_trigger_pct": ColumnSpec("distance_to_trigger_pct", "DIST", 76, "right", "Risk"),
    "distance_below_52w": ColumnSpec("distance_below_52w", "52W %", 76, "right", "Setup"),
    "away_52w_high_pct": ColumnSpec("away_52w_high_pct", "52W %", 76, "right", "Setup"),
    "reward_to_risk": ColumnSpec("reward_to_risk", "R:R", 64, "right", "Risk"),
    "initial_risk_pct": ColumnSpec("initial_risk_pct", "RISK %", 76, "right", "Risk"),
    "market_cap_cr": ColumnSpec("market_cap_cr", "MCAP", 96, "right", "Identity"),
    "total_score": ColumnSpec("total_score", "SCORE", 72, "right", "Setup"),
    "quality_score": ColumnSpec("quality_score", "FUNDA", 72, "right", "Quality"),
    "rs_percentile": ColumnSpec("rs_percentile", "RS", 64, "right", "Setup"),
    "rs_vs_nifty_63d": ColumnSpec("rs_vs_nifty_63d", "VS NIFTY 63D", 96, "right", "Setup"),
    "rs": ColumnSpec("rs", "RS", 64, "right", "Setup"),
    "rs_5d_trail": ColumnSpec("rs_5d_trail", "RS 5D TRAIL", 165, "center", "Setup"),
    "rs_rank": ColumnSpec("rs_rank", "RS RANK", 76, "right", "Setup"),
    "rank": ColumnSpec("rank", "RANK", 60, "right", "Setup"),
    "rank_change_5d": ColumnSpec("rank_change_5d", "RANK Δ", 76, "right", "Setup"),
    "day_pct": ColumnSpec("day_pct", "DAY %", 76, "right", "Market"),
    "week_pct": ColumnSpec("week_pct", "WEEK %", 76, "right", "Market"),
    "month_pct": ColumnSpec("month_pct", "MONTH %", 84, "right", "Market"),
    "return_1m_pct": ColumnSpec("return_1m_pct", "1M %", 76, "right", "Market"),
    "return_3m_pct": ColumnSpec("return_3m_pct", "3M %", 76, "right", "Market"),
    "above_50": ColumnSpec("above_50", "ABOVE 50", 84, "right", "Breadth"),
    "above_50ema_pct": ColumnSpec("above_50ema_pct", "ABOVE 50 EMA", 104, "right", "Breadth"),
    "above_200ema_pct": ColumnSpec("above_200ema_pct", "ABOVE 200 EMA", 112, "right", "Breadth"),
    "advance_pct": ColumnSpec("advance_pct", "ADVANCE %", 96, "right", "Breadth"),
    "near_52w_highs": ColumnSpec("near_52w_highs", "NEAR 52W", 88, "right", "Breadth"),
    "new_20d_highs": ColumnSpec("new_20d_highs", "NEW 20D", 84, "right", "Breadth"),
    "rvol": ColumnSpec("rvol", "RVOL", 72, "right", "Flow"),
    "vs_20d": ColumnSpec("vs_20d", "VS 20D", 80, "right", "Flow"),
    "vol_shock": ColumnSpec("vol_shock", "VOL SHOCK", 92, "right", "Flow"),
    "delivery_pct": ColumnSpec("delivery_pct", "DELIVERY %", 96, "right", "Flow"),
    "delivery_delta": ColumnSpec("delivery_delta", "DELIVERY Δ", 96, "right", "Flow"),
    "delivery_qty": ColumnSpec("delivery_qty", "DELIVERY QTY", 112, "right", "Flow"),
    "t_o_today": ColumnSpec("t_o_today", "T/O TODAY", 104, "right", "Flow"),
    "t_o_1w": ColumnSpec("t_o_1w", "T/O 1W", 92, "right", "Flow"),
    "t_o_1m": ColumnSpec("t_o_1m", "T/O 1M", 92, "right", "Flow"),
    "turnover_cr": ColumnSpec("turnover_cr", "TURNOVER CR", 104, "right", "Flow"),
    "buy_deal_cr": ColumnSpec("buy_deal_cr", "BUY CR", 88, "right", "Flow"),
    "sell_deal_cr": ColumnSpec("sell_deal_cr", "SELL CR", 88, "right", "Flow"),
    "net_deal_cr": ColumnSpec("net_deal_cr", "NET CR", 88, "right", "Flow"),
    "deal_net_10s_cr": ColumnSpec("deal_net_10s_cr", "NET 10S", 92, "right", "Flow"),
    "clientele": ColumnSpec("clientele", "CLIENTELE", 120, group="Flow", wrap=True),
    "clients": ColumnSpec("clients", "CLIENTS", 80, "right", "Flow"),
    "deal_when": ColumnSpec("deal_when", "DEAL WHEN", 200, group="Flow", wrap=True, responsive_priority=0),
    "event_risk": ColumnSpec("event_risk", "EVENT", 96, group="Action", wrap=True),
    "event_date": ColumnSpec("event_date", "EVENT DATE", 104, group="Action"),
    "actions": ColumnSpec("actions", "360 / TV", 96, "center", "Action"),
    "copy_symbols": ColumnSpec("copy_symbols", "COPY", 64, "center", "Action"),
    "client_name": ColumnSpec("client_name", "CLIENT", 200, group="Flow", wrap=True, responsive_priority=0),
    "latest_deal_date": ColumnSpec("latest_deal_date", "LATEST DEAL", 112, group="Flow"),
    "buy_value_cr": ColumnSpec("buy_value_cr", "BUY CR", 88, "right", "Flow"),
    "sell_value_cr": ColumnSpec("sell_value_cr", "SELL CR", 88, "right", "Flow"),
    "net_value_cr": ColumnSpec("net_value_cr", "NET CR", 88, "right", "Flow"),
    "active_days": ColumnSpec("active_days", "ACTIVE DAYS", 88, "right", "Flow"),
    "roe": ColumnSpec("roe", "ROE", 72, "right", "Quality"),
    "revenue_cagr_3y": ColumnSpec("revenue_cagr_3y", "REV 3Y", 84, "right", "Quality"),
    "debt_to_equity": ColumnSpec("debt_to_equity", "D/E", 64, "right", "Quality"),
    "promoter_pledge_pct": ColumnSpec("promoter_pledge_pct", "PLEDGE", 88, "right", "Quality"),
}

_COMPACT_WIDTHS: dict[str, int] = {
    "client_name": 240,
    "latest_deal_date": 112,
    "buy_value_cr": 88,
    "sell_value_cr": 88,
    "net_value_cr": 88,
    "active_days": 88,
    "copy_symbols": 54,
    "symbol_preview": 260,
}


def _fallback_label(key: str) -> str:
    return str(key).replace("_", " ").upper()


def column_spec_for(key: str, *, compact: bool = False) -> ColumnSpec:
    """Return the stable visual contract for one DataFrame column."""
    spec = _COLUMN_CONTRACTS.get(str(key))
    if spec is None:
        return ColumnSpec(str(key), _fallback_label(str(key)), 92)
    if compact and spec.key in _COMPACT_WIDTHS:
        return replace(spec, width_px=_COMPACT_WIDTHS[spec.key])
    return spec


def column_specs_for(keys: list[str] | tuple[str, ...], *, compact: bool = False) -> tuple[ColumnSpec, ...]:
    """Return ordered named contracts for a renderer's visible columns."""
    return tuple(column_spec_for(key, compact=compact) for key in keys)


def table_column_definition(spec: ColumnSpec) -> dict[str, str]:
    """Translate a named contract into NiceGUI/Quasar column style fields."""
    if spec.align == "right":
        classes = "numeric"
    elif spec.align == "center":
        classes = "action-col"
    elif spec.key == "symbol":
        classes = "symbol-col"
    elif spec.key in {"symbols", "symbol_list", "symbol_preview"}:
        classes = "symbols-col"
    else:
        classes = "text-col"

    width_decl = f"width:{spec.width_px}px;min-width:{spec.width_px}px;"
    if spec.wrap:
        style = f"{width_decl}max-width:{spec.width_px + 80}px;white-space:normal;word-break:break-word;vertical-align:top;"
        header_style = f"{width_decl}white-space:normal;line-height:1.2;"
        classes = f"{classes} mp-wrap-col"
    else:
        style = f"{width_decl}white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"
        header_style = f"{width_decl}white-space:normal;line-height:1.2;"
        if spec.key == "symbol":
            style = f"{width_decl}white-space:nowrap;overflow:hidden;"
    return {
        "align": spec.align,
        "style": style,
        "headerStyle": header_style,
        "classes": classes,
        "headerClasses": f"{classes} mp-th",
    }


def table_width_px(specs: list[ColumnSpec] | tuple[ColumnSpec, ...]) -> int:
    """Return the minimum scroll width required by an ordered table contract."""
    return sum(spec.width_px for spec in specs)


def fixed_table_css() -> str:
    """Return the active table CSS contract; details stay in the drawer."""
    return """
    .mp-table-shell .q-table {
      table-layout: fixed !important;
      width: 100% !important;
      min-width: 768px !important;
    }
    .mp-table-shell .q-table th,
    .mp-table-shell .q-table td {
      height: 36px;
      padding: 6px 10px;
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


SYMBOL_CELL_SLOT = """
<q-td :props="props" class="symbol-col">
  <div class="mp-symbol-cell">
    <button type="button" class="mp-symbol-star"
            @click.stop="$parent.$emit('quick_wl', props.row.symbol || props.value)"
            title="Quick add/remove from Watchlist (WL1)">★</button>
    <a class="mp-symbol"
       target="_blank" rel="noopener"
       :href="'https://www.tradingview.com/chart/?symbol=NSE:' + String(props.row.symbol || props.value).replace('-', '_')"
       @click.stop
       :title="'Open ' + (props.row.symbol || props.value) + ' on TradingView'">{{ props.value }}</a>
    <q-btn dense flat no-caps class="mp-symbol-open"
           @click.stop="$parent.$emit('stock360', props.row.symbol || props.value)"
           title="Open stock box">↗</q-btn>
    <span v-if="props.row.sector_badge" class="mp-mini-badge mp-sector-tag">{{ props.row.sector_badge }}</span>
    <span v-if="props.row.is_top_sector" class="mp-mini-badge mp-sector-badge">Lead</span>
    <span v-if="props.row.is_improving_sector" class="mp-mini-badge mp-improving-badge">Impr</span>
    <span v-if="props.row.is_top_industry" class="mp-mini-badge mp-industry-badge">Lead Ind</span>
    <span v-if="props.row.is_improving_industry" class="mp-mini-badge mp-improving-badge">Impr Ind</span>
    <span v-if="props.row.has_deal && props.row.has_deal !== 'No' && props.row.has_deal !== false" class="mp-mini-badge mp-deal-badge">Deal</span>
  </div>
</q-td>
"""


__all__ = [
    "ColumnSpec",
    "SCREENER_COLUMNS",
    "SWING_COLUMNS",
    "column_spec_for",
    "column_specs_for",
    "fixed_table_css",
    "table_column_definition",
    "table_width_px",
    "SYMBOL_CELL_SLOT",
    "ColumnContract",
    "GLOBAL_COLUMNS",
    "get_column_contract",
    "get_column_label",
    "get_quasar_column_def",
    "table_min_width_px",
]
