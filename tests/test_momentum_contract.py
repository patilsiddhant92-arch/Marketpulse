from pathlib import Path


def test_momentum_summary_respects_user_market_cap_filter_and_labels_volume_inputs():
    source = Path("App/app.py").read_text(encoding="utf-8")

    assert "tradable = tradable[pd.to_numeric(tradable[\"market_cap_cr\"], errors=\"coerce\").fillna(0) >= float(min_mcap.value or 0)]" in source
    assert 'ui.number("Day volume"' in source
    assert 'ui.number("20D avg volume"' in source
