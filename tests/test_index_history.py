from datetime import date


def test_parse_market_activity_extracts_index_rows(tmp_path):
    from Scripts.index_history import parse_market_activity

    path = tmp_path / "MA030826.csv"
    path.write_text(
        ",03-Aug-2026\n"
        ",INDEX,PREVIOUS CLOSE,OPEN,HIGH,LOW,CLOSE,GAIN/LOSS\n"
        ",Nifty 500,100,101,103,99,102,2\n"
        ",Nifty IT,200,198,201,195,196,-4\n",
        encoding="utf-8",
    )

    result = parse_market_activity(path, date(2026, 8, 3))

    assert result["index_name"].tolist() == ["Nifty 500", "Nifty IT"]
    assert result.loc[0, "return_1d_pct"] == 2.0


def test_index_features_use_prior_sessions_only():
    import pandas as pd
    from Scripts.index_history import build_index_features

    frame = pd.DataFrame(
        [{"trade_date": date(2026, 1, i), "index_name": "Nifty 500", "close_price": float(i)} for i in range(1, 6)]
    )
    result = build_index_features(frame)

    assert "return_5d_pct" in result.columns
    assert result.loc[result["trade_date"] == pd.Timestamp("2026-01-01"), "return_5d_pct"].isna().all()
