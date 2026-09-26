from __future__ import annotations

import math

import pytest

from price_adjustment import ParsedAction, parse_purpose


@pytest.mark.parametrize("text,kind,factor", [
    ("BONUS 2:1", "bonus", 1 / 3),
    ("BONUS 1:1", "bonus", 0.5),
    ("BONUS 3:2", "bonus", 0.4),
    ("Bonus 1 : 2", "bonus", 2 / 3),
    ("FVSPLT FRM RS 2 TO RE 1", "split", 0.5),
    ("FVSPLT FRM RS 10 TO RE 1", "split", 0.1),
    ("FVSPLT FRM RS 10 TO RS 2", "split", 0.2),
    ("FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RS 2/- PER SHARE", "split", 0.2),
    ("FV SPLIT RS.10 TO RS.2", "split", 0.2),
    ("FV SPLIT FROM RS 5/- TO RE 1/-", "split", 0.2),
    ("CONSOLIDATION OF SHARES FROM RS 1 TO RS 10", "consolidation", 10.0),
    ("SUB - DIVISION FROM RS 10 TO RS 1", "split", 0.1),
    ("SUB DIVISION OF SHARES FROM RS 10 TO RS 2", "split", 0.2),
    ("BONUS 1:1 AND RIGHTS 1:2", "bonus", 0.5),
    ("CONSOLIDATION OF SHARES FROM RS 5 TO RS 10 AND RIGHTS 1:1", "consolidation", 2.0),
    ("BONUS ISSUE 1:2", "bonus", 2 / 3),
])
def test_adjusting_actions(text, kind, factor):
    p = parse_purpose(text)
    assert p.kind == kind
    assert math.isclose(p.factor, factor, rel_tol=1e-9)


@pytest.mark.parametrize("text,kind", [
    ("SCH AGMT-BONUS NCRPS 4:1", "pref_bonus"),
    ("SCH AGMT-BONUS NCRPS46:1", "pref_bonus"),
    ("BONUS PREF SHARES 1:1", "pref_bonus"),
    ("RIGHTS 3:8@ PRM RS 14/-", "rights"),
    ("RIGHTS- 7CCPS/ 7WRNTS:40", "rights"),
    ("DEMERGER", "demerger"),
    ("DIV - RS 1.47 PER SH", "dividend"),
    ("AGM/DIV-RS 0.50 PER SH", "dividend"),
    ("ANNUAL GENERAL MEETING", "other"),
    ("", "other"),
    ("INTERIM DIVIDEND - RS 5 PER SHARE", "dividend"),
    ("RIGHTS ISSUE", "rights"),
    ("BONUS ISSUE AND RIGHTS ISSUE", "rights"),
    ("FV SPLIT AND DEMERGER", "demerger"),
    ("SPLIT AND DIV - RS 2 PER SHARE", "dividend"),
    ("BONUS ISSUE AND DEMERGER", "demerger"),
    ("FV SPLIT AND RIGHTS ISSUE", "rights"),
    ("BONUS AND RIGHTS 1:2", "rights"),
])
def test_non_adjusting_actions(text, kind):
    p = parse_purpose(text)
    assert p == ParsedAction(kind, None)


def test_unparseable_split_is_other_not_guessed():
    assert parse_purpose("FV SPLIT") == ParsedAction("other", None)


# --- Task 10: multi-action purposes (parse_purpose_all) and RS-less face-value forms ---------

from price_adjustment import parse_purpose_all  # noqa: E402

_ADJUSTING_CASES = [
    ("BONUS 2:1", "bonus", 1 / 3),
    ("BONUS 1:1", "bonus", 0.5),
    ("BONUS 3:2", "bonus", 0.4),
    ("Bonus 1 : 2", "bonus", 2 / 3),
    ("FVSPLT FRM RS 2 TO RE 1", "split", 0.5),
    ("FVSPLT FRM RS 10 TO RE 1", "split", 0.1),
    ("FVSPLT FRM RS 10 TO RS 2", "split", 0.2),
    ("FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RS 2/- PER SHARE", "split", 0.2),
    ("FV SPLIT RS.10 TO RS.2", "split", 0.2),
    ("FV SPLIT FROM RS 5/- TO RE 1/-", "split", 0.2),
    ("CONSOLIDATION OF SHARES FROM RS 1 TO RS 10", "consolidation", 10.0),
    ("SUB - DIVISION FROM RS 10 TO RS 1", "split", 0.1),
    ("SUB DIVISION OF SHARES FROM RS 10 TO RS 2", "split", 0.2),
    ("BONUS 1:1 AND RIGHTS 1:2", "bonus", 0.5),
    ("CONSOLIDATION OF SHARES FROM RS 5 TO RS 10 AND RIGHTS 1:1", "consolidation", 2.0),
    ("BONUS ISSUE 1:2", "bonus", 2 / 3),
]


