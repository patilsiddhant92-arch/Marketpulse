from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "Scripts"
APP = ROOT / "App"
for path in (ROOT, SCRIPTS, APP):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _clear_index_history_memo() -> None:
    # index_history is importable both as a top-level module (Scripts/ on sys.path above)
    # and as Scripts.index_history (a namespace package via ROOT on sys.path); each import
    # path gets its own module object with its own _INDEX_HISTORY_CACHE, so both must be
    # cleared or the memo can leak state between tests depending on which name a test used.
    for module_name in ("index_history", "Scripts.index_history"):
        try:
            module = __import__(module_name, fromlist=["clear_index_history_cache"])
        except ImportError:
            continue
        clear = getattr(module, "clear_index_history_cache", None)
        if clear is not None:
            clear()


@pytest.fixture(autouse=True)
def _fresh_index_history_cache():
    _clear_index_history_memo()
    yield
    _clear_index_history_memo()


@pytest.fixture(autouse=True)
def _skip_evidence_step(monkeypatch):
    # The derived step launches the (slow) evidence step as a child process; tests opt in explicitly.
    monkeypatch.setenv("MP_SKIP_EVIDENCE", "1")


@pytest.fixture(autouse=True)
def _skip_research_lab_step(monkeypatch):
    # daily_pipeline's research_lab step (Scripts/research_lab.py) is slow; pipeline tests opt in explicitly.
    monkeypatch.setenv("MP_SKIP_RESEARCH_LAB", "1")
