"""Manifest validation and prepared-session discovery."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class ReportRecord:
    report_type: str
    filename: str
    sha256: str
    validation_status: str


@dataclass(frozen=True)
class Manifest:
    path: Path
    schema_version: int
    trading_date: str
    status: str
    reports: tuple[ReportRecord, ...]


@dataclass
class SessionPlan:
    trading_dates: list[str]
    rows_by_table: dict[str, list[dict]] = field(default_factory=dict)
    inject_failure: bool = False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path) -> Manifest:
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("unsupported manifest schema version")
    status = str(payload.get("status", "incomplete"))
    reports = []
    for item in payload.get("reports", []):
        record = ReportRecord(str(item["report_type"]), str(item["filename"]), str(item.get("sha256", "")), str(item.get("validation_status", "incomplete")))
        report_path = path.parent / record.filename
        if record.validation_status == "validated":
            if not report_path.exists():
                raise ValueError(f"missing report: {record.filename}")
            if _sha256(report_path) != record.sha256:
                raise ValueError(f"checksum mismatch: {record.filename}")
        reports.append(record)
    return Manifest(path, 1, str(payload["trading_date"]), status, tuple(reports))


def prepare_session_manifest(session_dir: Path, trading_date: date | str, filenames: list[str] | None = None) -> Path:
    """Write a validated checksum manifest after a staged session passes validation."""

    session_dir = Path(session_dir)
    names = filenames or [path.name for path in sorted(session_dir.iterdir()) if path.is_file() and path.name != "manifest.json"]
    reports = []
    for filename in names:
        path = session_dir / filename
        if not path.is_file():
            raise ValueError(f"missing staged report: {filename}")
        reports.append(
            {
                "report_type": path.stem,
                "filename": path.name,
                "sha256": _sha256(path),
                "validation_status": "validated",
            }
        )
    payload = {"schema_version": 1, "trading_date": str(trading_date), "status": "validated", "reports": reports}
    path = session_dir / "manifest.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def validate_session_manifest(path_or_dir: Path) -> Manifest:
    """Read and validate a session manifest, including every report checksum."""

    path = Path(path_or_dir)
    manifest_path = path / "manifest.json" if path.is_dir() else path
    manifest = read_manifest(manifest_path)
    if manifest.status != "validated" or any(item.validation_status != "validated" for item in manifest.reports):
        raise ValueError("session manifest is not validated")
    return manifest


def discover_prepared_sessions(downloads_dir: Path) -> list[Manifest]:
    manifests = []
    for path in sorted(Path(downloads_dir).glob("*/manifest.json")):
        manifest = read_manifest(path)
        if manifest.status == "validated":
            manifests.append(manifest)
    return sorted(manifests, key=lambda item: item.trading_date)
