"""Unit tests for analyze.py trend, flag, and report-assembly logic."""

from datetime import date, timedelta

import pytest

from analyze import (
    _fmt_duration,
    _fmt_pct,
    _pct_change,
    _slope_per_week,
    analyze_activity,
    analyze_exercise,
    analyze_heart_metrics,
    analyze_readiness,
    analyze_sleep,
    analyze_weight,
    generate_report,
)


def _days_ago(n):
    return str(date.today() - timedelta(days=n))


class TestFormatHelpers:
    def test_fmt_duration(self):
        assert _fmt_duration(7 * 3600 + 30 * 60) == "7h 30m"
        assert _fmt_duration(3600) == "1h 00m"
        assert _fmt_duration(None) == "—"

    def test_pct_change(self):
        assert _pct_change(110, 100) == 10
        assert _pct_change(90, 100) == -10
        assert _pct_change(100, 0) is None
        assert _pct_change(None, 100) is None

    def test_fmt_pct(self):
        assert _fmt_pct(5) == "+5%"
        assert _fmt_pct(-3) == "-3%"
        assert _fmt_pct(None) == "—"


class TestAnalyzeSleep:
    def test_empty_input_returns_error(self):
        assert "error" in analyze_sleep([])
        assert "error" in analyze_sleep(None)

    def test_daily_trend_is_last_minus_previous(self):
        data = [
            {"day": _days_ago(2), "score": 70},
            {"day": _days_ago(1), "score": 80},
        ]
        result = analyze_sleep(data)
        assert result["avg_score"] == 75.0
        assert result["trend"] == 10.0

    def test_low_score_flag(self):
        data = [{"day": _days_ago(1), "score": 60}]
        result = analyze_sleep(data)
        assert any("low" in f for f in result["flags"])

    def test_no_flag_for_good_score(self):
        data = [{"day": _days_ago(1), "score": 85}]
        result = analyze_sleep(data)
        assert result["flags"] == []

    def test_weekly_trend_compares_week_averages(self):
        data = (
            [{"day": _days_ago(d), "score": 70} for d in range(8, 14)]
            + [{"day": _days_ago(d), "score": 80} for d in range(1, 7)]
        )
        result = analyze_sleep(data, weekly=True)
        assert result["avg_score"] == 80.0
        assert result["trend"] == 10.0

    def test_low_deep_sleep_flag(self):
        data = [{"day": _days_ago(1), "score": 85}]
        durations = [{
            "day": _days_ago(1),
            "deep_sleep_sec": 1800,  # 30m < 1h threshold
            "rem_sleep_sec": 5400,
            "total_sleep_sec": 25200,
        }]
        result = analyze_sleep(data, sleep_durations=durations)
        assert any("deep sleep" in f.lower() for f in result["flags"])
        assert result["avg_deep_sleep"] == "0h 30m"


class TestAnalyzeWeight:
    def test_empty_input_returns_error(self):
        assert "error" in analyze_weight([])

    def test_gaining_direction(self):
        entries = [
            {"date": date.today() - timedelta(days=14), "weight": 185.0},
            {"date": date.today(), "weight": 188.0},
        ]
        result = analyze_weight(entries)
        assert result["direction"] == "gaining"
        assert result["current"] == 188.0
        assert result["rate_per_week"] == 1.5

    def test_losing_direction(self):
        entries = [
            {"date": date.today() - timedelta(days=7), "weight": 188.0},
            {"date": date.today(), "weight": 185.0},
        ]
        assert analyze_weight(entries)["direction"] == "losing"

    def test_stable_within_one_pound(self):
        entries = [
            {"date": date.today() - timedelta(days=7), "weight": 185.0},
            {"date": date.today(), "weight": 185.5},
        ]
        assert analyze_weight(entries)["direction"] == "stable"

    def test_single_entry_insufficient(self):
        entries = [{"date": date.today(), "weight": 185.0}]
        result = analyze_weight(entries)
        assert result["direction"] == "insufficient data"
        assert result["rate_per_week"] is None


def _workout(days_ago, exercise, weight):
    return {
        "date": date.today() - timedelta(days=days_ago),
        "exercise": exercise,
        "weight": weight,
        "sets": 3,
        "reps": 10,
        "volume": 3 * 10 * weight,
    }


