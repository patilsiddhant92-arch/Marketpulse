from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from App.api import server
from App.api.server import app, validate_symbol


@pytest.mark.parametrize("raw,expected", [("reliance", "RELIANCE"), (" M&M ", "M&M"), ("BAJAJ-AUTO", "BAJAJ-AUTO")])
def test_validate_symbol_accepts_nse_symbols(raw, expected):
    assert validate_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["X'; COPY (SELECT 1) TO 'C:/x.csv'; --", "A B", "", "A" * 21, "SYM;"])
def test_validate_symbol_rejects_injection(raw):
    with pytest.raises(HTTPException) as exc:
        validate_symbol(raw)
    assert exc.value.status_code == 422


def test_momentum_debug_symbol_injection_is_rejected():
    client = TestClient(app)
    resp = client.get("/api/screener/momentum", params={"debug_symbol": "X' OR '1'='1"})
    assert resp.status_code == 422


def _preflight(origin: str):
    # Preflight is answered by the CORS middleware itself, so no DB access is needed (safe in CI).
    return TestClient(app).options(
        "/api/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )


def test_cors_does_not_allow_arbitrary_origins():
    assert _preflight("http://evil.example").headers.get("access-control-allow-origin") is None


def test_cors_allows_vite_dev_origin():
    resp = _preflight("http://127.0.0.1:5173")
    assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
