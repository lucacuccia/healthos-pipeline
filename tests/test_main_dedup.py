"""Tests for main.py report dedup and delivery fail-safes.

Pins the failure directions: a Firestore error must never silently eat or
double-send a report without an alert, and a failed email must leave the
report unlogged so a retry trigger resends it.
"""

from datetime import date

import pytest

import firestore_client
import main
import notify


class FakeDoc:
    def __init__(self, exists, data=None):
        self.exists = exists
        self._data = data or {}

    def to_dict(self):
        return self._data


class FakeFirestore:
    """Minimal collection().document().get() chain."""

    def __init__(self, doc):
        self._doc = doc

    def collection(self, name):
        return self

    def document(self, name):
        return self

    def get(self):
        return self._doc


@pytest.fixture
def alerts(monkeypatch):
    """Capture Telegram alerts instead of sending them."""
    sent = []
    monkeypatch.setattr(notify, "send_telegram", lambda msg: sent.append(msg) or True)
    return sent


@pytest.fixture
def reports_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "REPORTS_DIR", tmp_path)
    return tmp_path


class TestAlreadyReported:
    def test_local_report_file_wins(self, reports_dir):
        (reports_dir / f"daily_{date.today()}.md").write_text("x")
        assert main.already_reported("daily") is True

    def test_firestore_doc_marked_sent(self, reports_dir, monkeypatch):
        fake = FakeFirestore(FakeDoc(True, {"daily": True}))
        monkeypatch.setattr(firestore_client, "_get_client", lambda: fake)
        assert main.already_reported("daily") is True

    def test_firestore_doc_not_sent(self, reports_dir, monkeypatch):
        fake = FakeFirestore(FakeDoc(True, {"weekly": True}))
        monkeypatch.setattr(firestore_client, "_get_client", lambda: fake)
        assert main.already_reported("daily") is False

    def test_no_doc_means_not_reported(self, reports_dir, monkeypatch):
        fake = FakeFirestore(FakeDoc(False))
        monkeypatch.setattr(firestore_client, "_get_client", lambda: fake)
        assert main.already_reported("daily") is False

    def test_firestore_error_fails_safe_and_alerts(self, reports_dir, monkeypatch, alerts):
        def boom():
            raise ConnectionError("firestore down")
        monkeypatch.setattr(firestore_client, "_get_client", boom)
        assert main.already_reported("daily") is True  # skip to avoid duplicates
        assert len(alerts) == 1
        assert "Firestore" in alerts[0]


class TestClaimReportSlot:
    def test_firestore_error_fails_open_and_alerts(self, monkeypatch, alerts):
        def boom():
            raise ConnectionError("firestore down")
        monkeypatch.setattr(firestore_client, "_get_client", boom)
        assert main.claim_report_slot("daily") is True  # proceed anyway
        assert len(alerts) == 1
        assert "Firestore" in alerts[0]


class TestDeliverAndLog:
    def test_email_failure_returns_none_and_alerts(self, reports_dir, monkeypatch, alerts):
        monkeypatch.setattr(
            notify, "deliver_report", lambda r: {"telegram": None, "email": False}
        )
        firestore_writes = []
        monkeypatch.setattr(
            firestore_client, "_get_client",
            lambda: firestore_writes.append(1) or FakeFirestore(FakeDoc(False)),
        )

        result = main._deliver_and_log("daily", "# Report")

        assert result is None
        assert len(alerts) == 1
        assert "email delivery" in alerts[0]
        assert not list(reports_dir.iterdir())  # report not saved
        assert firestore_writes == []  # report not logged

    def test_email_unconfigured_still_logs(self, reports_dir, monkeypatch, alerts):
        """email=None means Gmail isn't set up — an intentional skip, not a failure."""
        import sheets
        monkeypatch.setattr(
            notify, "deliver_report", lambda r: {"telegram": None, "email": None}
        )
        monkeypatch.setattr(sheets, "log_report_to_sheets", lambda *a, **k: None)

        class WriteRecorder(FakeFirestore):
            def __init__(self):
                super().__init__(FakeDoc(False))
                self.writes = []

            def set(self, payload, merge=False):
                self.writes.append(payload)

        recorder = WriteRecorder()
        monkeypatch.setattr(firestore_client, "_get_client", lambda: recorder)

        result = main._deliver_and_log("daily", "# Report")

        assert result == "# Report"
        assert alerts == []
        assert (reports_dir / f"daily_{date.today()}.md").exists()
        assert any("daily" in w for w in recorder.writes)

    def test_email_success_saves_and_logs(self, reports_dir, monkeypatch, alerts):
        import sheets
        monkeypatch.setattr(
            notify, "deliver_report", lambda r: {"telegram": None, "email": True}
        )
        sheet_logs = []
        monkeypatch.setattr(
            sheets, "log_report_to_sheets", lambda *a, **k: sheet_logs.append(a)
        )
        monkeypatch.setattr(
            firestore_client, "_get_client", lambda: FakeFirestore(FakeDoc(False))
        )
        # FakeFirestore has no .set(); the Firestore log failure must be non-fatal
        result = main._deliver_and_log("daily", "# Report")

        assert result == "# Report"
        assert alerts == []
        assert (reports_dir / f"daily_{date.today()}.md").exists()
        assert len(sheet_logs) == 1