class TestAnalyzeExercise:
    def test_empty_input_returns_error(self):
        assert "error" in analyze_exercise([])

    def test_week_over_week_delta(self):
        workouts = [_workout(9, "OHP", 50), _workout(3, "OHP", 55)]
        prog = analyze_exercise(workouts)["progression"]["OHP"]
        assert prog["weight_delta"] == 5
        assert prog["within_week_delta"] is None

    def test_within_week_delta_for_new_exercise(self):
        workouts = [_workout(6, "Squat", 100), _workout(2, "Squat", 110)]
        prog = analyze_exercise(workouts)["progression"]["Squat"]
        assert prog["weight_delta"] is None
        assert prog["within_week_delta"] == 10
        assert prog["week_first_weight"] == 100
        assert prog["week_last_weight"] == 110

    def test_within_week_delta_when_max_matches_last_week(self):
        # Max unchanged vs last week (35 both weeks), but mid-week bump 30 -> 35
        workouts = [
            _workout(10, "Bench", 35),
            _workout(5, "Bench", 30),
            _workout(1, "Bench", 35),
        ]
        prog = analyze_exercise(workouts)["progression"]["Bench"]
        assert prog["weight_delta"] == 0
        assert prog["within_week_delta"] == 5

    def test_no_deltas_when_weight_unchanged(self):
        workouts = [_workout(8, "Row", 60), _workout(4, "Row", 60), _workout(2, "Row", 60)]
        prog = analyze_exercise(workouts)["progression"]["Row"]
        assert prog["weight_delta"] == 0
        assert prog["within_week_delta"] == 0


class TestGenerateReport:
    def test_all_empty_inputs_still_renders(self):
        report, metadata = generate_report(report_type="daily")
        assert isinstance(report, str)
        assert len(report) > 0
        assert isinstance(metadata, dict)

    def test_daily_report_with_sleep_data(self):
        sleep = [
            {"day": _days_ago(2), "score": 70},
            {"day": _days_ago(1), "score": 80},
        ]
        report, metadata = generate_report(sleep_data=sleep, report_type="daily")
        assert "80" in report or "75" in report
        assert metadata["sleep"]["avg_score"] == 75.0

    def test_weekly_report_renders_weekly_sections(self):
        sleep = [{"day": _days_ago(1), "score": 80}]
        report, _ = generate_report(
            sleep_data=sleep,
            report_type="weekly",
            start_date=date.today() - timedelta(days=7),
            end_date=date.today(),
        )
        assert isinstance(report, str)
        assert len(report) > 0

    def test_exercise_section_reports_in_week_weight_changes(self):
        workouts = [
            _workout(6, "Squat", 100),   # new this week, in-week 100 -> 110
            _workout(2, "Squat", 110),
            _workout(9, "OHP", 50),      # classic week-over-week 50 -> 55
            _workout(3, "OHP", 55),
            _workout(8, "Row", 60),      # unchanged — must stay out of the table
            _workout(4, "Row", 60),
        ]
        report, _ = generate_report(workouts=workouts, report_type="weekly")
        exercise_section = report.split("## Exercise")[1].split("\n## ")[0]
        assert "Weight Progression" in exercise_section
        assert "| Squat | 2 | 100 → 110 | ↑ 10 lbs (in-week) |" in exercise_section
        assert "| OHP | 1 | 50 → 55 | ↑ 5 lbs |" in exercise_section
        assert "Row" not in exercise_section

    def test_exercise_section_no_changes_message(self):
        workouts = [_workout(8, "Row", 60), _workout(4, "Row", 60)]
        report, _ = generate_report(workouts=workouts, report_type="weekly")
        assert "No weight changes vs last week" in report


