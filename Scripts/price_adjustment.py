"""Split / bonus / consolidation price adjustment from official NSE data."""
from __future__ import annotations

import re
from dataclasses import dataclass

ADJUSTING_KINDS = frozenset({"split", "bonus", "consolidation"})

_NUM = r"(\d+(?:\.\d+)?)"
_BONUS_RE = re.compile(rf"BONUS\D*?{_NUM}\s*:\s*{_NUM}")
# "FROM RS 10 ... TO RE 1", "RS.10 TO RS.2", "FRM RS 2 TO RE 1"
_FV_RE = re.compile(rf"(?:FROM|FRM)?\s*R[SE]\.?\s*{_NUM}\D*?\bTO\b\s*R[SE]\.?\s*{_NUM}")
# Match SPLIT, SPLT, SUB-DIVISION, SUB - DIVISION, SUB DIVISION, SUBDIVISION
_SPLIT_RE = re.compile(r"SPLIT|SPLT|SUB\s*-?\s*DIVISION")
# Match DIV with word boundaries to avoid matching inside DIVISION
_DIV_RE = re.compile(r"\bDIV(IDEND)?\b|\bDIV\s*-")


@dataclass(frozen=True)
class ParsedAction:
    kind: str
    factor: float | None


def parse_purpose(purpose: str) -> ParsedAction:
    text = re.sub(r"\s+", " ", str(purpose or "").upper()).strip()
    if not text:
        return ParsedAction("other", None)

    # Check for pref_bonus first (takes precedence even if BONUS pattern matches)
    if "BONUS" in text and ("NCRPS" in text or "PREF" in text or "DEBENTURE" in text):
        return ParsedAction("pref_bonus", None)

    # Try to parse adjusting actions (bonus, split, consolidation)
    # These should be checked before non-adjusting (rights, demerger, div)
    # so that combined purposes like "BONUS 1:1 AND RIGHTS" return the bonus

    # Try bonus first
    has_bonus = "BONUS" in text
    if has_bonus:
        m = _BONUS_RE.search(text)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            if a > 0 and b > 0:
                return ParsedAction("bonus", b / (a + b))
        # BONUS text exists but no valid pattern → return "other"
        return ParsedAction("other", None)

    # Try split/consolidation
    is_split = _SPLIT_RE.search(text) is not None
    is_consolidation = "CONSOLIDAT" in text
    if is_split or is_consolidation:
        m = _FV_RE.search(text)
        if m:
            old, new = float(m.group(1)), float(m.group(2))
            if old > 0 and new > 0 and old != new:
                return ParsedAction("consolidation" if new > old else "split", new / old)
        # SPLIT/CONSOLIDATION text exists but no valid pattern → return "other"
        return ParsedAction("other", None)

    # Fall back to non-adjusting keywords
    if "RIGHTS" in text:
        return ParsedAction("rights", None)
    if "DEMERGER" in text or "DE-MERGER" in text:
        return ParsedAction("demerger", None)
    if _DIV_RE.search(text):
        return ParsedAction("dividend", None)

    return ParsedAction("other", None)
