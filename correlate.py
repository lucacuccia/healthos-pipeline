"""Health OS — Cross-source correlations and insights.

Connects dots across sleep, HRV, workouts, weight, and blood tests to
surface actionable observations in plain language.
"""

from datetime import date, datetime, timedelta


def _normalize_date(d):
    """Accept date object or 'YYYY-MM-DD' string, return 'YYYY-MM-DD' string."""
    if isinstance(d, date) and not isinstance(d, datetime):
        return d.isoformat()
    if isinstance(d, datetime):
        return d.date().isoformat()
    return str(d)[:10]


def _avg(values):
    """Return average of non-empty numeric list, or None."""
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


# ---------------------------------------------------------------------------
# Correlation functions — each returns str | None
# ---------------------------------------------------------------------------

def recovery_status(readiness_analysis=None, sleep_analysis=None, heart_analysis=None):
    """Recovery as a number plus copy: {"score": int 0-100, "text": str} or None.

    Primary source is Oura's validated readiness score (with contributor-driven
    copy). When readiness is unavailable (non-Oura source), falls back to the
    legacy sleep+HRV+RHR heuristic rescaled to 0-100. monitor.py consumes the
    numeric score directly — never parse it back out of the text.
    """
    if readiness_analysis and not readiness_analysis.get("error"):
        avg = readiness_analysis.get("avg_score")
        if avg is not None:
            score = round(avg)
            parts = []
            if score >= 85:
                parts.append("recovery is strong")
            elif score >= 70:
                parts.append("recovery is on track")
            else:
                parts.append("recovery needs attention")
            low = readiness_analysis.get("low_contributors") or {}
            if low:
                worst = sorted(low.items(), key=lambda kv: kv[1])[:2]
                parts.append(
                    "held back by " + ", ".join(k.replace("_", " ") for k, _ in worst)
                )
            trend = readiness_analysis.get("trend")
            if trend is not None and abs(trend) >= 3:
                parts.append("trending up" if trend > 0 else "trending down")
            return {"score": score, "text": f"Readiness: {score}/100 — {', '.join(parts)}"}

    return _legacy_recovery(sleep_analysis, heart_analysis)


def _legacy_recovery(sleep_analysis, heart_analysis):
    """Hand-rolled sleep+HRV+RHR heuristic, rescaled to 0-100. Fallback only."""
    if not sleep_analysis or not heart_analysis:
        return None
    if sleep_analysis.get("error") or heart_analysis.get("error"):
        return None

    avg_score = sleep_analysis.get("avg_score")
    if avg_score is None:
        return None

    # Base: sleep score scaled to 10
    score = (avg_score / 100) * 10

    # HRV adjustment
    hrv_trend = heart_analysis.get("hrv_trend")
    if hrv_trend is not None:
        if hrv_trend > 3:
            score += 1
        elif hrv_trend < -5:
            score -= 1

    # RHR adjustment
    rhr_trend = heart_analysis.get("rhr_trend")
    if rhr_trend is not None:
        if rhr_trend > 3:
            score -= 1
        elif rhr_trend < 0:
            score += 0.5

    score = max(1, min(10, round(score))) * 10

    # Build description
    parts = []
    if avg_score >= 75:
        parts.append("sleep is solid")
    elif avg_score >= 60:
        parts.append("sleep is fair")
    else:
        parts.append("sleep needs work")

    if hrv_trend is not None:
        if abs(hrv_trend) <= 3:
            parts.append("HRV stable")
        elif hrv_trend > 3:
            parts.append("HRV rising")
        else:
            parts.append("HRV declining")

    detail = ", ".join(parts)
    return {"score": score, "text": f"Recovery: {score}/100 — {detail}"}


def recovery_score(sleep_analysis, heart_analysis, readiness_analysis=None):
    """Thin wrapper for report copy — returns just the text line."""
    status = recovery_status(readiness_analysis, sleep_analysis, heart_analysis)
    return status["text"] if status else None


