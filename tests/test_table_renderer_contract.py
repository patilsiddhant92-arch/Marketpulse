from __future__ import annotations

import App.ui.table as table_module


def test_table_column_definition_uses_named_width_alignment_and_wrap() -> None:
    definition_builder = getattr(table_module, "table_column_definition", None)
    spec_builder = getattr(table_module, "column_spec_for", None)
    assert callable(definition_builder), "table_column_definition must be the renderer contract"
    assert callable(spec_builder), "column_spec_for must be the renderer contract"

    definition = definition_builder(spec_builder("industry"))

    assert definition["align"] == "left"
    assert "width:176px" in definition["style"]
    assert "white-space:normal" in definition["style"]
    assert "mp-wrap-col" in definition["classes"]


def test_table_column_definition_keeps_numeric_fields_right_aligned() -> None:
    definition_builder = getattr(table_module, "table_column_definition", None)
    spec_builder = getattr(table_module, "column_spec_for", None)
    assert callable(definition_builder), "table_column_definition must be the renderer contract"
    assert callable(spec_builder), "column_spec_for must be the renderer contract"

    definition = definition_builder(spec_builder("day_pct"))

    assert definition["align"] == "right"
    assert "width:76px" in definition["style"]
    assert "white-space:nowrap" in definition["style"]
    assert "numeric" in definition["classes"]


def test_table_width_contract_is_the_sum_of_declared_column_widths() -> None:
    width_builder = getattr(table_module, "table_width_px", None)
    spec_builder = getattr(table_module, "column_specs_for", None)
    assert callable(width_builder), "table_width_px must preserve the declared table contract"
    assert callable(spec_builder), "column_specs_for must be the renderer contract"

    assert width_builder(spec_builder(["symbol", "industry", "day_pct"])) == 364
