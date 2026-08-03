import hashlib
import json


def test_manifest_reader_validates_checksums(tmp_path):
    from Scripts.ingestion_manifest import read_manifest

    report = tmp_path / "sec_bhavdata_full_030826.csv"
    report.write_text("DATE1,SYMBOL\n03-Aug-2026,AAA\n", encoding="utf-8")
    checksum = hashlib.sha256(report.read_bytes()).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"schema_version": 1, "trading_date": "2026-08-03", "status": "validated", "reports": [{"report_type": "bhavcopy", "filename": report.name, "sha256": checksum, "validation_status": "validated"}]}), encoding="utf-8")

    manifest = read_manifest(manifest_path)
    assert manifest.status == "validated"
    assert manifest.reports[0].sha256 == checksum


def test_manifest_reader_rejects_changed_file(tmp_path):
    from Scripts.ingestion_manifest import read_manifest

    report = tmp_path / "bulk.csv"
    report.write_text("old", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"schema_version": 1, "trading_date": "2026-08-03", "status": "validated", "reports": [{"report_type": "bulk", "filename": report.name, "sha256": "bad", "validation_status": "validated"}]}), encoding="utf-8")

    try:
        read_manifest(manifest_path)
    except ValueError as exc:
        assert "checksum" in str(exc).lower()
    else:
        raise AssertionError("changed manifest file was accepted")
