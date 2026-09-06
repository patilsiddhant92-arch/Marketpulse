from __future__ import annotations

import App.ui.table as table_module


def test_named_specs_keep_text_left_numeric_right_and_rationale_wrapped() -> None:
    spec_builder = getattr(table_module, "column_specs_for", None)
    assert callable(spec_builder), "column_specs_for must be the shared table contract entry point"
    specs = {item.key: item for item in spec_builder(["symbol", "industry", "day_pct", "why_now"])}
    assert specs["symbol"].width_px == 112
    assert specs["symbol"].align == "left"
    assert specs["industry"].width_px == 176
    assert specs["industry"].wrap is True
    assert specs["day_pct"].align == "right"
    assert specs["why_now"].responsive_priority == 0


def test_unknown_columns_get_a_stable_fallback_contract() -> None:
    spec_builder = getattr(table_module, "column_specs_for", None)
    assert callable(spec_builder), "column_specs_for must be the shared table contract entry point"
    spec = spec_builder(["new_metric"])[0]
    assert spec.width_px == 92
    assert spec.align == "left"
    assert spec.wrap is False
