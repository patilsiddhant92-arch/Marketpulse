from __future__ import annotations

import io

import pandas as pd

from build_database import clean_columns, parse_market_cap_frame
from reference_history import load_reference_history

CSV = """Trade Date,Symbol,Series,Security Name,Category,Last Trade Date,Face Value(Rs.),Issue Size,Close Price/Paid up value(Rs.),Market Cap(Rs.)
25 SEP 2026,TOTAL,BE,TOTAL TRANSPORT SYS LTD  ,Listed    ,25 SEP 2026,  10.00,  16126973,  70.85,  1142757306.80
25 SEP 2026,ATGL,EQ,ADANI TOTAL GAS LIMITED  ,Listed    ,25 SEP 2026,   1.00,1099810083, 611.65,672698837266.95
25 SEP 2026,Listed    ,  ,                         ,          ,           ,   0.00,         0,   0.00,473225303955365.40
25 SEP 2026,Permitted ,  ,                         ,          ,           ,   0.00,         0,   0.00,  3821649856571.00
25 SEP 2026,Total     ,  ,                         ,          ,           ,   0.00,         0,   0.00,477046953811936.40
"""


def test_summary_rows_are_dropped_and_real_total_kept():
    raw = clean_columns(pd.read_csv(io.StringIO(CSV), dtype=str, skipinitialspace=True))
    out = parse_market_cap_frame(raw)
    assert set(out["symbol"]) == {"TOTAL", "ATGL"}
    total = out.set_index("symbol").loc["TOTAL", "market_cap_cr"]
    assert 100 < total < 200  # ~114.3 Cr, not 4.77e7


def test_reference_history_mcap_loader_drops_summary_rows(tmp_path):
    daily = tmp_path / "Input" / "daily"
    daily.mkdir(parents=True)
    (daily / "mcap25092026.csv").write_text(CSV, encoding="utf-8")

    history = load_reference_history(tmp_path)

    assert set(history["symbol"]) == {"TOTAL", "ATGL"}
    total = history.set_index("symbol").loc["TOTAL", "market_cap_cr"]
    assert 100 < total < 200  # ~114.3 Cr, not 4.77e7
