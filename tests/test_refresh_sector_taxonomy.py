from __future__ import annotations

from pathlib import Path

import duckdb

from Scripts.refresh_sector_taxonomy import (
    FetchResult,
    extract_hierarchy_from_html,
    map_hierarchy,
    run_batch,
    select_batch,
)


HIERARCHY_HTML = """
<html><body>
<p class="sub">
<a href="/market/energy/">Energy</a>
<a href="/market/oil/">Oil, Gas &amp; Consumable Fuels</a>
<a href="/market/petro/">Petroleum Products</a>
<a href="/market/refineries/">Refineries</a>
</p>
</body></html>
"""

CF_HTML = "<html><body>Just a moment... cf-browser-verification</body></html>"


def _seed(db_path: Path) -> None:
    with duckdb.connect(str(db_path)) as db:
        db.execute(
            """
            CREATE TABLE stocks_master (
                symbol TEXT,
                broad_sector TEXT,
                sector TEXT,
                broad_industry TEXT,
                industry TEXT,
                market_cap_cr DOUBLE
            )
            """
        )
        db.execute(
            """
            INSERT INTO stocks_master VALUES
            ('RELIANCE', 'Energy', 'Energy', 'Oil', 'Refineries', 100000),
            ('VAML', NULL, NULL, NULL, NULL, 178000),
            ('MANIPALHOS', NULL, NULL, NULL, NULL, 101000),
            ('GENESYS-RE', NULL, NULL, NULL, NULL, 10)
            """
        )


def test_parser_reads_sub_paragraph_links_and_unescapes():
    parts = extract_hierarchy_from_html(HIERARCHY_HTML)
    assert parts == [
        "Energy",
        "Oil, Gas & Consumable Fuels",
        "Petroleum Products",
        "Refineries",
    ]
    mapped = map_hierarchy(parts)
    assert mapped == (
        "Energy",
        "Oil, Gas & Consumable Fuels",
        "Petroleum Products",
        "Refineries",
    )


def test_parser_pads_short_hierarchy_and_ignores_cloudflare():
    html = '<p class="sub"><a>Healthcare</a><a>Hospitals</a></p>'
    assert map_hierarchy(extract_hierarchy_from_html(html)) == (
        "Healthcare",
        "Hospitals",
        "Hospitals",
        "Hospitals",
    )
    assert extract_hierarchy_from_html(CF_HTML) == []
    assert map_hierarchy([]) is None


def test_batch_fills_only_missing_and_skips_existing(tmp_path):
    db_path = tmp_path / "marketpulse.duckdb"
    sector_file = tmp_path / "sector.csv"
    state_path = tmp_path / "state.json"
    _seed(db_path)
    sector_file.write_text("RELIANCE,Energy,Energy,Oil,Refineries\n", encoding="utf-8")

    def fetch(symbol: str) -> FetchResult:
        if symbol == "GENESYS-RE":
            return FetchResult(404, "Not Found")
        return FetchResult(200, HIERARCHY_HTML)

    sleeps: list[float] = []
    result = run_batch(
        db_path=db_path,
        sector_file=sector_file,
        state_path=state_path,
        batch_size=10,
        mini_delay_s=1.5,
        fetch_one=fetch,
        sleep=sleeps.append,
    )

    assert result["filled"] == 2
    assert result["invalid"] == 1
    csv_text = sector_file.read_text(encoding="utf-8")
    assert "VAML,Energy," in csv_text
    assert "MANIPALHOS,Energy," in csv_text
    assert csv_text.count("RELIANCE") == 1
    with duckdb.connect(str(db_path), read_only=True) as db:
        vaml = db.execute(
            "SELECT broad_sector, sector, industry FROM stocks_master WHERE symbol = 'VAML'"
        ).fetchone()
        reliance = db.execute(
            "SELECT sector FROM stocks_master WHERE symbol = 'RELIANCE'"
        ).fetchone()
        genesys = db.execute(
            "SELECT sector FROM stocks_master WHERE symbol = 'GENESYS-RE'"
        ).fetchone()
    assert vaml == ("Energy", "Oil, Gas & Consumable Fuels", "Refineries")
    assert reliance[0] == "Energy"
    assert genesys[0] is None
    assert sleeps == [1.5, 1.5]


def test_rate_limit_stops_batch_and_does_not_write(tmp_path):
    db_path = tmp_path / "marketpulse.duckdb"
    sector_file = tmp_path / "sector.csv"
    state_path = tmp_path / "state.json"
    _seed(db_path)
    sector_file.write_text("", encoding="utf-8")
    calls: list[str] = []

    def fetch(symbol: str) -> FetchResult:
        calls.append(symbol)
        return FetchResult(429, "Too Many Requests")

    result = run_batch(
        db_path=db_path,
        sector_file=sector_file,
        state_path=state_path,
        batch_size=10,
        mini_delay_s=0,
        fetch_one=fetch,
        sleep=lambda _s: None,
    )

    assert result["filled"] == 0
    assert result["retried"] == 1
    assert calls == ["VAML"]
    assert "VAML" in (state_path.read_text(encoding="utf-8"))
    with duckdb.connect(str(db_path), read_only=True) as db:
        assert db.execute("SELECT sector FROM stocks_master WHERE symbol = 'VAML'").fetchone()[0] is None


def test_select_batch_skips_invalid_and_respects_retry_cooldown():
    missing = ["AAA", "BBB", "CCC"]
    state = {
        "skip": {"BBB": "invalid_symbol"},
        "retry": {"AAA": {"status": "RETRY", "attempts": 1, "next_ok_at": "2099-01-01T00:00:00+00:00"}},
    }
    assert select_batch(missing, state, batch_size=10, retry_failed=False) == ["CCC"]
    assert select_batch(missing, state, batch_size=10, retry_failed=True) == ["AAA"]


def test_daily_pipeline_wires_taxonomy_fill():
    root = Path(__file__).resolve().parents[1]
    daily = (root / "Scripts" / "daily_pipeline.py").read_text(encoding="utf-8")
    assert "refresh_sector_taxonomy" in daily
    assert "sector_taxonomy" in daily
