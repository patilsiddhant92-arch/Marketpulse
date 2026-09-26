"""NSE symbol change history (symbolchange.csv) → current-symbol mapping."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def parse_symbol_changes(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, header=None, dtype=str, names=["company", "old_symbol", "new_symbol", "change_date"],
                      skipinitialspace=True, on_bad_lines="skip")
    raw["old_symbol"] = raw["old_symbol"].astype(str).str.strip().str.upper()
    raw["new_symbol"] = raw["new_symbol"].astype(str).str.strip().str.upper()
    raw["change_date"] = pd.to_datetime(raw["change_date"].astype(str).str.strip(), format="%d-%b-%Y", errors="coerce")
    raw = raw[(raw["old_symbol"] != "") & (raw["new_symbol"] != "") & (raw["old_symbol"] != raw["new_symbol"])]
    return raw[["old_symbol", "new_symbol", "change_date"]].sort_values("change_date").reset_index(drop=True)


def resolve_current_symbol(changes: pd.DataFrame) -> dict[str, str]:
    """Map every old symbol to its latest symbol, following chains; symbols in a cycle are skipped."""
    step = dict(zip(changes["old_symbol"], changes["new_symbol"]))
    resolved: dict[str, str] = {}
    for start in step:
        seen = {start}
        cur = step[start]
        while cur in step and cur not in seen:
            seen.add(cur)
            cur = step[cur]
        if cur in seen:  # A→B→A: ambiguous, leave unmapped
            continue
        resolved[start] = cur
    return resolved
