"""Manifest validation and prepared-session discovery."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
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


def discover_prepared_sessions(downloads_dir: Path) -> list[Manifest]:
    manifests = []
    for path in sorted(Path(downloads_dir).glob("*/manifest.json")):
        manifest = read_manifest(path)
        if manifest.status == "validated":
            manifests.append(manifest)
    return sorted(manifests, key=lambda item: item.trading_date)
