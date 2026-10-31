"""Tests for baselines.py — personal baseline computation and abnormality."""

import pytest

from baselines import compute_baseline, deviation, is_abnormal, describe


def _series(mean, spread, n=20):
    """Alternating values around a mean, deterministic."""
    return [mean + (spread if i % 2 else -spread) for i in range(n)]


class TestComputeBaseline:
    def test_returns_mean_sd_n(self):
        b = compute_baseline(_series(50, 5, n=20))
        assert b["n"] == 20
        assert b["mean"] == pytest.approx(50)
        assert b["sd"] == pytest.approx(5, rel=0.05)

    def test_ignores_nones(self):
        values = _series(50, 5, n=20) + [None, None]
        assert compute_baseline(values)["n"] == 20

    def test_too_few_samples_returns_none(self):
        assert compute_baseline(_series(50, 5, n=13)) is None

    def test_empty_and_none_input(self):
        assert compute_baseline([]) is None
        assert compute_baseline(None) is None

    def test_min_samples_env_override(self, monkeypatch):
        monkeypatch.setenv("BASELINE_MIN_SAMPLES", "5")
        assert compute_baseline(_series(50, 5, n=6)) is not None


class TestIsAbnormal:
    def setup_method(self):
        self.baseline = {"mean": 50.0, "sd": 4.0, "n": 30}

    def test_low_direction_flags_low_values(self):
        abnormal, z = is_abnormal(40, self.baseline, direction="low")
        assert abnormal
        assert z == pytest.approx(-2.5)

    def test_low_direction_ignores_high_values(self):
        abnormal, _ = is_abnormal(65, self.baseline, direction="low")
        assert not abnormal

    def test_high_direction_flags_high_values(self):
        abnormal, z = is_abnormal(60, self.baseline, direction="high")
        assert abnormal
        assert z == pytest.approx(2.5)

    def test_high_direction_ignores_low_values(self):
        abnormal, _ = is_abnormal(38, self.baseline, direction="high")
        assert not abnormal

    def test_both_direction_flags_either_side(self):
        assert is_abnormal(60, self.baseline, direction="both")[0]
        assert is_abnormal(40, self.baseline, direction="both")[0]
        assert not is_abnormal(52, self.baseline, direction="both")[0]

    def test_within_threshold_not_abnormal(self):
        # 1.75 SD default → 50 ± 7 is the boundary
        assert not is_abnormal(44, self.baseline, direction="low")[0]

    def test_sd_threshold_env_override(self, monkeypatch):
        monkeypatch.setenv("BASELINE_SD_THRESHOLD", "1.0")
        assert is_abnormal(45, self.baseline, direction="low")[0]

    def test_no_baseline_returns_false(self):
        assert is_abnormal(40, None, direction="low") == (False, None)

    def test_zero_sd_returns_false(self):
        flat = {"mean": 50.0, "sd": 0.0, "n": 30}
        assert is_abnormal(40, flat, direction="low") == (False, None)

    def test_none_value_returns_false(self):
        assert is_abnormal(None, self.baseline) == (False, None)


class TestHelpers:
    def test_deviation(self):
        assert deviation(58, {"mean": 50.0, "sd": 4.0, "n": 30}) == pytest.approx(2.0)

    def test_describe(self):
        assert describe({"mean": 48.4, "sd": 6.6, "n": 30}, unit="ms") == "48 ± 7 ms"
        assert describe({"mean": 187.46, "sd": 1.24, "n": 30}, decimals=1) == "187.5 ± 1.2"
