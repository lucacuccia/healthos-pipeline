"""Tests for monitor.py checks and correlate.py recovery status (numeric API)."""

from datetime import date, timedelta

from correlate import recovery_status, recovery_score
from monitor import (
    _check_hrv,
    _check_missed_workouts,
    _check_recovery,
    _check_rhr,
    _check_sleep,
    _check_weight,
    _get_thresholds,
)


def _days_ago(n):
    return str(date.today() - timedelta(days=n))


THRESHOLDS = {
    "sleep_score_low": 65,
    "hrv_drop": 15,
    "rhr_spike": 5,
    "recovery_low": 40,
    "missed_workouts_days": 5,
    "weight_change_lbs": 3.0,
}


class TestRecoveryStatus:
    def _readiness(self, score, low=None, trend=None):
        return {
            "avg_score": score,
            "low_contributors": low or {},
            "trend": trend,
        }

    def test_readiness_primary_returns_numeric_and_text(self):
        status = recovery_status(readiness_analysis=self._readiness(85))
        assert status["score"] == 85
        assert "Readiness: 85/100" in status["text"]

    def test_low_contributors_named_in_copy(self):
        status = recovery_status(
            readiness_analysis=self._readiness(65, low={"hrv_balance": 55})
        )
        assert "hrv balance" in status["text"]

    def test_legacy_fallback_when_no_readiness(self):
        sleep = {"avg_score": 80}
        heart = {"hrv_trend": 0.0, "rhr_trend": 0.0}
        status = recovery_status(None, sleep, heart)
        assert status["score"] == 80  # 8/10 rescaled to 0-100
        assert "Recovery:" in status["text"]

    def test_none_when_nothing_available(self):
        assert recovery_status(None, None, None) is None
        assert recovery_status({"error": "x"}, {"error": "x"}, {"error": "x"}) is None

    def test_recovery_score_wrapper_returns_text(self):
        text = recovery_score(None, None, readiness_analysis=self._readiness(85))
        assert isinstance(text, str)
        assert "85/100" in text


class TestCheckRecovery:
    def test_numeric_threshold_no_string_parsing(self):
        readiness = [{"day": _days_ago(1), "score": 30, "contributors": {}}]
        result = _check_recovery(None, None, THRESHOLDS, readiness_data=readiness)
        assert result is not None
        assert result[0] == "recovery_low"
        assert "30/100" in result[1]

    def test_no_alert_when_recovered(self):
        readiness = [{"day": _days_ago(1), "score": 85, "contributors": {}}]
        assert _check_recovery(None, None, THRESHOLDS, readiness_data=readiness) is None

    def test_default_threshold_is_0_100_scale(self):
        assert _get_thresholds()["recovery_low"] == 40


class TestBaselineChecks:
    BASELINES = {
        "sleep_score": {"mean": 82.0, "sd": 4.0, "n": 30},
        "hrv": {"mean": 48.0, "sd": 6.0, "n": 30},
        "rhr": {"mean": 52.0, "sd": 3.0, "n": 30},
        "weight": {"mean": 187.0, "sd": 1.0, "n": 30},
    }

    def test_sleep_uses_personal_baseline(self):
        # 72 passes the fixed threshold (65) but is > 2 SD below the 82 ± 4 norm
        data = [{"day": _days_ago(1), "score": 72}]
        result = _check_sleep(data, THRESHOLDS, self.BASELINES)
        assert result is not None
        assert "60-day norm" in result[1]

    def test_sleep_within_norm_no_alert(self):
        data = [{"day": _days_ago(1), "score": 78}]
        assert _check_sleep(data, THRESHOLDS, self.BASELINES) is None

    def test_sleep_falls_back_to_constant(self):
        data = [{"day": _days_ago(1), "score": 60}]
        result = _check_sleep(data, THRESHOLDS, baselines={})
        assert result is not None
        assert "threshold" in result[1]

    def test_hrv_personal_baseline(self):
        data = [{"day": _days_ago(1), "avg_hrv": 34, "lowest_hr": 52}]
        result = _check_hrv(data, THRESHOLDS, self.BASELINES)
        assert result is not None
        assert "60-day norm" in result[1]

    def test_hrv_fallback_needs_window(self):
        # Without a baseline the old windowed logic needs >= 3 entries
        data = [{"day": _days_ago(1), "avg_hrv": 34, "lowest_hr": 52}]
        assert _check_hrv(data, THRESHOLDS, baselines={}) is None

    def test_rhr_personal_baseline(self):
        data = [{"day": _days_ago(1), "avg_hrv": 48, "lowest_hr": 60}]
        result = _check_rhr(data, THRESHOLDS, self.BASELINES)
        assert result is not None
        assert "60-day norm" in result[1]

    def test_weight_personal_baseline_both_directions(self):
        entries = [{"date": _days_ago(1), "weight": 190.0}]
        result = _check_weight(entries, THRESHOLDS, self.BASELINES)
        assert result is not None
        assert "up" in result[1]

        entries = [{"date": _days_ago(1), "weight": 169.0}]
        result = _check_weight(entries, THRESHOLDS, self.BASELINES)
        assert result is not None
        assert "down" in result[1]

    def test_weight_fallback_uses_delta(self):
        entries = [
            {"date": _days_ago(7), "weight": 185.0},
            {"date": _days_ago(1), "weight": 189.0},
        ]
        result = _check_weight(entries, THRESHOLDS, baselines={})
        assert result is not None
        assert "threshold" in result[1]


class TestMissedWorkouts:
    def test_fetch_failure_sends_unreachable_alert_not_missing_data(self):
        # workouts=None because the fetch raised — must not be reported as
        # "no workouts found" (#69).
        result = _check_missed_workouts(None, THRESHOLDS, fetch_failed=True)
        assert result is not None
        key, message = result
        assert key == "workout_source_unreachable"
        assert "unreachable" in message.lower()

    def test_no_data_without_fetch_failure_reports_missing(self, monkeypatch):
        monkeypatch.delenv("WORKOUT_SOURCE", raising=False)
        result = _check_missed_workouts(None, THRESHOLDS, fetch_failed=False)
        assert result is not None
        assert result[0] == "missed_workouts"

    def test_recent_workout_no_alert(self):
        workouts = [{"date": _days_ago(1)}]
        assert _check_missed_workouts(workouts, THRESHOLDS, fetch_failed=False) is None

    def test_stale_workout_alerts(self):
        workouts = [{"date": _days_ago(10)}]
        result = _check_missed_workouts(workouts, THRESHOLDS, fetch_failed=False)
        assert result is not None
        assert result[0] == "missed_workouts"
