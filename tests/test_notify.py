"""Tests for notify.py — email retry behavior, subject building, Telegram chunking."""

import smtplib

import pytest

import notify


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)


@pytest.fixture
def gmail_configured(monkeypatch):
    monkeypatch.setattr(notify, "GMAIL_ADDRESS", "test@example.com")
    monkeypatch.setattr(notify, "GMAIL_APP_PASSWORD", "app-password")


class TestSendEmail:
    def test_unconfigured_returns_none(self, monkeypatch):
        monkeypatch.setattr(notify, "GMAIL_ADDRESS", "")
        assert notify.send_email("subject", "body") is None

    def test_success_first_attempt(self, gmail_configured, monkeypatch):
        attempts = []

        class FakeSMTP:
            def __init__(self, *args, **kwargs):
                attempts.append(1)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def login(self, *args):
                pass

            def send_message(self, msg):
                pass

        monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
        assert notify.send_email("subject", "body") is True
        assert len(attempts) == 1

    def test_retries_then_fails(self, gmail_configured, monkeypatch):
        attempts = []

        class BoomSMTP:
            def __init__(self, *args, **kwargs):
                attempts.append(1)
                raise ConnectionError("smtp down")

        monkeypatch.setattr(smtplib, "SMTP_SSL", BoomSMTP)
        assert notify.send_email("subject", "body") is False
        assert len(attempts) == 3

    def test_succeeds_on_second_attempt(self, gmail_configured, monkeypatch):
        attempts = []

        class FlakySMTP:
            def __init__(self, *args, **kwargs):
                attempts.append(1)
                if len(attempts) == 1:
                    raise ConnectionError("transient")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def login(self, *args):
                pass

            def send_message(self, msg):
                pass

        monkeypatch.setattr(smtplib, "SMTP_SSL", FlakySMTP)
        assert notify.send_email("subject", "body") is True
        assert len(attempts) == 2


class TestBuildEmailSubject:
    def test_daily_subject_extracts_metrics(self):
        report = (
            "# Daily Snapshot\n"
            "- **Average Score:** 85\n"
            "- **Avg HRV:** 45 ms\n"
            "- **Avg Resting HR:** 52 bpm\n"
        )
        subject = notify._build_email_subject(report)
        assert "Sleep 85" in subject
        assert "HRV 45ms" in subject
        assert "RHR 52" in subject

    def test_flag_count_in_subject(self):
        report = "# Daily Snapshot\n⚠️ low sleep\n⚠️ low HRV\n"
        subject = notify._build_email_subject(report)
        assert "2 flags" in subject

    def test_weekly_fallback_subject(self):
        subject = notify._build_email_subject("# Weekly Report\nnothing parseable")
        assert "Weekly" in subject


class TestSendTelegramChunking:
    @pytest.fixture
    def telegram_configured(self, monkeypatch):
        monkeypatch.setattr(notify, "TELEGRAM_BOT_TOKEN", "token")
        monkeypatch.setattr(notify, "TELEGRAM_CHAT_ID", "123")

    def test_unconfigured_returns_false(self, monkeypatch):
        monkeypatch.setattr(notify, "TELEGRAM_BOT_TOKEN", "")
        assert notify.send_telegram("hi") is False

    def test_short_message_single_post(self, telegram_configured, monkeypatch):
        posts = []

        def fake_post(url, json=None, timeout=None):
            posts.append(json)

            class Resp:
                ok = True

            return Resp()

        monkeypatch.setattr(notify.requests, "post", fake_post)
        assert notify.send_telegram("hello") is True
        assert len(posts) == 1
        assert posts[0]["text"] == "hello"

    def test_long_message_chunked_under_limit(self, telegram_configured, monkeypatch):
        posts = []

        def fake_post(url, json=None, timeout=None):
            posts.append(json)

            class Resp:
                ok = True

            return Resp()

        monkeypatch.setattr(notify.requests, "post", fake_post)
        message = "\n".join(f"line {i} " + "x" * 80 for i in range(100))
        assert len(message) > 4096

        assert notify.send_telegram(message) is True
        assert len(posts) > 1
        for p in posts:
            assert len(p["text"]) <= 4096
