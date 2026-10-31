"""Tests for main.run_labs.

Pins that --labs re-parses the Health folder, which is what mirrors blood
test data to Firestore for Cloud Run.
"""

import blood_tests
import main


PARSED = {"date": "2026-10-01", "results": [{"test": "LDL", "value": 90, "unit": "mg/dL", "flag": ""}]}


def _stub(monkeypatch, tmp_path, parsed=PARSED):
    calls = []
    monkeypatch.setattr(main, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(blood_tests, "parse_blood_test_pdf", lambda pdf: parsed)
    monkeypatch.setattr(blood_tests, "parse_all_blood_tests", lambda: calls.append("parse_all") or [])
    monkeypatch.setattr(blood_tests, "explain_results", lambda p: calls.append("explain") or "explanation")
    monkeypatch.setattr(blood_tests, "compare_to_history", lambda p: calls.append("compare") or "")
    return calls


def test_labs_reparses_folder_before_comparing(monkeypatch, tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF")
    calls = _stub(monkeypatch, tmp_path)

    output = main.run_labs(str(pdf))

    assert output == "explanation"
    assert calls.index("parse_all") < calls.index("compare")
    assert (tmp_path / "labs_2026-10-01.md").read_text() == "explanation"


def test_labs_skips_reparse_when_nothing_extracted(monkeypatch, tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF")
    calls = _stub(monkeypatch, tmp_path, parsed={"date": "2026-10-01", "results": []})

    assert main.run_labs(str(pdf)) is None
    assert calls == []
