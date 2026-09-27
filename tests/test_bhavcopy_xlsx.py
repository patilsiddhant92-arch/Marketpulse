"""read_bhavcopy parses an XLSX saved under a .csv name (zip magic) with the stdlib only."""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
import pytest

import build_database

HEADER = ["SYMBOL", " SERIES", " DATE1", " PREV_CLOSE", " OPEN_PRICE", " HIGH_PRICE", " LOW_PRICE", " LAST_PRICE",
          " CLOSE_PRICE", " AVG_PRICE", " TTL_TRD_QNTY", " TURNOVER_LACS", " NO_OF_TRADES", " DELIV_QTY", " DELIV_PER"]
ROWS = [
    ["20MICRONS", " EQ", " 08-Aug-2022", 108.1, 109.45, 115.45, 108.7, 112.0, 112.3, 112.21, 250000, 280.5, 3000, 120000, 48.0],
    ["ZYDUSLIFE", " EQ", " 08-Aug-2022", 380.0, 381.0, 390.0, 379.5, 388.0, 388.55, 386.1, 1200000, 4633.2, 40000, " -", " -"],
    ["SOMEBOND", " N1", " 08-Aug-2022", 1000, 1000, 1000, 1000, 1000, 1000, 1000, 10, 0.1, 1, " -", " -"],
]


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _write_csv(path: Path) -> None:
    lines = [",".join(HEADER)] + [",".join(str(v) for v in row) for row in ROWS]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_xlsx(path: Path, inline_first_symbol: bool = False) -> None:
    strings: list[str] = []

    def sid(value: str) -> int:
        if value not in strings:
            strings.append(value)
        return strings.index(value)

    rows_xml = []
    for r, row in enumerate([HEADER] + ROWS, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{_col(c)}{r}"
            if isinstance(value, str):
                if inline_first_symbol and r == 2 and c == 0:
                    cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
                else:
                    cells.append(f'<c r="{ref}" t="s"><v>{sid(value)}</v></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        rows_xml.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    sheet = f'<?xml version="1.0" encoding="UTF-8"?><worksheet {ns}><sheetData>{"".join(rows_xml)}</sheetData></worksheet>'
    sst_items = "".join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in strings)
    sst = f'<?xml version="1.0" encoding="UTF-8"?><sst {ns} count="{len(strings)}" uniqueCount="{len(strings)}">{sst_items}</sst>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", f"<workbook {ns}/>")
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


@pytest.mark.parametrize("inline", [False, True])
def test_xlsx_frame_matches_csv_frame(tmp_path, inline):
    csv_path = tmp_path / "csv" / "sec_bhavdata_full_08082022.csv"
    xlsx_path = tmp_path / "xlsx" / "sec_bhavdata_full_08082022.csv"
    csv_path.parent.mkdir()
    xlsx_path.parent.mkdir()
    _write_csv(csv_path)
    _write_xlsx(xlsx_path, inline_first_symbol=inline)
    assert xlsx_path.read_bytes()[:2] == b"PK"
    from_csv = build_database.read_bhavcopy(csv_path).reset_index(drop=True)
    from_xlsx = build_database.read_bhavcopy(xlsx_path).reset_index(drop=True)
    pd.testing.assert_frame_equal(from_xlsx, from_csv)
    assert list(from_xlsx["symbol"]) == ["20MICRONS", "ZYDUSLIFE"]
    assert (from_xlsx["trade_date"] == pd.Timestamp("2022-08-08")).all()


def test_xlsx_excel_serial_dates_are_converted(tmp_path):
    rows = [["AAA", "EQ", 44781, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]]  # 44781 == 2022-08-08
    path = tmp_path / "sec_bhavdata_full_08082022.csv"
    global ROWS
    saved = ROWS
    try:
        ROWS = rows
        _write_xlsx(path)
    finally:
        ROWS = saved
    frame = build_database.read_bhavcopy(path)
    assert frame["trade_date"].tolist() == [pd.Timestamp("2022-08-08")]


@pytest.mark.realdb
def test_real_08082022_xlsx_file():
    path = Path(r"D:\Sid\MarketPulse2.0\Input\archive\backfill\bhav\sec_bhavdata_full_08082022.csv")
    if not path.exists():
        pytest.skip("real backfill file not available")
    frame = build_database.read_bhavcopy(path)
    assert 1500 <= len(frame) <= 2600
    assert set(frame["trade_date"].dt.date.astype(str)) == {"2022-08-08"}
    assert frame["close_price"].notna().all()
