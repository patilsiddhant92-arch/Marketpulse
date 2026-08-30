from __future__ import annotations

from pathlib import Path


def test_pull_request_workflow_runs_pytest_and_eod_does_not_commit_input() -> None:
    root = Path(__file__).parents[1]
    test_workflow = root / ".github" / "workflows" / "test.yml"
    eod = (root / ".github" / "workflows" / "eod.yml").read_text(encoding="utf-8")
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")

    assert test_workflow.exists()
    assert "pytest" in test_workflow.read_text(encoding="utf-8")
    assert "compileall" in test_workflow.read_text(encoding="utf-8")
    assert "git add -A Input/" not in eod
    assert "Input/archive/" in gitignore
    assert "Input/downloads/" in gitignore
    assert "Input/daily/" not in gitignore
