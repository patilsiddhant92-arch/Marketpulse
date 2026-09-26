from __future__ import annotations

import math

import pandas as pd

from price_adjustment import gap_candidates, load_overrides, reconcile


def _a(sym, d, kind, factor, source):
    return {"symbol": sym, "ex_date": pd.Timestamp(d), "kind": kind, "factor": factor, "description": kind, "source": source}


def test_gap_candidates():
    p = pd.DataFrame({"symbol": ["G"] * 3 + ["X"] * 2,
                      "trade_date": pd.to_datetime(["2026-08-19", "2026-08-20", "2026-08-21", "2026-08-20", "2026-08-21"]),
                      "close_price": [1363.3, 1439.4, 490.9, 100.0, 104.0]})
    g = gap_candidates(p)
    assert g["symbol"].tolist() == ["G"] and math.isclose(g["gap_ratio"].iloc[0], 490.9 / 1439.4)


def test_reconcile_confirms_and_merges_sources():
    bc = pd.DataFrame([_a("GOODLUCK", "2026-08-21", "bonus", 1 / 3, "bc"),
                       _a("SIYSIL", "2026-08-21", "pref_bonus", None, "bc")])
    mcap = pd.DataFrame([_a("GOODLUCK", "2026-08-21", "bonus", 1 / 3, "mcap_issue"),
                         _a("KIRLPNU", "2026-08-18", "split", 0.5, "mcap_fv")])
    gaps = pd.DataFrame({"symbol": ["GOODLUCK", "HEG"], "ex_date": pd.to_datetime(["2026-08-21", "2026-09-01"]),
                         "gap_ratio": [490.9 / 1439.4, 0.33]})
    out = reconcile(bc, mcap, gaps, pd.DataFrame()).set_index("symbol")
    g = out.loc["GOODLUCK"]
    assert g["applied"] and g["confidence"] == "confirmed" and g["source"] == "bc+mcap_issue" and math.isclose(g["factor"], 1 / 3)
    assert out.loc["KIRLPNU", "applied"] and out.loc["KIRLPNU", "source"] == "mcap_fv"
    assert not out.loc["SIYSIL", "applied"] and out.loc["SIYSIL", "confidence"] == "not_adjusting"
    assert out.loc["HEG", "kind"] == "unexplained_gap" and not out.loc["HEG", "applied"]


def test_overrides_suppress_and_add(tmp_path):
    y = tmp_path / "o.yaml"
    y.write_text("- {symbol: KIRLPNU, ex_date: 2026-08-18, factor: null, note: wrong}\n"
                 "- {symbol: NEWCO, ex_date: 2021-01-04, factor: 0.5, note: manual}\n")
    ov = load_overrides(y)
    mcap = pd.DataFrame([_a("KIRLPNU", "2026-08-18", "split", 0.5, "mcap_fv")])
    out = reconcile(pd.DataFrame(), mcap, pd.DataFrame(), ov).set_index("symbol")
    assert not out.loc["KIRLPNU", "applied"] and out.loc["KIRLPNU", "confidence"] == "suppressed"
    assert out.loc["NEWCO", "applied"] and out.loc["NEWCO", "source"] == "override"
    assert load_overrides(tmp_path / "missing.yaml").empty


def test_mcap_issue_bonus_conflicts_with_bc_rights():
    bc = pd.DataFrame([_a("MPEL", "2026-08-31", "rights", None, "bc")])
    bc.loc[0, "description"] = "RIGHTS 2:1 @ PRM RS 6/-"
    mcap = pd.DataFrame([_a("MPEL", "2026-08-31", "bonus", 1 / 3, "mcap_issue")])
    gaps = pd.DataFrame({"symbol": ["MPEL"], "ex_date": pd.to_datetime(["2026-08-31"]), "gap_ratio": [0.34]})
    out = reconcile(bc, mcap, gaps, pd.DataFrame())
    row = out[(out["symbol"] == "MPEL") & (out["source"] == "mcap_issue")].iloc[0]
    assert not row["applied"] and row["confidence"] == "rights_conflict"
    # The gap next to the conflicting rights issue is explained by it, not left dangling.
    assert not ((out["symbol"] == "MPEL") & (out["kind"] == "unexplained_gap")).any()