class TestSlopePerWeek:
    def test_noisy_endpoint_does_not_flip_direction(self):
        # Steadily losing ~0.7 lb/wk, but the final reading spikes up. The old
        # first-vs-last math called this "stable/gaining"; regression sees the loss.
        entries = [
            {"date": date.today() - timedelta(days=13 - i), "weight": w}
            for i, w in enumerate(
                [189.0, 188.8, 188.9, 188.6, 188.5, 188.4, 188.2,
                 188.1, 187.9, 187.8, 187.6, 187.5, 187.4, 189.1]
            )
        ]
        result = analyze_weight(entries)
        assert result["direction"] == "losing"
        assert result["rate_per_week"] < 0

    def test_slope_helper_basic(self):
        # 1 lb/day = 7 lbs/week
        points = [(0, 100.0), (1, 101.0), (2, 102.0)]
        assert _slope_per_week(points) == pytest.approx(7.0)

    def test_slope_helper_degenerate(self):
        assert _slope_per_week([(0, 100.0)]) is None
        assert _slope_per_week([(0, 100.0), (0, 101.0)]) is None
        assert _slope_per_week([]) is None


class TestBaselineFlags:
    def _baselines(self):
        return {
            "sleep_score": {"mean": 82.0, "sd": 4.0, "n": 30},
            "hrv": {"mean": 48.0, "sd": 6.0, "n": 30},
            "rhr": {"mean": 52.0, "sd": 3.0, "n": 30},
        }

    def test_sleep_flag_fires_on_personal_deviation(self):
        # 72 is fine by the universal <70 constant, but > 2 SD below this
        # person's 82 ± 4 norm.
        data = [{"day": _days_ago(1), "score": 72}]
        result = analyze_sleep(data, baselines=self._baselines())
        assert any("60-day norm" in f for f in result["flags"])

    def test_sleep_no_flag_within_personal_norm(self):
        data = [{"day": _days_ago(1), "score": 79}]
        result = analyze_sleep(data, baselines=self._baselines())
        assert result["flags"] == []

    def test_sleep_falls_back_to_constant_without_baseline(self):
        data = [{"day": _days_ago(1), "score": 60}]
        result = analyze_sleep(data, baselines={})
        assert any("low" in f for f in result["flags"])

    def test_hrv_flag_personal_vs_universal(self):
        # 34 ms passes the universal <20 constant but is abnormal for a 48 ± 6 norm
        data = [{"day": _days_ago(1), "avg_hrv": 34, "lowest_hr": 52}]
        result = analyze_heart_metrics(data, baselines=self._baselines())
        assert any("HRV" in f and "60-day norm" in f for f in result["flags"])

    def test_rhr_high_flag(self):
        data = [{"day": _days_ago(1), "avg_hrv": 48, "lowest_hr": 60}]
        result = analyze_heart_metrics(data, baselines=self._baselines())
        assert any("resting HR" in f for f in result["flags"])


class TestAnalyzeReadiness:
    def test_empty_input_returns_error(self):
        assert "error" in analyze_readiness([])
        assert "error" in analyze_readiness(None)

    def test_avg_trend_and_contributors(self):
        data = [
            {"day": _days_ago(2), "score": 70,
             "contributors": {"hrv_balance": 60, "recovery_index": 90}},
            {"day": _days_ago(1), "score": 80,
             "contributors": {"hrv_balance": 64, "recovery_index": 92}},
        ]
        result = analyze_readiness(data)
        assert result["avg_score"] == 75.0
        assert result["trend"] == 10.0
        assert result["avg_contributors"]["hrv_balance"] == 62.0
        assert "hrv_balance" in result["low_contributors"]
        assert "recovery_index" not in result["low_contributors"]

    def test_low_readiness_flag(self):
        data = [{"day": _days_ago(1), "score": 55, "contributors": {}}]
        result = analyze_readiness(data)
        assert any("low" in f for f in result["flags"])

    def test_weekly_split(self):
        data = (
            [{"day": _days_ago(d), "score": 60, "contributors": {}} for d in range(8, 14)]
            + [{"day": _days_ago(d), "score": 80, "contributors": {}} for d in range(1, 7)]
        )
        result = analyze_readiness(data, weekly=True)
        assert result["avg_score"] == 80.0
        assert result["trend"] == 20.0


