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
])
def test_non_adjusting_actions(text, kind):
    p = parse_purpose(text)
    assert p == ParsedAction(kind, None)


def test_unparseable_split_is_other_not_guessed():
    assert parse_purpose("FV SPLIT") == ParsedAction("other", None)