def test_parse_purpose_all_bonus_and_rs_less_split():
    # Real NSE text (GLOBE 2021): a bonus AND a split in one purpose, split part without "RS".
    out = parse_purpose_all("BONUS2:1/FVSPLIT10TO2")
    assert [a.kind for a in out] == ["bonus", "split"]
    assert math.isclose(out[0].factor, 1 / 3) and math.isclose(out[1].factor, 0.2)


def test_parse_purpose_all_bonus_and_split_with_rs():
    out = parse_purpose_all("BONUS 1:1 AND FV SPLIT FROM RS 10 TO RS 2")
    assert [a.kind for a in out] == ["bonus", "split"]
    assert math.isclose(out[0].factor, 0.5) and math.isclose(out[1].factor, 0.2)


def test_parse_purpose_all_keeps_text_order():
    out = parse_purpose_all("FVSPLT FRM RS 10 TO RS 2 AND BONUS 1:1")
    assert [a.kind for a in out] == ["split", "bonus"]
    # parse_purpose keeps its historical precedence (bonus first) for multi-action text.
    assert parse_purpose("FVSPLT FRM RS 10 TO RS 2 AND BONUS 1:1").kind == "bonus"


@pytest.mark.parametrize("text,factor", [
    ("FVSPLIT10TO2", 0.2),
    ("FV SPLIT 10 TO 2", 0.2),
    ("SPLIT FROM 10 TO 1", 0.1),
])
def test_rs_less_face_value_forms(text, factor):
    out = parse_purpose_all(text)
    assert len(out) == 1 and out[0].kind == "split" and math.isclose(out[0].factor, factor)
    single = parse_purpose(text)
    assert single.kind == "split" and math.isclose(single.factor, factor)


def test_rs_less_form_ignores_implausible_numbers_like_years():
    # A date range after a SPLIT keyword must not be mistaken for a face-value change.
    assert parse_purpose_all("FV SPLIT BC 01/08/2021 TO 05/08/2021") == [ParsedAction("other", None)]


@pytest.mark.parametrize("text,kind,factor", _ADJUSTING_CASES)
def test_parse_purpose_all_single_action_unchanged(text, kind, factor):
    out = parse_purpose_all(text)
    assert len(out) == 1
    assert out[0].kind == kind and math.isclose(out[0].factor, factor, rel_tol=1e-9)


@pytest.mark.parametrize("text", [
    "SCH AGMT-BONUS NCRPS 4:1", "RIGHTS 3:8@ PRM RS 14/-", "RIGHTS- 7CCPS/ 7WRNTS:40", "DEMERGER",
    "DIV - RS 1.47 PER SH", "ANNUAL GENERAL MEETING", "", "BONUS ISSUE AND RIGHTS ISSUE", "FV SPLIT",
    "SPLIT AND DIV - RS 2 PER SHARE", "BONUS AND RIGHTS 1:2",
])
def test_parse_purpose_all_non_adjusting_is_single_classification(text):
    assert parse_purpose_all(text) == [parse_purpose(text)]


def test_rights_stays_one_rights_action():
    assert parse_purpose_all("RIGHTS 3:8@ PRM RS 14/-") == [ParsedAction("rights", None)]


@pytest.mark.parametrize("text,bonus,split", [
    ("BON1:1/FVSPLTFRMRS5TORS2", 0.5, 0.4),      # real NSE text: TIDEWATER, ex 2021-07-26
    ("BON 2:1/FVSPLIT RS2TORE1", 1 / 3, 0.5),    # real NSE text: SHRENIK, ex 2020-10-08
])
def test_bon_abbreviation_yields_bonus_and_split(text, bonus, split):
    out = parse_purpose_all(text)
    assert [a.kind for a in out] == ["bonus", "split"]
    assert math.isclose(out[0].factor, bonus) and math.isclose(out[1].factor, split)


@pytest.mark.parametrize("text,factor", [
    ("CNSLDATNRE1 TO RS10", 10.0),        # real NSE text: VERTOZ, ex 2025-06-25
    ("CNSLDATN RE 1 TO RS 10", 10.0),     # real NSE text: SHEKHAWATI, ex 2024-08-28
    ("CNSLDATNRS10 TO RS1000", 100.0),    # real NSE text: KAUSHALYA, ex 2024-01-12
])
def test_cnsldatn_abbreviation_is_consolidation(text, factor):
    assert parse_purpose_all(text) == [ParsedAction("consolidation", factor)]


@pytest.mark.parametrize("text", [
    "REDEMPTION OF BONDS 1:1", "INT ON BONDS", "CARBON 2:1", "CARBON1:1", "BONANZA 1:1",
    "XBON 1:1", "BON", "BONDS",
])
def test_bon_does_not_match_inside_other_words(text):
    assert all(a.kind != "bonus" for a in parse_purpose_all(text))
    assert parse_purpose(text).kind != "bonus"