def test_mcap_issue_bonus_unconfirmed_without_evidence():
    mcap = pd.DataFrame([_a("ONDOOR", "2026-07-31", "bonus", 0.8, "mcap_issue")])
    out = reconcile(pd.DataFrame(), mcap, pd.DataFrame(), pd.DataFrame()).set_index("symbol")
    assert not out.loc["ONDOOR", "applied"] and out.loc["ONDOOR", "confidence"] == "unconfirmed"


def test_mcap_issue_bonus_confirmed_by_gap_without_bc():
    mcap = pd.DataFrame([_a("XYZ", "2026-07-31", "bonus", 0.5, "mcap_issue")])
    gaps = pd.DataFrame({"symbol": ["XYZ"], "ex_date": pd.to_datetime(["2026-07-31"]), "gap_ratio": [0.51]})
    out = reconcile(pd.DataFrame(), mcap, gaps, pd.DataFrame()).set_index("symbol")
    row = out.loc["XYZ"]
    assert row["applied"] and row["confidence"] == "confirmed" and row["source"] == "mcap_issue"


def test_incompatible_kinds_do_not_merge():
    # A bc split and an mcap_issue bonus landing on the same symbol/date/factor by coincidence
    # must NOT merge -- only kind-compatible pairs do (bonus<->mcap_issue, split/consolidation<->mcap_fv).
    bc = pd.DataFrame([_a("SPLITCO", "2026-07-10", "split", 0.5, "bc")])
    mcap = pd.DataFrame([_a("SPLITCO", "2026-07-10", "bonus", 0.5, "mcap_issue")])
    out = reconcile(bc, mcap, pd.DataFrame(), pd.DataFrame())
    assert not (out["source"] == "bc+mcap_issue").any()
    bc_row = out[out["source"] == "bc"].iloc[0]
    assert bc_row["applied"] and bc_row["confidence"] == "single_source"
    mcap_row = out[out["source"] == "mcap_issue"].iloc[0]
    assert not mcap_row["applied"] and mcap_row["confidence"] == "unconfirmed"


def test_override_replaces_event_dropped_by_duplicate_guard():
    # Two bc announcements of the same bonus two days apart collapse to one applied row at the
    # earlier date. An override keyed to the *dropped* date must not become a second applied row
    # -- it should replace the surviving row (nearest within window_days), leaving exactly one.
    bc = pd.DataFrame([_a("DUPCO", "2026-08-10", "bonus", 0.5, "bc"),
                       _a("DUPCO", "2026-08-12", "bonus", 0.5, "bc")])
    ov = pd.DataFrame([{"symbol": "DUPCO", "ex_date": pd.Timestamp("2026-08-12"), "factor": 0.4, "note": "correct date"}])
    out = reconcile(bc, pd.DataFrame(), pd.DataFrame(), ov)
    dupco = out[out["symbol"] == "DUPCO"]
    applied = dupco[dupco["applied"]]
    assert len(applied) == 1
    row = applied.iloc[0]
    assert row["ex_date"] == pd.Timestamp("2026-08-12") and math.isclose(row["factor"], 0.4)
    assert row["confidence"] == "override"


def test_override_wins_post_override_dedupe_against_untouched_row():
    # bc P4 bonus 0.9 on 2026-08-10 (event A) and bc P4 bonus 0.5 on 2026-08-14 (event B, a
    # different factor so the FIRST dedupe pass does not collapse them). An override on
    # 2026-08-13 factor 0.9 replaces the closer event, B -- but that override's new (date, factor)
    # now falls within window_days/factor_tol of the untouched event A. The SECOND dedupe pass
    # (which runs after overrides) must not fall back to "keep the earliest": the override row
    # must survive over the plain bc row it now collides with.
    bc = pd.DataFrame([_a("P4", "2026-08-10", "bonus", 0.9, "bc"),
                       _a("P4", "2026-08-14", "bonus", 0.5, "bc")])
    ov = pd.DataFrame([{"symbol": "P4", "ex_date": pd.Timestamp("2026-08-13"), "factor": 0.9, "note": "confirmed date"}])
    out = reconcile(bc, pd.DataFrame(), pd.DataFrame(), ov)
    p4 = out[out["symbol"] == "P4"]
    applied = p4[p4["applied"]]
    assert len(applied) == 1
    row = applied.iloc[0]
    assert row["ex_date"] == pd.Timestamp("2026-08-13")
    assert math.isclose(row["factor"], 0.9)
    assert row["confidence"] == "override"


