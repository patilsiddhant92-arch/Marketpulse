from __future__ import annotations

from datetime import date

import duckdb


def test_score_comparison_reports_overlap_rejections_and_rank_changes(tmp_path):
    path = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(path)) as db:
        db.execute(
            """
            CREATE TABLE candidate_daily (
                trade_date DATE, symbol TEXT, score_version TEXT, candidate_state TEXT,
                total_score DOUBLE, rank_overall INTEGER, eligibility_status TEXT,
                blocking_reasons TEXT, warning_reasons TEXT, market_cap_cr DOUBLE,
                market_regime TEXT, sector TEXT, sector_state TEXT, event_risk TEXT
            )
            """
        )
        db.executemany(
            "INSERT INTO candidate_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (date(2026, 8, 7), "AAA", "focused-v1", "Prepare", 80, 1, "eligible", "", "", 1500, "Constructive", "Tech", "Leading", "none"),
                (date(2026, 8, 7), "BBB", "focused-v1", "Prepare", 70, 2, "eligible", "", "", 1300, "Constructive", "Banks", "Improving", "none"),
                (date(2026, 8, 7), "AAA", "focused-v2", "Prepare", 88, 2, "eligible", "", "", 1500, "Constructive", "Tech", "Leading", "none"),
                (date(2026, 8, 7), "CCC", "focused-v2", "Blocked", 77, 1, "blocked", "market_cap_below_1000cr;risk_geometry_missing", "", 800, "Constructive", "Industrials", "Improving", "warn"),
            ],
        )

    from Scripts.compare_score_versions import compare_score_versions

    report = compare_score_versions(path, date(2026, 8, 7))

    assert report.row_counts == {"focused-v1": 2, "focused-v2": 2}
    assert report.overlap_count == 1
    assert report.only_v1 == ("BBB",)
    assert report.only_v2 == ("CCC",)
    assert report.rejection_reasons["market_cap_below_1000cr"] == 1
    assert report.rank_changes.iloc[0]["rank_delta"] == 1
    assert report.sessions_evaluated == 1
