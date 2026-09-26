from __future__ import annotations

import pandas as pd

from build_index_name_map import derive_name_map
from index_history import load_all_index_history, parse_ind_close_all

CSV = """Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield
Nifty 50,25-09-2026,25000.00,25100.00,24900.00,25050.00,50.00,0.20,300000000,25000.5,22.1,3.5,1.2
NIFTY Midsmallcap 400,25-09-2026,19000.00,19100.00,18900.00,19080.00,-20.00,-0.10,-,-,-,-,-
"""


def test_parse_ind_close_all(tmp_path):
    p = tmp_path / "ind_close_all_25092026.csv"
    p.write_text(CSV)
    df = parse_ind_close_all(p)
    row = df.set_index("index_name").loc["Nifty 50"]
    assert row["close_price"] == 25050.0 and row["previous_close"] == 25000.0
    assert row["return_1d_pct"] == 0.2 and row["volume"] == 300000000 and row["pe"] == 22.1
    assert str(df["trade_date"].iloc[0].date()) == "2026-09-25"
    assert pd.isna(df.set_index("index_name").loc["NIFTY Midsmallcap 400", "pe"])


def test_derive_name_map_by_matching_closes():
    dates = pd.to_datetime(["2026-09-2%d" % i for i in range(1, 7)])
    close_all = pd.DataFrame({"trade_date": list(dates) * 2,
                              "index_name": ["NIFTY Midsmallcap 400"] * 6 + ["Nifty 50"] * 6,
                              "close_price": [19000 + i for i in range(6)] + [25000 + i for i in range(6)]})
    ma = pd.DataFrame({"trade_date": list(dates) * 2,
                       "index_name": ["NIFTY MIDSML 400"] * 6 + ["Nifty 50"] * 6,
                       "close_price": [19000 + i for i in range(6)] + [25000 + i for i in range(6)]})
    m = derive_name_map(close_all, ma).set_index("source_name")
    assert m.loc["NIFTY Midsmallcap 400", "canonical_name"] == "NIFTY MIDSML 400"
    assert m.loc["Nifty 50", "canonical_name"] == "Nifty 50"


def test_derive_name_map_is_one_to_one():
    dates = pd.to_datetime(["2026-09-2%d" % i for i in range(1, 7)])
    close_all = pd.DataFrame({
        "trade_date": list(dates) * 2,
        "index_name": ["Nifty 50"] * 6 + ["Nifty 50 Futures Index"] * 6,
        "close_price": [25000 + i for i in range(6)] * 2,
    })
    ma = pd.DataFrame({
        "trade_date": dates,
        "index_name": ["Nifty 50"] * 6,
        "close_price": [25000 + i for i in range(6)],
    })
    m = derive_name_map(close_all, ma)
    canon_rows = m[m["canonical_name"] == "Nifty 50"]
    assert len(canon_rows) == 1
    assert canon_rows.iloc[0]["source_name"] == "Nifty 50"


def test_load_all_prefers_close_all_and_fills_from_ma(tmp_path, monkeypatch):
    daily = tmp_path / "Input" / "daily"
    daily.mkdir(parents=True)
    (daily / "ind_close_all_25092026.csv").write_text(CSV)
    ref = tmp_path / "map.csv"
    ref.write_text("source_name,canonical_name\nNIFTY Midsmallcap 400,NIFTY MIDSML 400\n")
    ma = pd.DataFrame({"trade_date": pd.to_datetime(["2026-09-24", "2026-09-25"]),
                       "index_name": ["NIFTY MIDSML 400", "NIFTY MIDSML 400"],
                       "previous_close": [1.0, 1.0], "open_price": [1.0, 1.0], "high_price": [1.0, 1.0],
                       "low_price": [1.0, 1.0], "close_price": [18000.0, 99999.0], "change_value": [0.0, 0.0],
                       "return_1d_pct": [0.0, 0.0]})
    import index_history
    monkeypatch.setattr(index_history, "load_all_market_activity_history", lambda root: ma)
    out = load_all_index_history(tmp_path, ref).set_index(["trade_date", "index_name"])
    assert out.loc[(pd.Timestamp("2026-09-25"), "NIFTY MIDSML 400"), "close_price"] == 19080.0  # close_all wins
    assert out.loc[(pd.Timestamp("2026-09-24"), "NIFTY MIDSML 400"), "close_price"] == 18000.0  # MA fills gap