class TestAnalyzeActivity:
    def test_empty_input_returns_error(self):
        assert "error" in analyze_activity([])

    def test_averages_and_trend(self):
        data = [
            {"day": _days_ago(2), "score": 80, "steps": 8000, "active_calories": 400},
            {"day": _days_ago(1), "score": 90, "steps": 12000, "active_calories": 600},
        ]
        result = analyze_activity(data)
        assert result["avg_steps"] == 10000
        assert result["avg_active_calories"] == 500
        assert result["avg_score"] == 85.0
        assert result["steps_trend"] == 4000

    def test_weekly_trend_compares_week_averages(self):
        data = (
            [{"day": _days_ago(d), "steps": 6000} for d in range(8, 14)]
            + [{"day": _days_ago(d), "steps": 9000} for d in range(1, 7)]
        )
        result = analyze_activity(data, weekly=True)
        assert result["avg_steps"] == 9000
        assert result["steps_trend"] == 3000

    def test_daily_excludes_todays_partial_steps(self):
        data = [
            {"day": _days_ago(2), "score": 80, "steps": 8000, "active_calories": 400},
            {"day": _days_ago(1), "score": 90, "steps": 12000, "active_calories": 600},
            {"day": _days_ago(0), "score": 10, "steps": 300, "active_calories": 20},
        ]
        result = analyze_activity(data)
        assert result["avg_steps"] == 10000
        assert result["avg_active_calories"] == 500
        assert result["avg_score"] == 85.0
        assert result["steps_trend"] == 4000
        assert [d["day"] for d in result["daily"]] == [_days_ago(2), _days_ago(1)]

    def test_weekly_excludes_todays_partial_steps(self):
        data = (
            [{"day": _days_ago(d), "steps": 6000} for d in range(9, 15)]
            + [{"day": _days_ago(d), "steps": 9000} for d in range(1, 8)]
            + [{"day": _days_ago(0), "steps": 300}]
        )
        result = analyze_activity(data, weekly=True)
        assert result["avg_steps"] == 9000
        assert result["steps_trend"] == 3000
        assert result["days"] == 7
        assert _days_ago(0) not in [d["day"] for d in result["daily"]]

    def test_weekly_keeps_today_when_it_is_the_only_data(self):
        data = [{"day": _days_ago(0), "steps": 300}]
        result = analyze_activity(data, weekly=True)
        assert result["avg_steps"] == 300

    def test_daily_keeps_today_when_it_is_the_only_data(self):
        data = [{"day": _days_ago(0), "steps": 300}]
        result = analyze_activity(data)
        assert result["avg_steps"] == 300


class TestReportNewSections:
    def test_activity_section_renders(self):
        activity = [{"day": _days_ago(1), "score": 90, "steps": 11000, "active_calories": 550}]
        report, metadata = generate_report(
            activity_data=activity, report_type="daily"
        )
        assert "## Activity" in report
        assert "11,000" in report
        assert metadata["activity"]["avg_steps"] == 11000

    def test_readiness_section_never_renders_but_metadata_is_kept(self):
        readiness = [{"day": _days_ago(1), "score": 85, "contributors": {}}]
        for report_type in ("daily", "weekly"):
            report, metadata = generate_report(
                readiness_data=readiness, report_type=report_type
            )
            assert "## Readiness" not in report
            assert metadata["readiness"]["avg_score"] == 85.0

    def test_activity_table_is_most_recent_first(self):
        activity = [
            {"day": _days_ago(3), "score": 80, "steps": 8000, "active_calories": 400},
            {"day": _days_ago(1), "score": 90, "steps": 12000, "active_calories": 600},
            {"day": _days_ago(2), "score": 85, "steps": 10000, "active_calories": 500},
        ]

        report, _ = generate_report(activity_data=activity, report_type="daily")

        activity_rows = [
            line for line in report.splitlines()
            if line.startswith(tuple(f"| {_days_ago(days)} |" for days in (1, 2, 3)))
        ]
        assert activity_rows == [
            f"| {_days_ago(1)} | 12,000 | 600 | 90 |",
            f"| {_days_ago(2)} | 10,000 | 500 | 85 |",
            f"| {_days_ago(3)} | 8,000 | 400 | 80 |",
        ]

    def test_sections_absent_without_data(self):
        report, metadata = generate_report(report_type="weekly")
        assert "## Readiness" not in report
        assert "## Activity" not in report