def sleep_vs_workouts(sleep_data, workouts):
    """Compare sleep scores on nights after workout days vs rest days."""
    if not sleep_data or not workouts:
        return None

    # Build set of workout dates
    workout_dates = set()
    for w in workouts:
        d = w.get("date") or w.get("day")
        if d:
            workout_dates.add(_normalize_date(d))

    if not workout_dates:
        return None

    # For each sleep entry, check if previous day was a workout day
    post_workout_scores = []
    post_rest_scores = []

    for s in sleep_data:
        day_str = _normalize_date(s.get("day", s.get("date", "")))
        score = s.get("score")
        if not day_str or score is None:
            continue

        try:
            sleep_date = datetime.strptime(day_str, "%Y-%m-%d").date()
            prev_day = (sleep_date - timedelta(days=1)).isoformat()
        except (ValueError, TypeError):
            continue

        if prev_day in workout_dates:
            post_workout_scores.append(score)
        else:
            post_rest_scores.append(score)

    if len(post_workout_scores) < 2 or len(post_rest_scores) < 2:
        return None

    avg_workout = round(_avg(post_workout_scores))
    avg_rest = round(_avg(post_rest_scores))
    diff = avg_workout - avg_rest

    if abs(diff) < 3:
        return None  # No meaningful difference

    if diff > 0:
        return f"You sleep better after training days (avg score {avg_workout} vs {avg_rest} on rest days)"
    else:
        return f"Your sleep is lower after training days (avg score {avg_workout} vs {avg_rest} on rest days) — check workout timing or intensity"


def hrv_vs_training_load(hrv_data, workouts):
    """Quantify how next-morning HRV differs after lifting days vs rest/easy days.

    Compares the average next-morning HRV following days with strength volume
    (lift days) against days without it (rest or cardio-only days), and reports
    the actual gap in ms and percent rather than a vague correlation direction.
    """
    if not hrv_data or not workouts:
        return None

    # Build daily strength-volume map (cardio logs volume 0; rest days are absent)
    daily_volume = {}
    for w in workouts:
        d = _normalize_date(w.get("date") or w.get("day", ""))
        vol = w.get("volume")
        if d and vol is not None:
            daily_volume[d] = daily_volume.get(d, 0) + vol

    # Window bounds let us treat an absent day inside the range as a genuine
    # rest day, while excluding days that simply have no data fetched.
    hrv_days = sorted(
        _normalize_date(h.get("day", "")) for h in hrv_data if h.get("day")
    )
    if not hrv_days:
        return None
    window_start, window_end = hrv_days[0], hrv_days[-1]

    # Bucket each morning's HRV by the previous day's training load
    lift_hrvs = []
    rest_hrvs = []
    for h in hrv_data:
        day_str = _normalize_date(h.get("day", ""))
        hrv_val = h.get("avg_hrv")
        if not day_str or hrv_val is None:
            continue
        try:
            hrv_date = datetime.strptime(day_str, "%Y-%m-%d").date()
            prev_day = (hrv_date - timedelta(days=1)).isoformat()
        except (ValueError, TypeError):
            continue

        if not (window_start <= prev_day <= window_end):
            continue  # prev day outside fetched range — can't tell rest from missing

        if daily_volume.get(prev_day, 0) > 0:
            lift_hrvs.append(hrv_val)
        else:
            rest_hrvs.append(hrv_val)

    # Need a few samples on each side for the comparison to mean anything
    if len(lift_hrvs) < 3 or len(rest_hrvs) < 3:
        return None

    mean_lift = _avg(lift_hrvs)
    mean_rest = _avg(rest_hrvs)
    if mean_lift is None or mean_rest is None or mean_rest == 0:
        return None

    delta = mean_lift - mean_rest
    pct = delta / mean_rest * 100
    direction = "higher" if delta >= 0 else "lower"

    return (
        f"Next-morning HRV averaged {round(mean_lift)} ms after lifting days "
        f"vs {round(mean_rest)} ms after rest/easy days "
        f"({abs(round(delta))} ms {direction}, {pct:+.0f}%; "
        f"{len(lift_hrvs)} lift vs {len(rest_hrvs)} rest days)"
    )


def training_consistency_hrv(heart_analysis, exercise_analysis):
    """Assess recovery based on training frequency + HRV trend."""
    if not heart_analysis or not exercise_analysis:
        return None
    if heart_analysis.get("error") or exercise_analysis.get("error"):
        return None

    sessions = exercise_analysis.get("total_sessions", 0)
    hrv_trend = heart_analysis.get("hrv_trend")

    if sessions < 3:
        return None

    if hrv_trend is None:
        return None

    if hrv_trend >= -3:
        return f"{sessions} sessions this week with stable HRV — recovery looks solid"
    else:
        return f"{sessions} sessions this week but HRV is dropping ({hrv_trend:+.1f}ms) — consider a deload"


