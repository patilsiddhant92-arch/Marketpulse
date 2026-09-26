from __future__ import annotations

import io
import math
import zipfile

import pandas as pd

from price_adjustment import (actions_from_bc_frame, actions_from_corporate_actions_table,
                              collect_bc_actions, read_bc_member)

BC_2026 = """SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE
EQ,GOODLUCK,Goodluck India Ltd,2026-08-21,,,2026-08-21,,,BONUS 2:1
EQ,KIRLPNU,Kirloskar Pneumatic,2026-08-18,,,2026-08-18,,,FVSPLT FRM RS 2 TO RE 1
BE,SIYSIL,Siyaram Silk Mills Ltd,2026-08-22,,,2026-08-21,,,SCH AGMT-BONUS NCRPS 4:1
N1,SOMEBOND,Bond,2026-08-21,,,2026-08-21,,,BONUS 1:1
"""
BC_2019 = """SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE
EQ,OLDCO,Old Co Ltd, ,24/09/2019,30/09/2019,20/09/2019, , ,FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RS 2/- PER SHARE
"""


def _zip(tmp_path, name, member, text):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(member, text)
        zf.writestr("Pd240919.csv", "x")
    return p


def test_read_bc_member_handles_both_name_styles(tmp_path):
    z1 = _zip(tmp_path, "PR210826.zip", "bc21082026.csv", BC_2026)
    z2 = _zip(tmp_path, "PR240919.zip", "Bc240919.csv", BC_2019)
    assert len(read_bc_member(zipfile.ZipFile(z1))) == 4
    assert len(read_bc_member(zipfile.ZipFile(z2))) == 1


def test_actions_from_bc_frame_parses_dates_kinds_and_series(tmp_path):
    raw = pd.read_csv(io.StringIO(BC_2026), dtype=str, keep_default_na=False)
    a = actions_from_bc_frame(raw).set_index("symbol")
    assert "SOMEBOND" not in a.index
    assert str(a.loc["GOODLUCK", "ex_date"].date()) == "2026-08-21"
    assert a.loc["GOODLUCK", "kind"] == "bonus" and math.isclose(a.loc["GOODLUCK", "factor"], 1 / 3)
    assert a.loc["KIRLPNU", "kind"] == "split" and math.isclose(a.loc["KIRLPNU", "factor"], 0.5)
    assert a.loc["SIYSIL", "kind"] == "pref_bonus" and pd.isna(a.loc["SIYSIL", "factor"])
    raw19 = pd.read_csv(io.StringIO(BC_2019), dtype=str, keep_default_na=False)
    b = actions_from_bc_frame(raw19).iloc[0]
    assert str(b["ex_date"].date()) == "2019-09-20" and math.isclose(b["factor"], 0.2)


def test_collect_dedupes_across_zips(tmp_path):
    z1 = _zip(tmp_path, "PR210826.zip", "bc21082026.csv", BC_2026)
    z2 = _zip(tmp_path, "PR220826.zip", "bc22082026.csv", BC_2026)
    assert collect_bc_actions([z1, z2])["symbol"].tolist().count("GOODLUCK") == 1


def test_actions_from_db_table():
    df = pd.DataFrame({"symbol": ["TCC"], "ex_date": pd.to_datetime(["2026-09-04"]),
                       "action_type": ["other"], "description": ["FVSPLT FRM RS 10 TO RS 2"]})
    a = actions_from_corporate_actions_table(df).iloc[0]
    assert a["kind"] == "split" and math.isclose(a["factor"], 0.2) and a["source"] == "bc"


# --- Task 10: one purpose -> one row per parsed action -----------------------------------------

BC_MULTI = """SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE
EQ,GLOBE,Globe Textiles (I) Ltd.,30/07/2021, , ,29/07/2021, , ,BONUS2:1/FVSPLIT10TO2
EQ,OTHERCO,Other Co,30/07/2021, , ,29/07/2021, , ,DIV - RS 2 PER SH
"""


def test_bc_frame_expands_multi_action_purpose_into_rows():
    raw = pd.read_csv(io.StringIO(BC_MULTI), dtype=str, keep_default_na=False)
    a = actions_from_bc_frame(raw)
    globe = a[a["symbol"] == "GLOBE"].reset_index(drop=True)
    assert globe["kind"].tolist() == ["bonus", "split"]
    assert math.isclose(globe.loc[0, "factor"], 1 / 3) and math.isclose(globe.loc[1, "factor"], 0.2)
    assert (globe["description"] == "BONUS2:1/FVSPLIT10TO2").all()
    assert (globe["ex_date"] == pd.Timestamp("2021-07-29")).all() and (globe["source"] == "bc").all()
    assert a[a["symbol"] == "OTHERCO"]["kind"].tolist() == ["dividend"]


def test_collect_keeps_both_actions_of_a_multi_action_purpose(tmp_path):
    z = _zip(tmp_path, "PR200721.zip", "bc20072021.csv", BC_MULTI)
    a = collect_bc_actions([z])
    assert sorted(a[a["symbol"] == "GLOBE"]["kind"].tolist()) == ["bonus", "split"]


BC_ONE_BAD_LINE = """SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE
EQ,GOODLUCK,Goodluck India Ltd,2026-08-21,,,2026-08-21,,,BONUS 2:1
EQ,BADCO,Bad Co, Ltd,2026-08-21,,,2026-08-21,,,DIV - RS 2 PER SH
EQ,KIRLPNU,Kirloskar Pneumatic,2026-08-18,,,2026-08-18,,,FVSPLT FRM RS 2 TO RE 1
"""


def test_malformed_bc_line_is_skipped_not_the_whole_file(tmp_path, capsys):
    # Real case: PR210824.zip -- "Expected 10 fields in line 162, saw 11" used to drop the file.
    z = _zip(tmp_path, "PR210824.zip", "bc21082024.csv", BC_ONE_BAD_LINE)
    a = collect_bc_actions([z])
    assert set(a["symbol"]) == {"GOODLUCK", "KIRLPNU"}
    out = capsys.readouterr().out
    warnings = [line for line in out.splitlines() if "PR210824.zip" in line]
    assert len(warnings) == 1
    assert "1 malformed line" in warnings[0]


def test_db_table_expands_multi_action_purpose():
    df = pd.DataFrame({"symbol": ["GLOBE"], "ex_date": pd.to_datetime(["2021-08-03"]),
                       "action_type": ["bonus"], "description": ["BONUS 1:1 AND FV SPLIT FROM RS 10 TO RS 2"]})
    a = actions_from_corporate_actions_table(df)
    assert a["kind"].tolist() == ["bonus", "split"]
    assert math.isclose(a["factor"].iloc[0], 0.5) and math.isclose(a["factor"].iloc[1], 0.2)
