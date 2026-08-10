from pathlib import Path


def test_app_exposes_candidates_health_and_loopback_default():
    source = Path("App/app.py").read_text(encoding="utf-8")
    assert '("Candidates", candidates_page, "candidates", False)' in source
    assert '("Data Health", data_health_page, "data-health", False)' in source
    assert 'host = os.environ.get("MP_HOST") or "127.0.0.1"' in source