def test_override_far_from_any_event_is_added():
    bc = pd.DataFrame([_a("FARAWAY", "2026-01-01", "bonus", 0.5, "bc")])
    ov = pd.DataFrame([{"symbol": "FARAWAY", "ex_date": pd.Timestamp("2026-02-01"), "factor": 0.6, "note": "separate event"}])
    out = reconcile(bc, pd.DataFrame(), pd.DataFrame(), ov)
    faraway = out[out["symbol"] == "FARAWAY"]
    applied = faraway[faraway["applied"]]
    assert len(applied) == 2
    added = faraway[faraway["source"] == "override"].iloc[0]
    assert added["applied"] and added["ex_date"] == pd.Timestamp("2026-02-01") and math.isclose(added["factor"], 0.6)
    original = faraway[faraway["ex_date"] == pd.Timestamp("2026-01-01")].iloc[0]
    assert original["applied"] and original["confidence"] == "single_source"


# --- Task 10: announcement revisions (latest published version wins) ----------------------------

def _pub(sym, d, kind, factor, published, description):
    row = _a(sym, d, kind, factor, "bc")
    row.update({"published": pd.Timestamp(published), "description": description})
    return row


# Real GLOBE (2021) sequence: two earlier versions with ex 2021-07-29, final split + bonus ex 2021-08-03.
GLOBE_BC = [
    _pub("GLOBE", "2021-07-29", "bonus", 2 / 3, "2021-07-20", "BONUS1:2/FVSPLIT10TO2"),
    _pub("GLOBE", "2021-07-29", "split", 0.2, "2021-07-20", "BONUS1:2/FVSPLIT10TO2"),
    _pub("GLOBE", "2021-07-29", "bonus", 1 / 3, "2021-07-23", "BONUS2:1/FVSPLIT10TO2"),
    _pub("GLOBE", "2021-07-29", "split", 0.2, "2021-07-23", "BONUS2:1/FVSPLIT10TO2"),
    _pub("GLOBE", "2021-08-03", "split", 0.2, "2021-07-30", "FVSPLT FRM RS 10 TO RS 2"),
    _pub("GLOBE", "2021-08-03", "bonus", 1 / 3, "2021-07-30", "BONUS 2:1"),
]


def test_revised_announcements_keep_only_latest_published_version():
    out = reconcile(pd.DataFrame(GLOBE_BC), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    globe = out[out["symbol"] == "GLOBE"]
    applied = globe[globe["applied"]].sort_values("kind").reset_index(drop=True)
    assert applied["kind"].tolist() == ["bonus", "split"]
    assert (applied["ex_date"] == pd.Timestamp("2021-08-03")).all()
    assert math.isclose(applied.loc[0, "factor"], 1 / 3) and math.isclose(applied.loc[1, "factor"], 0.2)
    # The superseded versions are gone entirely, not merely un-applied.
    assert len(globe) == 2


def test_genuinely_separate_bonuses_six_months_apart_both_survive():
    bc = pd.DataFrame([_pub("TWICE", "2025-01-10", "bonus", 0.5, "2025-01-02", "BONUS 1:1"),
                       _pub("TWICE", "2025-07-10", "bonus", 0.5, "2025-07-01", "BONUS 1:1")])
    out = reconcile(bc, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    applied = out[(out["symbol"] == "TWICE") & out["applied"]]
    assert applied["ex_date"].tolist() == [pd.Timestamp("2025-01-10"), pd.Timestamp("2025-07-10")]


def test_revision_collapse_leaves_non_adjusting_kinds_alone():
    bc = pd.DataFrame([_pub("DIVCO", "2025-01-10", "dividend", None, "2025-01-02", "DIV - RS 1"),
                       _pub("DIVCO", "2025-01-20", "dividend", None, "2025-01-15", "DIV - RS 2")])
    out = reconcile(bc, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    assert len(out[out["symbol"] == "DIVCO"]) == 2
