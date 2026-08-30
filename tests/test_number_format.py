from App.ui.number_format import classify_column, format_cell


def test_delivery_and_advance_are_levels_not_pnl():
    text, tone = format_cell("delivery_pct", 52.0)
    assert text == "52.0%"
    assert tone == ""
    text, tone = format_cell("advance_pct", 51.6)
    assert text == "51.6%"
    assert tone == ""


def test_fifty_two_week_distance_is_plain_signed_percent():
    text, tone = format_cell("away_52w_high_pct", -8.2)
    assert text == "-8.2%"
    assert tone == ""
    text, tone = format_cell("away_52w_high_pct", 2.0)
    assert text == "2.0%"
    assert tone == ""
    text, tone = format_cell("away_10ema_pct", 1.2)
    assert text == "1.2%"
    assert tone == ""


def test_turnover_is_money_and_never_colored():
    assert classify_column("t_o_today") == "money"
    assert classify_column("turnover_cr") == "money"
    text, tone = format_cell("t_o_today", 97548.3)
    assert "97,548.3" == text
    assert tone == ""
    text, tone = format_cell("turnover_cr", 120.0)
    assert text == "120.0"
    assert tone == ""


def test_signed_returns_keep_plus_minus_and_color():
    text, tone = format_cell("day_pct", 0.35)
    assert text == "+0.35%"
    assert tone == "mp-up"
    text, tone = format_cell("week_pct", -1.2)
    assert text == "-1.20%"
    assert tone == "mp-down"


def test_buy_sell_net_use_side_not_nan_parsing():
    text, tone = format_cell("buy_value_cr", 80)
    assert text == "80.0"
    assert tone == "mp-up"
    text, tone = format_cell("sell_value_cr", 12)
    assert tone == "mp-down"
    text, tone = format_cell("net_value_cr", -12.5)
    assert text.startswith("-")
    assert tone == "mp-down"
