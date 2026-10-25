"""Verify direct-upload file counting and rejection paths."""

from pathlib import Path

from package_audit import audit


def test_manifest_limits(tmp_path):
    """Accept actual files and reject links, duplicates and missing paths."""
    report = tmp_path / 'report.pdf'
    report.write_bytes(b'report')
    assert audit([str(report)])['status'] == 'PASS'
    assert audit([str(report)] * 11)['status'] == 'FAIL'
    assert audit(['https://example.com/report.pdf'])['status'] == 'FAIL'
    assert audit([str(Path(tmp_path / 'missing'))])['status'] == 'FAIL'
