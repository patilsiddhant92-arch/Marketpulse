"""Optional `kind` in adjustments_override.yaml: 'ignore' marks a gap reviewed, 'demerger' records a
non-adjusting demerger; no kind keeps the existing factor/suppress behaviour."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from price_adjustment import load_overrides, reconcile, summarize_adjustments


def _gaps(*rows):
    return pd.DataFrame({"symbol": [r[0] for r in rows], "ex_date": pd.to_datetime([r[1] for r in rows]),
                         "gap_ratio": [r[2] for r in rows]})


def _load(tmp_path, text):
    y = tmp_path / "adjustments_override.yaml"
    y.write_text(text, encoding="utf-8")
    return load_overrides(y)


def test_kind_column_loaded_and_defaults_to_none(tmp_path):
    ov = _load(tmp_path, "- {symbol: aaa, ex_date: 2026-01-05, factor: 0.5, note: x}\n"
                         "- {symbol: bbb, ex_date: 2026-01-06, kind: Ignore, note: reviewed}\n")
    assert pd.isna(ov["kind"].iloc[0]) and ov["kind"].iloc[1] == "ignore"
    assert list(ov["symbol"]) == ["AAA", "BBB"]


def test_unknown_kind_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="kind"):
        _load(tmp_path, "- {symbol: A, ex_date: 2026-01-05, kind: bonus}\n")


def test_ignore_marks_gap_reviewed(tmp_path):
    ov = _load(tmp_path, "- {symbol: HEG, ex_date: 2026-09-02, kind: ignore, note: genuine crash}\n")
    out = reconcile(pd.DataFrame(), pd.DataFrame(), _gaps(("HEG", "2026-09-01", 0.4), ("ZZZ", "2026-03-03", 0.5)), ov)
    heg = out[out["symbol"] == "HEG"].iloc[0]
    assert heg["kind"] == "unexplained_gap" and heg["confidence"] == "reviewed" and not heg["applied"]
    assert "genuine crash" in heg["description"]
    # only ZZZ is still an open (unreviewed) gap
    assert "1 unconfirmed gaps" in summarize_adjustments(out)


def test_ignore_without_matching_gap_adds_nothing(tmp_path):
    ov = _load(tmp_path, "- {symbol: HEG, ex_date: 2026-09-02, kind: ignore}\n")
    out = reconcile(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), ov)
    assert out.empty


def test_ignore_never_touches_an_applied_action(tmp_path):
    mcap = pd.DataFrame([{"symbol": "KIRLPNU", "ex_date": pd.Timestamp("2026-08-18"), "kind": "split", "factor": 0.5,
                          "description": "split", "source": "mcap_fv"}])
    ov = _load(tmp_path, "- {symbol: KIRLPNU, ex_date: 2026-08-18, kind: ignore}\n")
    out = reconcile(pd.DataFrame(), mcap, pd.DataFrame(), ov).iloc[0]
    assert out["applied"] and out["kind"] == "split"


def test_demerger_recorded_not_applied(tmp_path):
    ov = _load(tmp_path, "- {symbol: SIEMENS, ex_date: 2026-04-07, kind: demerger, note: Siemens Energy demerger}\n")
    out = reconcile(pd.DataFrame(), pd.DataFrame(), _gaps(("SIEMENS", "2026-04-07", 0.55)), ov).iloc[0]
    assert out["kind"] == "demerger" and not out["applied"] and out["confidence"] == "not_adjusting"
    assert math.isnan(out["factor"])
    assert "Siemens Energy" in out["description"]
    s = summarize_adjustments(pd.DataFrame([out]))
    assert "0 applied" in s and "0 unconfirmed gaps" in s and "1 non-adjusting" in s


def test_demerger_without_gap_adds_a_row(tmp_path):
    ov = _load(tmp_path, "- {symbol: ITC, ex_date: 2026-01-06, kind: demerger, note: hotels}\n")
    out = reconcile(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), ov)
    assert len(out) == 1 and out.iloc[0]["kind"] == "demerger" and not out.iloc[0]["applied"]


def test_default_kind_keeps_factor_behaviour(tmp_path):
    ov = _load(tmp_path, "- {symbol: HEG, ex_date: 2026-09-01, factor: 0.2, note: 1:5 split missing}\n")
    out = reconcile(pd.DataFrame(), pd.DataFrame(), _gaps(("HEG", "2026-09-01", 0.2)), ov).iloc[0]
    assert out["applied"] and out["confidence"] == "override" and math.isclose(out["factor"], 0.2)
