"""Tests for oura.py — sleep period selection and Oura end_date semantics."""

from datetime import date

import oura


class _FakeResponse:
    status_code = 200

    def __init__(self, days):
        self._days = days

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": [{"day": d} for d in self._days]}


def _period(day, total, hrv=None, lowest_hr=None, avg_hr=None, deep=None, rem=None,
            type_="long_sleep"):
    return {
        "day": day,
        "type": type_,
        "total_sleep_duration": total,
        "average_hrv": hrv,
        "lowest_heart_rate": lowest_hr,
        "average_heart_rate": avg_hr,
        "deep_sleep_duration": deep,
        "rem_sleep_duration": rem,
    }


class TestEndDateSemantics:
    """Oura v2 end_date is inclusive for daily_sleep/daily_readiness but exclusive
    for sleep/daily_activity (verified against the live API 2026-07-31). _fetch()
    therefore always sends end_date + 1 day, while has_fresh_sleep_data() — which
    hits the inclusive daily_sleep — sends the target date unchanged.
    """

    def _capture(self, monkeypatch, days=()):
        calls = []

        def fake_get(url, headers=None, params=None, timeout=None):
            calls.append((url, params))
            return _FakeResponse(days)

        monkeypatch.setattr(oura.requests, "get", fake_get)
        return calls

    def test_fetch_sends_end_date_plus_one_day(self, monkeypatch, tmp_path):
        monkeypatch.setattr(oura, "OURA_CACHE_DIR", tmp_path)
        calls = self._capture(monkeypatch)

        oura._fetch("sleep", date(2026, 7, 25), date(2026, 7, 28))

        assert calls[0][1] == {"start_date": "2026-07-25", "end_date": "2026-07-29"}

    def test_cache_key_uses_requested_end_date_not_api_end_date(self, monkeypatch, tmp_path):
        monkeypatch.setattr(oura, "OURA_CACHE_DIR", tmp_path)
        self._capture(monkeypatch)

        oura._fetch("sleep", date(2026, 7, 25), date(2026, 7, 28))

        assert (tmp_path / "sleep_2026-07-25_2026-07-28.json").exists()

    def test_freshness_check_sends_single_day_window(self, monkeypatch):
        calls = self._capture(monkeypatch, days=["2026-07-28"])

        assert oura.has_fresh_sleep_data(date(2026, 7, 28)) is True
        url, params = calls[0]
        assert url.endswith("/daily_sleep")
        assert params == {"start_date": "2026-07-28", "end_date": "2026-07-28"}

    def test_freshness_check_false_when_target_day_absent(self, monkeypatch):
        self._capture(monkeypatch, days=["2026-07-27"])

        assert oura.has_fresh_sleep_data(date(2026, 7, 28)) is False


class TestMainSleepByDay:
    def test_keeps_longest_of_multiple_long_sleeps(self):
        periods = [
            _period("2026-07-20", 28800, hrv=60),
            _period("2026-07-20", 3600, hrv=20),
        ]
        assert oura._main_sleep_by_day(periods)["2026-07-20"]["average_hrv"] == 60

    def test_order_independent(self):
        short_first = [
            _period("2026-07-20", 3600, hrv=20),
            _period("2026-07-20", 28800, hrv=60),
        ]
        assert oura._main_sleep_by_day(short_first)["2026-07-20"]["average_hrv"] == 60

    def test_ignores_naps(self):
        periods = [
            _period("2026-07-20", 28800, hrv=60),
            _period("2026-07-20", 36000, hrv=20, type_="sleep"),
        ]
        assert oura._main_sleep_by_day(periods)["2026-07-20"]["average_hrv"] == 60

    def test_skips_entries_without_day(self):
        assert oura._main_sleep_by_day([_period(None, 28800)]) == {}

    def test_missing_duration_treated_as_zero(self):
        periods = [
            _period("2026-07-20", None, hrv=20),
            _period("2026-07-20", 28800, hrv=60),
        ]
        assert oura._main_sleep_by_day(periods)["2026-07-20"]["average_hrv"] == 60

    def test_missing_duration_on_second_entry_does_not_overwrite(self):
        periods = [
            _period("2026-07-20", 28800, hrv=60),
            _period("2026-07-20", None, hrv=20),
        ]
        assert oura._main_sleep_by_day(periods)["2026-07-20"]["average_hrv"] == 60


class TestGetHrvRhr:
    def test_uses_longest_sleep_not_last(self, monkeypatch):
        periods = [
            _period("2026-07-20", 28800, hrv=60, lowest_hr=48, avg_hr=55),
            _period("2026-07-20", 3600, hrv=20, lowest_hr=70, avg_hr=78),
        ]
        monkeypatch.setattr(oura, "get_sleep_periods", lambda *a, **kw: periods)

        result = oura.get_hrv_rhr(days=7)
        assert result == [
            {"day": "2026-07-20", "avg_hrv": 60, "lowest_hr": 48, "avg_hr": 55}
        ]

    def test_sorted_by_day(self, monkeypatch):
        periods = [
            _period("2026-07-21", 28800, hrv=61),
            _period("2026-07-19", 28800, hrv=59),
            _period("2026-07-20", 28800, hrv=60),
        ]
        monkeypatch.setattr(oura, "get_sleep_periods", lambda *a, **kw: periods)

        days = [r["day"] for r in oura.get_hrv_rhr(days=7)]
        assert days == ["2026-07-19", "2026-07-20", "2026-07-21"]


class TestGetSleepDurations:
    def test_uses_longest_sleep(self, monkeypatch):
        periods = [
            _period("2026-07-20", 28800, deep=5400, rem=6000),
            _period("2026-07-20", 3600, deep=600, rem=300),
        ]
        monkeypatch.setattr(oura, "get_sleep_periods", lambda *a, **kw: periods)

        assert oura.get_sleep_durations(days=7) == [
            {
                "day": "2026-07-20",
                "deep_sleep_sec": 5400,
                "rem_sleep_sec": 6000,
                "total_sleep_sec": 28800,
            }
        ]

    def test_agrees_with_hrv_on_same_period(self, monkeypatch):
        """Both getters must pick the same period, so metrics stay consistent."""
        periods = [
            _period("2026-07-20", 3600, hrv=20, deep=600, rem=300),
            _period("2026-07-20", 28800, hrv=60, deep=5400, rem=6000),
        ]
        monkeypatch.setattr(oura, "get_sleep_periods", lambda *a, **kw: periods)

        assert oura.get_hrv_rhr(days=7)[0]["avg_hrv"] == 60
        assert oura.get_sleep_durations(days=7)[0]["total_sleep_sec"] == 28800