def sleep_weight_connection(sleep_analysis, weight_analysis):
    """Flag when poor sleep coincides with weight gain."""
    if not sleep_analysis or not weight_analysis:
        return None
    if sleep_analysis.get("error") or weight_analysis.get("error"):
        return None

    avg_score = sleep_analysis.get("avg_score")
    direction = weight_analysis.get("direction")

    if avg_score is None or not direction:
        return None

    if avg_score < 70 and direction == "gaining":
        return f"Poor sleep (avg {avg_score}) coincides with weight trending up — sleep disruption can increase appetite and water retention"

    return None


def blood_test_reminder(blood_tests_parsed):
    """Nudge if last test was >6 months ago. Silent otherwise."""
    if not blood_tests_parsed:
        return None

    dates = []
    for t in blood_tests_parsed:
        d = t.get("date")
        if d:
            try:
                if isinstance(d, str):
                    dates.append(datetime.strptime(d[:10], "%Y-%m-%d").date())
                elif isinstance(d, date):
                    dates.append(d)
            except (ValueError, TypeError):
                continue

    if not dates:
        return None

    latest = max(dates)
    days_ago = (date.today() - latest).days

    if days_ago > 180:
        months = days_ago // 30
        return f"Last blood test was on {latest} ({months} months ago) — time for a new panel?"

    return None


def wellness_sleep_correlation(wellness_analysis, sleep_analysis):
    """Meditation volume vs sleep quality."""
    if not wellness_analysis or wellness_analysis.get("error"):
        return None
    if not sleep_analysis or sleep_analysis.get("error"):
        return None

    med = wellness_analysis.get("meditation", {})
    sessions = med.get("sessions_this", 0)
    avg_score = sleep_analysis.get("avg_score")
    if not avg_score:
        return None

    if sessions >= 3 and avg_score >= 80:
        return f"Regular meditation ({sessions} sessions) paired with strong sleep (avg {avg_score}) — keep it up"
    if sessions == 0 and avg_score < 75:
        return f"No meditation this week and sleep is below target (avg {avg_score}) — worth reintroducing"
    return None


def wellness_recovery_correlation(wellness_analysis, heart_analysis):
    """Sauna + cold plunge volume vs HRV trend."""
    if not wellness_analysis or wellness_analysis.get("error"):
        return None
    if not heart_analysis or heart_analysis.get("error"):
        return None

    sauna_sessions = wellness_analysis.get("sauna", {}).get("sessions_this", 0)
    cold_sessions = wellness_analysis.get("cold_plunge", {}).get("sessions_this", 0)
    recovery_sessions = sauna_sessions + cold_sessions
    hrv_trend = heart_analysis.get("hrv_trend")

    if recovery_sessions >= 2 and hrv_trend is not None and hrv_trend >= 3:
        return f"{recovery_sessions} contrast/recovery sessions (sauna + cold plunge) alongside HRV rising {hrv_trend} ms — hot/cold exposure looks like it's working"
    if recovery_sessions == 0 and hrv_trend is not None and hrv_trend <= -3:
        return f"HRV down {abs(hrv_trend)} ms and no sauna or cold plunge this week — contrast therapy might help"
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_insights(
    sleep_data=None, hrv_data=None, workouts=None,
    sleep_analysis=None, heart_analysis=None,
    exercise_analysis=None, weight_analysis=None,
    wellness_analysis=None,
    blood_tests_parsed=None,
    readiness_analysis=None,
    report_type=None,
):
    """Run all correlation functions and return list of insight strings."""
    insights = []

    dispatch = [
        (recovery_score, (sleep_analysis, heart_analysis, readiness_analysis)),
        (sleep_vs_workouts, (sleep_data, workouts)),
        (hrv_vs_training_load, (hrv_data, workouts)),
        (training_consistency_hrv, (heart_analysis, exercise_analysis)),
        (sleep_weight_connection, (sleep_analysis, weight_analysis)),
        (wellness_sleep_correlation, (wellness_analysis, sleep_analysis)),
        (wellness_recovery_correlation, (wellness_analysis, heart_analysis)),
    ]

    # Blood test cadence is months — only surface the nudge on weekly+ cadence.
    if report_type != "daily":
        dispatch.append((blood_test_reminder, (blood_tests_parsed,)))

    for fn, args in dispatch:
        try:
            result = fn(*args)
            if result:
                insights.append(result)
        except Exception:
            continue

    return insights
