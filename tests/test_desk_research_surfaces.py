from pathlib import Path


def test_deals_cluster_radar_is_open_and_side_defaults_both():
    src = Path("App/pages/research/deals.py").read_text(encoding="utf-8")
    assert "ui.expansion" not in src
    assert 'value="BOTH"' in src
    assert "mp-deals-split" in src
    assert "run_advanced()" in src


def test_table_formatter_does_not_paint_turnover_red_via_nan():
    src = Path("App/app.py").read_text(encoding="utf-8")
    assert "format_cell" in src
    # Old slot: Number("1,234.5") and Number("52.3%") are NaN, so everything went red.
    assert "Number(props.value || 0) >= 0 ? 'mp-pos' : 'mp-neg'" not in src


def test_desk_and_sectors_show_research_surfaces():
    desk = Path("App/pages/desk.py").read_text(encoding="utf-8")
    sectors = Path("App/pages/research/sector_board.py").read_text(encoding="utf-8")
    chart = Path("App/ui/vcp_chart.py").read_text(encoding="utf-8")
    assert "near_highs" in desk
    assert "delivery_thrust" in desk
    assert "return_heatmap" in desk
    assert "line_chart" in desk
    assert "grouped_line_chart" in desk
    assert "return_heatmap" in sectors
    assert "grouped_line_chart" in sectors
    assert "rs_rank" in sectors
    assert "RS vs Nifty" in chart
    assert '("Template", sma_template_page, "sma-template", False)' in Path("App/app.py").read_text(encoding="utf-8")


def test_global_column_labels_are_stable():
    from Scripts.config import FRIENDLY_COLUMNS

    assert FRIENDLY_COLUMNS["away_52w_high_pct"] == "52W %"
    assert FRIENDLY_COLUMNS["rs_percentile"] == "RS %"
    assert FRIENDLY_COLUMNS["t_o_today"] == "T/O Cr"
    assert FRIENDLY_COLUMNS["turnover_cr"] == "T/O Cr"
    assert FRIENDLY_COLUMNS["buy_value_cr"] == "Buy Cr"
    assert FRIENDLY_COLUMNS["buy_deal_cr"] == "Buy Cr"
    assert FRIENDLY_COLUMNS["cmp_vs_inst_entry_pct"] == "vs Entry %"
    assert FRIENDLY_COLUMNS["avg_volume_20d"] == "20D Avg Vol"
    assert FRIENDLY_COLUMNS["market_cap_cr"] == "MCap Cr"


def test_desk_does_not_show_index_values():
    desk = Path("App/pages/desk.py").read_text(encoding="utf-8")
    assert "Index tape" not in desk
    assert '"Nifty 50"' not in desk
    assert "Midcap 150" not in desk
    assert "India VIX" not in desk
