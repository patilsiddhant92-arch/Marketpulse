from datetime import datetime
from pathlib import Path
from Scripts.backfill_ma_index_archives import download_ma_for_date
from Scripts.index_history import parse_market_activity
from Scripts.true_rs import BENCH_MIDSML400, BENCH_NIFTY50

def test_ma_known_date_parses_benches():
    day = datetime(2026, 8, 4)
    path = download_ma_for_date(day, sleep_s=0.0)
    assert path is not None and Path(path).exists()
    frame = parse_market_activity(path, day.date())
    names = set(frame["index_name"].astype(str))
    assert BENCH_NIFTY50 in names
    assert BENCH_MIDSML400 in names
