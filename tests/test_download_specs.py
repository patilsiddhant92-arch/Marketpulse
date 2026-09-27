from __future__ import annotations

from datetime import datetime

from Scripts.download_nse_reports import (
    NSE_ARCHIVES,
    ReportSpec,
    _write_auxiliary_fallback,
    report_specs,
)
from index_history import parse_ind_close_all


def test_report_specs_includes_ind_close_all(tmp_path):
    day = datetime(2026, 9, 25)
    specs = report_specs(day, {})
    by_label = {spec.label: spec for spec in specs}

    assert "all indices" in by_label
    spec = by_label["all indices"]

    assert spec.output_name == "ind_close_all_25092026.csv"
    assert spec.candidates == (
        f"{NSE_ARCHIVES}/content/indices/ind_close_all_25092026.csv",
    )
    assert spec.required_columns == ("Index Name", "Closing Index Value")


def test_ind_close_all_fallback_parses_to_zero_rows(tmp_path, capsys):
    spec = ReportSpec(
        "all indices",
        "ind_close_all_25092026.csv",
        (),
        ("Index Name", "Closing Index Value"),
    )
    path = tmp_path / spec.output_name
    _write_auxiliary_fallback(path, spec)

    assert path.exists()
    text = path.read_text(encoding="utf-8-sig")
    assert text.strip() == (
        "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,"
        "Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),"
        "P/E,P/B,Div Yield"
    )

    df = parse_ind_close_all(path)
    captured = capsys.readouterr()
    assert df.empty
    assert "0 rows" in captured.out
