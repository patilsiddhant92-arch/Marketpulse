from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from App.api.server import SPAStaticFiles


def _client(tmp_path) -> TestClient:
    (tmp_path / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "main.js").write_text("console.log(1)", encoding="utf-8")
    app = FastAPI()
    app.mount("/", SPAStaticFiles(directory=str(tmp_path), html=True), name="static")
    return TestClient(app)


def test_client_routes_fall_back_to_index(tmp_path):
    client = _client(tmp_path)
    for path in ("/groups", "/stock/HEG", "/research?rview=analogs"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "app" in resp.text


def test_real_files_and_api_404s_are_untouched(tmp_path):
    client = _client(tmp_path)
    assert client.get("/assets/main.js").text == "console.log(1)"
    assert client.get("/api/v2/nope").status_code == 404
