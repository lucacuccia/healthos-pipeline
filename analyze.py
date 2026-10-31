"""Trend analysis and report generation."""

from datetime import date, timedelta
from collections import defaultdict


def _fmt_duration(seconds):
    """Convert seconds to 'Xh YYm' format."""
    if seconds is None:
        return "—"
    h, remainder = divmod(int(seconds), 3600)
    m = remainder // 60
    return f"{h}h {m:02d}m"


def _pct_change(curr, prev):
    """Percent change from prev to curr, rounded. Returns None if not computable."""
    if curr is None or prev is None or prev == 0:
        return None
    return round((curr - prev) / prev * 100)


def _fmt_pct(pct):
    """Format a percent change as '+5%' / '-3%', or '—' for None."""
    if pct is None:
        return "—"
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct}%"


def _slope_per_week(points):
    """Least-squares slope over (day_offset, value) points, in units/week.

    Robust to endpoint noise, unlike last-minus-first. Returns None when the
    points can't support a slope (fewer than 2, or no x spread).
    (statistics.linear_regression needs 3.10+; local venv runs 3.9.)
    """
    if not points or len(points) < 2:
        return None
    n = len(points)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] ** 2 for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx ** 2
    if denom == 0:
        return None
    return (n * sxy - sx * sy) / denom * 7


def _baseline_flag(value, baselines, metric, direction, label, unit="", decimals=0):
    """Personal-baseline flag text, or None if value is within the norm.

    Returns (flag_text, had_baseline): had_baseline is False when no baseline
    exists for the metric, meaning the caller should fall back to its fixed
    constant instead.
    """
    from baselines import is_abnormal, describe
    baseline = (baselines or {}).get(metric)
    if not baseline:
        return None, False
    abnormal, _ = is_abnormal(value, baseline, direction=direction)
    if not abnormal:
        return None, True
    side = "below" if direction == "low" else "above"
    val_str = f"{round(value, decimals) if decimals else round(value):g}{' ' + unit if unit else ''}"
    return (
        f"{label} {val_str} is well {side} your 60-day norm "
        f"({describe(baseline, unit=unit, decimals=decimals)})",
        True,
    )


def analyze_sleep(sleep_data, sleep_durations=None, weekly=False, baselines=None):
    """Analyze sleep data. Input: list of Oura daily_sleep objects.

    baselines: optional dict from baselines.get_baselines() — when present,
    flags fire on deviation from the personal norm instead of fixed constants.
    """
    if not sleep_data:
        return {"error": "No sleep data available"}

    if weekly:
        cutoff = date.today() - timedelta(days=7)
        this_week_data = [s for s in sleep_data if s.get("day") and s["day"] > str(cutoff)]
        last_week_data = [s for s in sleep_data if s.get("day") and s["day"] <= str(cutoff)]
        active_data = this_week_data if this_week_data else sleep_data
    else:
        active_data = sleep_data
        last_week_data = []

    scores = [s.get("score") for s in active_data if s.get("score")]
    avg_score = round(sum(scores) / len(scores), 1) if scores else None

    # Extract contributor scores where available (used by generate_suggestions)
    contributors = defaultdict(list)
    for s in active_data:
        for key, val in s.get("contributors", {}).items():
            if isinstance(val, (int, float)):
                contributors[key].append(val)

    avg_contributors = {}
    for key, vals in contributors.items():
        avg_contributors[key] = round(sum(vals) / len(vals), 1)

    # Trend: week-over-week (weekly) or day-over-day (daily)
    trend = None
    if weekly:
        last_week_scores = [s.get("score") for s in last_week_data if s.get("score")]
        if scores and last_week_scores:
            trend = round(sum(scores) / len(scores) - sum(last_week_scores) / len(last_week_scores), 1)
    elif len(scores) >= 2:
        trend = round(scores[-1] - scores[-2], 1)

    # Flags — personal baseline when available, fixed constant otherwise
    flags = []
    if avg_score:
        flag, had_baseline = _baseline_flag(
            avg_score, baselines, "sleep_score", "low", "Average sleep score"
        )
        if flag:
            flags.append(flag)
        elif not had_baseline and avg_score < 70:
            flags.append(f"Average sleep score is low ({avg_score})")

    # Duration-based analysis
    avg_deep_sleep = None
    avg_rem_sleep = None
    avg_total_sleep = None
    deep_sleep_trend = None
    rem_sleep_trend = None
    total_sleep_trend = None
    last_night = {}
    daily_durations = []
    if sleep_durations:
        if weekly:
            cutoff_str = str(date.today() - timedelta(days=7))
            this_week_dur = [d for d in sleep_durations if d.get("day") and d["day"] > cutoff_str]
            last_week_dur = [d for d in sleep_durations if d.get("day") and d["day"] <= cutoff_str]
            dur_display = this_week_dur if this_week_dur else sleep_durations
        else:
            dur_display = sleep_durations
            last_week_dur = []

        deep_vals = [d["deep_sleep_sec"] for d in dur_display if d.get("deep_sleep_sec") is not None]
        rem_vals = [d["rem_sleep_sec"] for d in dur_display if d.get("rem_sleep_sec") is not None]
        total_vals = [d["total_sleep_sec"] for d in dur_display if d.get("total_sleep_sec") is not None]

        avg_deep_sec = round(sum(deep_vals) / len(deep_vals)) if deep_vals else None
        avg_rem_sec = round(sum(rem_vals) / len(rem_vals)) if rem_vals else None
        avg_total_sec = round(sum(total_vals) / len(total_vals)) if total_vals else None

        avg_deep_sleep = _fmt_duration(avg_deep_sec)
        avg_rem_sleep = _fmt_duration(avg_rem_sec)
        avg_total_sleep = _fmt_duration(avg_total_sec)

        def _duration_trend(key, this_entries, prev_entries):
            this_vals = [d[key] for d in this_entries if d.get(key) is not None]
            if weekly:
                prev_vals = [d[key] for d in prev_entries if d.get(key) is not None]
                if not this_vals or not prev_vals:
                    return None
                diff_sec = sum(this_vals) / len(this_vals) - sum(prev_vals) / len(prev_vals)
            else:
                if len(this_vals) < 2:
                    return None
                diff_sec = this_vals[-1] - this_vals[-2]
            diff_min = round(diff_sec / 60)
            arrow = "↑" if diff_min > 0 else "↓" if diff_min < 0 else "→"
            return {"arrow": arrow, "delta_min": abs(diff_min)}

        deep_sleep_trend = _duration_trend("deep_sleep_sec", dur_display, last_week_dur)
        rem_sleep_trend = _duration_trend("rem_sleep_sec", dur_display, last_week_dur)
        total_sleep_trend = _duration_trend("total_sleep_sec", dur_display, last_week_dur)

        # Last night's values (most recent entry in this week)
        latest = dur_display[-1]
        last_night = {
            "day": latest.get("day"),
            "deep_sec": latest.get("deep_sleep_sec"),
            "rem_sec": latest.get("rem_sleep_sec"),
            "total_sec": latest.get("total_sleep_sec"),
        }

        # Flag if average deep sleep < 1 hour
        if avg_deep_sec and avg_deep_sec < 3600:
            flags.append(f"Average deep sleep is low ({avg_deep_sleep})")

        # Total sleep vs personal baseline (formatted as durations, so this
        # doesn't go through _baseline_flag)
        duration_baseline = (baselines or {}).get("sleep_duration")
        if duration_baseline and avg_total_sec:
            from baselines import is_abnormal
            abnormal, _ = is_abnormal(avg_total_sec, duration_baseline, direction="low")
            if abnormal:
                flags.append(
                    f"Average total sleep {avg_total_sleep} is well below your "
                    f"60-day norm ({_fmt_duration(duration_baseline['mean'])} "
                    f"± {round(duration_baseline['sd'] / 60)}m)"
                )

        ordered = list(dur_display)  # chronological: oldest → newest
        entries = []
        for i, d in enumerate(ordered):
            prev = ordered[i - 1] if i > 0 else None
            entries.append({
                "day": d["day"],
                "deep": _fmt_duration(d.get("deep_sleep_sec")),
                "rem": _fmt_duration(d.get("rem_sleep_sec")),
                "total": _fmt_duration(d.get("total_sleep_sec")),
                "deep_pct": _fmt_pct(_pct_change(d.get("deep_sleep_sec"), prev.get("deep_sleep_sec") if prev else None)),
                "rem_pct": _fmt_pct(_pct_change(d.get("rem_sleep_sec"), prev.get("rem_sleep_sec") if prev else None)),
                "total_pct": _fmt_pct(_pct_change(d.get("total_sleep_sec"), prev.get("total_sleep_sec") if prev else None)),
            })
        daily_durations = list(reversed(entries))
    else:
        deep = avg_contributors.get("deep_sleep")
        if deep and deep < 50:
            flags.append(f"Deep sleep contributor score low ({deep})")

    # Last night's score
    last_score = scores[-1] if scores else None

    return {
        "days": len(active_data),
        "avg_score": avg_score,
        "avg_contributors": avg_contributors,
        "trend": trend,
        "flags": flags,
        "daily_scores": [{"day": s.get("day"), "score": s.get("score")} for s in active_data],
        "avg_deep_sleep": avg_deep_sleep,
        "avg_rem_sleep": avg_rem_sleep,
        "avg_total_sleep": avg_total_sleep,
        "deep_sleep_trend": deep_sleep_trend,
        "rem_sleep_trend": rem_sleep_trend,
        "total_sleep_trend": total_sleep_trend,
        "last_night": last_night,
        "last_score": last_score,
        "daily_durations": daily_durations,
    }


def analyze_heart_metrics(hrv_rhr_data, weekly=False, baselines=None):
    """Analyze HRV and resting heart rate trends.

    Input: list of dicts [{day, avg_hrv, lowest_hr, avg_hr}, ...]
    baselines: optional dict from baselines.get_baselines().
    """
    if not hrv_rhr_data:
        return {"error": "No HRV/heart rate data available"}

    if weekly:
        cutoff = str(date.today() - timedelta(days=7))
        this_week = [d for d in hrv_rhr_data if d.get("day") and d["day"] > cutoff]
        last_week = [d for d in hrv_rhr_data if d.get("day") and d["day"] <= cutoff]
        active = this_week if this_week else hrv_rhr_data
    else:
        active = hrv_rhr_data
        last_week = []

    hrvs = [d["avg_hrv"] for d in active if d.get("avg_hrv") is not None]
    rhrs = [d["lowest_hr"] for d in active if d.get("lowest_hr") is not None]

    avg_hrv = round(sum(hrvs) / len(hrvs), 1) if hrvs else None
    avg_rhr = round(sum(rhrs) / len(rhrs), 1) if rhrs else None

    # Trend: week-over-week (weekly) or day-over-day (daily)
    hrv_trend = None
    rhr_trend = None
    if weekly:
        last_hrvs = [d["avg_hrv"] for d in last_week if d.get("avg_hrv") is not None]
        last_rhrs = [d["lowest_hr"] for d in last_week if d.get("lowest_hr") is not None]
        if hrvs and last_hrvs:
            hrv_trend = round(sum(hrvs) / len(hrvs) - sum(last_hrvs) / len(last_hrvs), 1)
        if rhrs and last_rhrs:
            rhr_trend = round(sum(rhrs) / len(rhrs) - sum(last_rhrs) / len(last_rhrs), 1)
    else:
        if len(hrvs) >= 2:
            hrv_trend = round(hrvs[-1] - hrvs[-2], 1)
        if len(rhrs) >= 2:
            rhr_trend = round(rhrs[-1] - rhrs[-2], 1)

    # Flags — personal baseline when available, fixed constant otherwise
    flags = []
    if avg_hrv:
        flag, had_baseline = _baseline_flag(
            avg_hrv, baselines, "hrv", "low", "Average HRV", unit="ms"
        )
        if flag:
            flags.append(flag)
        elif not had_baseline and avg_hrv < 20:
            flags.append(f"Average HRV is low ({avg_hrv} ms)")
    if avg_rhr:
        flag, _ = _baseline_flag(
            avg_rhr, baselines, "rhr", "high", "Average resting HR", unit="bpm"
        )
        if flag:
            flags.append(flag)
    if hrv_trend and hrv_trend < -5:
        flags.append(f"HRV trending down ({hrv_trend} ms)")
    if rhr_trend and rhr_trend > 3:
        flags.append(f"Resting heart rate trending up (+{rhr_trend} bpm)")

    ordered = list(active)  # chronological: oldest → newest
    daily_entries = []
    for idx, d in enumerate(ordered):
        prev = ordered[idx - 1] if idx > 0 else None
        daily_entries.append({
            "day": d["day"],
            "hrv": d.get("avg_hrv"),
            "rhr": d.get("lowest_hr"),
            "hrv_pct": _fmt_pct(_pct_change(d.get("avg_hrv"), prev.get("avg_hrv") if prev else None)),
            "rhr_pct": _fmt_pct(_pct_change(d.get("lowest_hr"), prev.get("lowest_hr") if prev else None)),
        })

    return {
        "days": len(active),
        "avg_hrv": avg_hrv,
        "avg_rhr": avg_rhr,
        "hrv_trend": hrv_trend,
        "rhr_trend": rhr_trend,
        "flags": flags,
        "daily": list(reversed(daily_entries)),
    }


def _split_week(data, anchor=None):
    """Split day-keyed entries into (this_week, last_week) around a 7-day cutoff.

    `anchor` is the last day counted as "this week" (defaults to today). Pass
    yesterday when today's entry is excluded, so both windows hold 7 days.
    """
    cutoff = str((anchor or date.today()) - timedelta(days=7))
    this_week = [d for d in data if d.get("day") and d["day"] > cutoff]
    last_week = [d for d in data if d.get("day") and d["day"] <= cutoff]
    return this_week, last_week


def analyze_readiness(readiness_data, weekly=False):
    """Analyze Oura daily_readiness data (validated readiness score + contributors).

    Input: list of Oura daily_readiness objects [{day, score, contributors}, ...]
    """
    if not readiness_data:
        return {"error": "No readiness data available"}

    if weekly:
        this_week, last_week = _split_week(readiness_data)
        active = this_week if this_week else readiness_data
    else:
        active = readiness_data
        last_week = []

    scores = [r.get("score") for r in active if r.get("score")]
    avg_score = round(sum(scores) / len(scores), 1) if scores else None

    contributors = defaultdict(list)
    for r in active:
        for key, val in (r.get("contributors") or {}).items():
            if isinstance(val, (int, float)):
                contributors[key].append(val)
    avg_contributors = {
        key: round(sum(vals) / len(vals), 1) for key, vals in contributors.items()
    }
    # Contributors Oura scores below 70 are dragging readiness down
    low_contributors = {
        key: val for key, val in avg_contributors.items() if val < 70
    }

    trend = None
    if weekly:
        last_scores = [r.get("score") for r in last_week if r.get("score")]
        if scores and last_scores:
            trend = round(sum(scores) / len(scores) - sum(last_scores) / len(last_scores), 1)
    elif len(scores) >= 2:
        trend = round(scores[-1] - scores[-2], 1)

    # Readiness is already personalized by Oura — a fixed floor is appropriate
    flags = []
    if avg_score and avg_score < 70:
        flags.append(f"Average readiness is low ({avg_score})")

    return {
        "days": len(active),
        "avg_score": avg_score,
        "last_score": scores[-1] if scores else None,
        "trend": trend,
        "avg_contributors": avg_contributors,
        "low_contributors": low_contributors,
        "flags": flags,
        "daily": [{"day": r.get("day"), "score": r.get("score")} for r in active],
    }


def analyze_activity(activity_data, weekly=False):
    """Analyze Oura daily_activity data (steps, calories, activity score).

    Input: list of Oura daily_activity objects [{day, score, steps,
    active_calories, total_calories}, ...]
    """
    if not activity_data:
        return {"error": "No activity data available"}

    # Today's entry is still accumulating steps throughout the day, so it
    # would misrepresent activity if the report runs early (e.g. 8am).
    # Use only complete days when any are available — daily and weekly alike.
    today_str = str(date.today())
    full_days = [e for e in activity_data if e.get("day") != today_str]
    complete = full_days if full_days else activity_data

    if weekly:
        # Anchor on yesterday so both comparison windows cover 7 complete days.
        anchor = date.today() - timedelta(days=1) if full_days else None
        this_week, last_week = _split_week(complete, anchor=anchor)
        active = this_week if this_week else complete
    else:
        active = complete
        last_week = []

    def _mean(entries, key, digits=0):
        vals = [e.get(key) for e in entries if e.get(key) is not None]
        if not vals:
            return None
        return round(sum(vals) / len(vals), digits) if digits else round(sum(vals) / len(vals))

    avg_steps = _mean(active, "steps")
    avg_active_cal = _mean(active, "active_calories")
    avg_score = _mean(active, "score", digits=1)

    steps_trend = None
    if weekly:
        last_avg_steps = _mean(last_week, "steps")
        if avg_steps is not None and last_avg_steps is not None:
            steps_trend = avg_steps - last_avg_steps
    else:
        step_vals = [e.get("steps") for e in active if e.get("steps") is not None]
        if len(step_vals) >= 2:
            steps_trend = step_vals[-1] - step_vals[-2]

    return {
        "days": len(active),
        "avg_steps": avg_steps,
        "avg_active_calories": avg_active_cal,
        "avg_score": avg_score,
        "steps_trend": steps_trend,
        "daily": [
            {
                "day": e.get("day"),
                "steps": e.get("steps"),
                "active_calories": e.get("active_calories"),
                "score": e.get("score"),
            }
            for e in active
        ],
    }


def analyze_exercise(workouts):
    """Analyze workout data. Expects up to 14 days of workouts for week-over-week comparison.

    Compares the most recent 7-day window (this week) against the prior 7-day window (last week):
    for each exercise done this week, reports max weight this week vs max weight last week.
    """
    if not workouts:
        return {"error": "No workout data available"}

    today = date.today()
    this_week_start = today - timedelta(days=7)

    this_week = [w for w in workouts if w["date"] > this_week_start]
    last_week = [w for w in workouts if w["date"] <= this_week_start]

    by_exercise_this = defaultdict(list)
    for w in this_week:
        by_exercise_this[w["exercise"]].append(w)

    by_exercise_last = defaultdict(list)
    for w in last_week:
        by_exercise_last[w["exercise"]].append(w)

    progression = {}
    for ex, sessions in by_exercise_this.items():
        sessions.sort(key=lambda x: x["date"])
        this_weights = [s["weight"] for s in sessions]
        this_max = max(this_weights) if this_weights else 0
        last_weights = [s["weight"] for s in by_exercise_last.get(ex, [])]
        last_max = max(last_weights) if last_weights else None
        weight_delta = (this_max - last_max) if last_max is not None else None
        # Within-week change: first vs last session this week. Catches changes
        # the max-vs-max comparison misses (new exercises, or a mid-week bump
        # back up to last week's max).
        within_week_delta = (this_weights[-1] - this_weights[0]) if len(this_weights) >= 2 else None
        progression[ex] = {
            "sessions": len(sessions),
            "this_week_weight": this_max,
            "last_week_weight": last_max,
            "weight_delta": weight_delta,
            "week_first_weight": this_weights[0],
            "week_last_weight": this_weights[-1],
            "within_week_delta": within_week_delta,
            "total_volume": sum(s["volume"] for s in sessions),
        }

    # PRs (use full 14-day window)
    from sheets import find_prs
    prs = find_prs(workouts)

    return {
        "total_sessions": len(set(w["date"] for w in this_week)),
        "exercises": len(by_exercise_this),
        "progression": progression,
        "recent_prs": [p for p in prs if (today - p["date"]).days <= 14],
    }


def analyze_weight(entries):
    """Analyze bodyweight trend."""
    if not entries:
        return {"error": "No bodyweight data available"}

    entries.sort(key=lambda x: x["date"])
    weights = [e["weight"] for e in entries]
    current = weights[-1]

    # 4-week trend
    four_weeks_ago = date.today() - timedelta(days=28)
    recent = [e for e in entries if e["date"] >= four_weeks_ago]
    if recent:
        weekly_avg = round(sum(e["weight"] for e in recent) / len(recent), 1)
    else:
        weekly_avg = current

    # Direction + rate from a least-squares slope over the whole window, so a
    # single noisy endpoint reading can't flip the trend.
    first_day = entries[0]["date"]
    points = [((e["date"] - first_day).days, e["weight"]) for e in entries]
    slope = _slope_per_week(points)
    rate = round(slope, 2) if slope is not None else None

    if rate is None:
        direction = "insufficient data"
    elif rate > 0.5:
        direction = "gaining"
    elif rate < -0.5:
        direction = "losing"
    else:
        direction = "stable"

    return {
        "current": current,
        "weekly_avg": weekly_avg,
        "direction": direction,
        "rate_per_week": rate,
        "entries": len(entries),
    }


def _bp_avg(entries, key):
    vals = [e[key] for e in entries if e.get(key) is not None]
    return round(sum(vals) / len(vals)) if vals else None


def _bp_window_summary(entries, session):
    """Average sys/dia/hr for one session ("am"/"pm") over a window of entries."""
    sys_v = _bp_avg(entries, f"systolic_{session}")
    dia_v = _bp_avg(entries, f"diastolic_{session}")
    hr_v = _bp_avg(entries, f"hr_{session}")
    if sys_v is None or dia_v is None:
        return None
    return {"systolic": sys_v, "diastolic": dia_v, "hr": hr_v}


def analyze_bp(bp_entries, weekly=False, baselines=None):
    """Analyze blood pressure entries.

    Input: list of {"date", "systolic_am", "diastolic_am", "systolic_pm",
    "diastolic_pm"} optionally extended with hr_am/hr_pm/notes_am/notes_pm
    (Firestore source). In weekly mode, entries may span the whole year to
    date — the daily table covers this week only, while the standing
    averages cover this week / rolling 30 days / year to date.
    Returns aggregated metrics, trends, standing averages, and flags.
    """
    if not bp_entries:
        return {"error": "No blood pressure data available"}

    bp_entries = sorted(bp_entries, key=lambda x: x["date"])
    today = date.today()

    if weekly:
        cutoff = today - timedelta(days=7)
        this_week = [e for e in bp_entries if e["date"] > cutoff]
        last_week = [e for e in bp_entries if cutoff - timedelta(days=7) < e["date"] <= cutoff]
        active = this_week
    else:
        active = bp_entries
        last_week = []

    avg_sys_am = _bp_avg(active, "systolic_am")
    avg_dia_am = _bp_avg(active, "diastolic_am")
    avg_sys_pm = _bp_avg(active, "systolic_pm")
    avg_dia_pm = _bp_avg(active, "diastolic_pm")
    avg_hr_am = _bp_avg(active, "hr_am")
    avg_hr_pm = _bp_avg(active, "hr_pm")

    def _trend(key, this_entries, prev_entries):
        this_vals = [e[key] for e in this_entries if e.get(key) is not None]
        if weekly:
            prev_vals = [e[key] for e in prev_entries if e.get(key) is not None]
            if not this_vals or not prev_vals:
                return None
            delta = round(sum(this_vals) / len(this_vals) - sum(prev_vals) / len(prev_vals))
        else:
            if len(this_vals) < 2:
                return None
            delta = round(this_vals[-1] - this_vals[-2])
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        return {"arrow": arrow, "delta": abs(delta)}

    systolic_trend = _trend("systolic_am", active, last_week)
    diastolic_trend = _trend("diastolic_am", active, last_week)
    hr_trend = _trend("hr_am", active, last_week)

    flags = []
    if avg_sys_am:
        flag, had_baseline = _baseline_flag(
            avg_sys_am, baselines, "systolic", "high", "Average AM systolic", unit="mmHg"
        )
        if flag:
            flags.append(flag)
        elif not had_baseline and avg_sys_am > 130:
            flags.append(f"Elevated average systolic ({avg_sys_am} mmHg)")
    # Absolute clinical threshold — kept regardless of personal baseline
    for e in active:
        sys = e.get("systolic_am") or e.get("systolic_pm")
        dia = e.get("diastolic_am") or e.get("diastolic_pm")
        if sys and sys > 140:
            flags.append(f"High reading on {e['date']} ({sys}/{dia} mmHg)")

    daily = []
    for e in active:
        sys_am_v = e.get("systolic_am")
        dia_am_v = e.get("diastolic_am")
        sys_pm_v = e.get("systolic_pm")
        dia_pm_v = e.get("diastolic_pm")
        am_str = f"{int(sys_am_v)}/{int(dia_am_v)}" if sys_am_v and dia_am_v else "—"
        pm_str = f"{int(sys_pm_v)}/{int(dia_pm_v)}" if sys_pm_v and dia_pm_v else "—"
        note_parts = []
        if e.get("notes_am"):
            note_parts.append(f"AM: {e['notes_am']}")
        if e.get("notes_pm"):
            note_parts.append(f"PM: {e['notes_pm']}")
        daily.append({
            "date": str(e["date"]),
            "am": am_str,
            "pm": pm_str,
            "notes": " · ".join(note_parts),
        })

    # Standing averages over fixed windows, independent of the weekly split.
    standing = []
    for label, since in [
        ("This Week", today - timedelta(days=7)),
        ("Last 30 Days", today - timedelta(days=30)),
        ("Year to Date", date(today.year, 1, 1) - timedelta(days=1)),
    ]:
        window = [e for e in bp_entries if e["date"] > since]
        standing.append({
            "label": label,
            "am": _bp_window_summary(window, "am"),
            "pm": _bp_window_summary(window, "pm"),
        })

    return {
        "avg_systolic_am": avg_sys_am,
        "avg_diastolic_am": avg_dia_am,
        "avg_systolic_pm": avg_sys_pm,
        "avg_diastolic_pm": avg_dia_pm,
        "avg_hr_am": avg_hr_am,
        "avg_hr_pm": avg_hr_pm,
        "systolic_trend": systolic_trend,
        "diastolic_trend": diastolic_trend,
        "hr_trend": hr_trend,
        "flags": flags,
        "daily": daily,
        "standing": standing,
        "count": len(active),
    }


def analyze_wellness(extras):
    """Analyze wellness activities (meditation, sauna, cold plunge).

    Expects up to 14 days of extras for week-over-week comparison.
    Each extra: {date, meditation, sauna, cold_plunge}, where each nested
    activity dict has {duration: int (min), ...} or is None.
    """
    if not extras:
        return {"error": "No wellness activities logged this week."}

    today = date.today()
    this_week_start = today - timedelta(days=7)

    def _activity_stats(entries, activity_key, temp_key=None):
        durations = []
        temps = []
        for e in entries:
            act = e.get(activity_key)
            if not act:
                continue
            dur = act.get("duration")
            if dur is not None:
                durations.append(dur)
            if temp_key and act.get(temp_key) is not None:
                temps.append(act[temp_key])
        sessions = len(durations)
        total = sum(durations)
        avg = round(total / sessions) if sessions else None
        avg_temp = round(sum(temps) / len(temps), 1) if temps else None
        return sessions, total, avg, avg_temp

    this_week = [e for e in extras if e["date"] > this_week_start]
    last_week = [e for e in extras if e["date"] <= this_week_start]

    def _summary(activity_key, temp_key=None):
        s_this, t_this, a_this, temp_this = _activity_stats(this_week, activity_key, temp_key)
        s_last, t_last, _, _ = _activity_stats(last_week, activity_key, temp_key)
        out = {
            "sessions_this": s_this,
            "sessions_last": s_last,
            "total_min_this": t_this,
            "total_min_last": t_last,
            "avg_min_this": a_this,
            "delta_sessions": s_this - s_last,
            "delta_total_min": t_this - t_last,
        }
        if temp_key:
            out["avg_temp_f_this"] = temp_this
        return out

    meditation = _summary("meditation")
    sauna = _summary("sauna", temp_key="temperature")
    cold_plunge = _summary("cold_plunge", temp_key="temperature")

    # Meditation style split (this week)
    style_split = {"Seated": 0, "Walking": 0}
    for e in this_week:
        med = e.get("meditation")
        if med and med.get("style") in style_split:
            style_split[med["style"]] += 1
    meditation["style_split"] = style_split

    # Daily table for this week (most recent first)
    daily = []
    for e in sorted(this_week, key=lambda x: x["date"], reverse=True):
        med = e.get("meditation")
        sau = e.get("sauna")
        cold = e.get("cold_plunge")
        med_str = f"{med['duration']}m {med.get('style', '')}".strip() if med else None
        if sau:
            temp = sau.get("temperature")
            sau_str = f"{sau['duration']}m @{temp:g}°F" if temp is not None else f"{sau['duration']}m"
        else:
            sau_str = None
        if cold:
            temp = cold.get("temperature")
            cold_str = f"{cold['duration']}m @{temp:g}°F" if temp is not None else f"{cold['duration']}m"
        else:
            cold_str = None
        if med_str or sau_str or cold_str:
            daily.append({
                "date": e["date"],
                "meditation": med_str,
                "sauna": sau_str,
                "cold_plunge": cold_str,
            })

    any_activity = any(
        s["sessions_this"] or s["sessions_last"]
        for s in (meditation, sauna, cold_plunge)
    )
    if not any_activity:
        return {"error": "No wellness activities logged this week."}

    return {
        "meditation": meditation,
        "sauna": sauna,
        "cold_plunge": cold_plunge,
        "daily": daily,
        "any_activity": any_activity,
    }


def generate_questions(sleep_analysis, exercise_analysis, weight_analysis, heart_analysis=None):
    """Generate contextual questions about anomalies."""
    questions = []
    q_num = 1

    if sleep_analysis.get("flags"):
        for flag in sleep_analysis["flags"]:
            questions.append(f"{q_num}. {flag} — any idea what's causing this? (stress, late meals, screen time?)")
            q_num += 1

    if sleep_analysis.get("trend") and sleep_analysis["trend"] < -5:
        questions.append(f"{q_num}. Your sleep score dropped {abs(sleep_analysis['trend'])} points this week — anything unusual going on?")
        q_num += 1

    if weight_analysis.get("direction") == "gaining" and weight_analysis.get("rate_per_week", 0) > 1:
        questions.append(f"{q_num}. You're gaining ~{weight_analysis['rate_per_week']} lbs/week — is this intentional (bulking) or unintentional?")
        q_num += 1

    if heart_analysis and heart_analysis.get("hrv_trend") and heart_analysis["hrv_trend"] < -5:
        questions.append(f"{q_num}. Your HRV dropped {abs(heart_analysis['hrv_trend'])} ms — stress, illness, or overtraining?")
        q_num += 1

    if heart_analysis and heart_analysis.get("rhr_trend") and heart_analysis["rhr_trend"] > 3:
        questions.append(f"{q_num}. Resting heart rate is creeping up (+{heart_analysis['rhr_trend']} bpm) — feeling run down?")
        q_num += 1

    if not questions:
        questions.append(f"{q_num}. Everything looks stable this week — any subjective changes in energy or recovery you've noticed?")

    return questions


def generate_suggestions(sleep_analysis, exercise_analysis, weight_analysis, heart_analysis=None):
    """Generate actionable intervention ideas based on patterns."""
    suggestions = []

    if sleep_analysis.get("avg_score") and sleep_analysis["avg_score"] < 75:
        suggestions.append("Consider a consistent wind-down routine: no screens 30 min before bed, room at 65-68°F")

    deep = sleep_analysis.get("avg_contributors", {}).get("deep_sleep")
    if deep and deep < 50:
        suggestions.append("Low deep sleep — try limiting alcohol and heavy meals within 3 hours of bedtime")

    if exercise_analysis.get("total_sessions", 0) < 3:
        suggestions.append("Only {n} workout sessions this week — even light movement on rest days helps recovery".format(
            n=exercise_analysis.get("total_sessions", 0)))

    if heart_analysis and heart_analysis.get("flags"):
        for flag in heart_analysis["flags"]:
            if "HRV" in flag and "low" in flag:
                suggestions.append("Low HRV can signal accumulated stress — consider a deload day or extra rest")
            if "trending up" in flag:
                suggestions.append("Rising resting HR often means insufficient recovery — prioritize sleep and hydration")

    return suggestions


def generate_report(sleep_data=None, workouts=None, weight_entries=None,
                    new_files=None, blood_tests=None, blood_tests_parsed=None,
                    responses=None, hrv_rhr_data=None, sleep_durations=None,
                    bp_entries=None, wellness_data=None,
                    readiness_data=None, activity_data=None, baselines=None,
                    report_type="weekly", start_date=None, end_date=None,
                    show_blood_tests=True):
    """Assemble a full markdown report. Returns (markdown, metadata) tuple.

    metadata contains analysis dicts for use by Telegram formatter.

    show_blood_tests gates the weekly blood test sections (trends + latest
    results explained). Callers set it False to suppress results that have
    already been shown in a prior weekly email, until a newer test arrives.
    """
    lines = []
    today = date.today()
    metadata = {}

    def _empty(msg):
        lines.append(f"_{msg}_")

    if report_type == "daily":
        lines.append(f"# Health OS — Daily Snapshot ({today})")
    elif start_date and end_date:
        if start_date.year == end_date.year:
            range_str = f"{start_date.strftime('%B %-d')} – {end_date.strftime('%B %-d, %Y')}"
        else:
            range_str = f"{start_date.strftime('%B %-d, %Y')} – {end_date.strftime('%B %-d, %Y')}"
        lines.append(f"# Health OS — Weekly Report ({range_str})")
    else:
        lines.append(f"# Health OS — Weekly Report ({today})")

    is_weekly = report_type == "weekly"

    # Sleep
    if sleep_data is not None or is_weekly:
        sleep = analyze_sleep(sleep_data or [], sleep_durations=sleep_durations,
                              weekly=is_weekly, baselines=baselines)
        metadata["sleep"] = sleep
        lines.append("\n## Sleep")
        if sleep.get("error"):
            _empty("No sleep data available for this week.")
        else:
            lines.append(f"- **7-Day Average Score:** {sleep['avg_score']}")
            if sleep.get("trend") is not None:
                direction = "↑" if sleep["trend"] > 0 else "↓" if sleep["trend"] < 0 else "→"
                lines.append(f"- **Week Trend:** {direction} {abs(sleep['trend'])} points")
            if sleep.get("avg_deep_sleep"):
                lines.append("\n### 7-Day Averages")
                lines.append("- **Sleep Durations:**")
                lines.append(f"  - Deep Sleep: {sleep['avg_deep_sleep']}")
                lines.append(f"  - REM Sleep: {sleep['avg_rem_sleep']}")
                lines.append(f"  - Total Sleep: {sleep['avg_total_sleep']}")
            if sleep.get("flags"):
                lines.append("- **Flags:**")
                for f in sleep["flags"]:
                    lines.append(f"  - ⚠️ {f}")
            if sleep.get("daily_durations"):
                lines.append("\n| Day | Deep | Δ Deep | REM | Δ REM | Total | Δ Total |")
                lines.append("|-----|------|--------|-----|-------|-------|---------|")
                for d in sleep["daily_durations"]:
                    lines.append(f"| {d['day']} | {d['deep']} | {d.get('deep_pct', '—')} | {d['rem']} | {d.get('rem_pct', '—')} | {d['total']} | {d.get('total_pct', '—')} |")
            else:
                lines.append("\n| Day | Score |")
                lines.append("|-----|-------|")
                for d in sleep.get("daily_scores", []):
                    lines.append(f"| {d['day']} | {d['score']} |")

    # Readiness (Oura-only). No dedicated section is rendered for either report
    # type — the analysis is kept in metadata only so the recovery score in
    # Insights stays readiness-driven.
    if readiness_data:
        readiness = analyze_readiness(readiness_data, weekly=is_weekly)
        metadata["readiness"] = readiness

    # HRV & Resting Heart Rate
    if hrv_rhr_data is not None or is_weekly:
        heart = analyze_heart_metrics(hrv_rhr_data or [], weekly=is_weekly, baselines=baselines)
        metadata["heart"] = heart
        lines.append("\n## HRV & Resting Heart Rate")
        if heart.get("error"):
            _empty("No HRV or resting heart rate data available for this week.")
        else:
            lines.append(f"- **7-Day Avg HRV:** {heart['avg_hrv']} ms")
            lines.append(f"- **7-Day Avg Resting HR:** {heart['avg_rhr']} bpm")
            if heart.get("hrv_trend") is not None:
                direction = "↑" if heart["hrv_trend"] > 0 else "↓" if heart["hrv_trend"] < 0 else "→"
                lines.append(f"- **HRV Trend:** {direction} {abs(heart['hrv_trend'])} ms")
            if heart.get("rhr_trend") is not None:
                direction = "↑" if heart["rhr_trend"] > 0 else "↓" if heart["rhr_trend"] < 0 else "→"
                lines.append(f"- **RHR Trend:** {direction} {abs(heart['rhr_trend'])} bpm")
            if heart.get("flags"):
                lines.append("- **Flags:**")
                for f in heart["flags"]:
                    lines.append(f"  - ⚠️ {f}")
            lines.append("\n| Day | HRV (ms) | Δ HRV | RHR (bpm) | Δ RHR |")
            lines.append("|-----|----------|-------|-----------|-------|")
            for d in heart.get("daily", []):
                hrv_val = d["hrv"] if d["hrv"] is not None else "—"
                rhr_val = d["rhr"] if d["rhr"] is not None else "—"
                lines.append(f"| {d['day']} | {hrv_val} | {d.get('hrv_pct', '—')} | {rhr_val} | {d.get('rhr_pct', '—')} |")

    # Exercise
    exercise = None
    if workouts is not None or is_weekly:
        exercise = analyze_exercise(workouts or [])
        metadata["exercise"] = exercise
        lines.append("\n## Exercise")
        if exercise.get("error"):
            _empty("No workouts logged this week.")
        else:
            lines.append(f"- **Total workouts:** {exercise['total_sessions']}")
            changed = {
                ex: data for ex, data in (exercise.get("progression") or {}).items()
                if data.get("weight_delta") or data.get("within_week_delta")
            }
            if changed:
                lines.append("\n### Weight Progression (vs last week)")
                lines.append("| Exercise | Sessions | Last wk → This wk (lbs) | Δ |")
                lines.append("|----------|----------|------------------------|---|")
                for ex, data in changed.items():
                    delta = data["weight_delta"]
                    if delta:
                        arrow = "↑" if delta > 0 else "↓"
                        delta_str = f"{arrow} {abs(delta):g} lbs"
                        weight_str = f"{data['last_week_weight']:g} → {data['this_week_weight']:g}"
                    else:
                        wd = data["within_week_delta"]
                        arrow = "↑" if wd > 0 else "↓"
                        delta_str = f"{arrow} {abs(wd):g} lbs (in-week)"
                        weight_str = f"{data['week_first_weight']:g} → {data['week_last_weight']:g}"
                    lines.append(f"| {ex} | {data['sessions']} | {weight_str} | {delta_str} |")
            elif exercise.get("progression"):
                lines.append("\n_No weight changes vs last week._")

    # Activity (Oura-only; steps, calories, activity score)
    if activity_data:
        activity = analyze_activity(activity_data, weekly=is_weekly)
        metadata["activity"] = activity
        lines.append("\n## Activity")
        if activity.get("error"):
            _empty("No activity data available for this week.")
        else:
            if activity.get("avg_steps") is not None:
                lines.append(f"- **Avg Steps:** {activity['avg_steps']:,}")
            if activity.get("steps_trend") is not None:
                direction = "↑" if activity["steps_trend"] > 0 else "↓" if activity["steps_trend"] < 0 else "→"
                lines.append(f"- **Steps Trend:** {direction} {abs(activity['steps_trend']):,}")
            if activity.get("avg_active_calories") is not None:
                lines.append(f"- **Avg Active Calories:** {activity['avg_active_calories']:,}")
            if activity.get("avg_score") is not None:
                lines.append(f"- **Avg Activity Score:** {activity['avg_score']}")
            lines.append("\n| Day | Steps | Active Cal | Score |")
            lines.append("|-----|-------|------------|-------|")
            # Most recent day at the top (descending by date)
            for d in sorted(
                activity.get("daily", []),
                key=lambda d: d.get("day") or "",
                reverse=True,
            ):
                steps = f"{d['steps']:,}" if d.get("steps") is not None else "—"
                cal = f"{d['active_calories']:,}" if d.get("active_calories") is not None else "—"
                score = d["score"] if d.get("score") is not None else "—"
                lines.append(f"| {d['day']} | {steps} | {cal} | {score} |")

    # Wellness (weekly only)
    if is_weekly:
        wellness = analyze_wellness(wellness_data or [])
        metadata["wellness"] = wellness
        lines.append("\n## Wellness")
        if wellness.get("error"):
            _empty(wellness["error"])
        else:
            for key, label in [("meditation", "Meditation"), ("sauna", "Sauna"), ("cold_plunge", "Cold Plunge")]:
                w = wellness[key]
                if not (w["sessions_this"] or w["sessions_last"]):
                    continue
                delta_total = w["delta_total_min"]
                arrow = "↑" if delta_total > 0 else "↓" if delta_total < 0 else "→"
                delta_str = f"{arrow}{abs(delta_total)}min" if delta_total else "flat"
                session_word = "session" if w["sessions_this"] == 1 else "sessions"
                parts = [
                    f"{w['sessions_this']} {session_word} this wk (vs {w['sessions_last']})",
                    f"{w['total_min_this']}min total ({delta_str})",
                ]
                if w["avg_min_this"] is not None:
                    avg_part = f"avg {w['avg_min_this']}min"
                    if w.get("avg_temp_f_this") is not None:
                        avg_part += f" @ {w['avg_temp_f_this']:g}°F"
                    parts.append(avg_part)
                if key == "meditation":
                    split = w.get("style_split", {})
                    if split.get("Seated") or split.get("Walking"):
                        parts.append(f"Seated {split.get('Seated', 0)} / Walking {split.get('Walking', 0)}")
                lines.append(f"- **{label}:** " + " · ".join(parts))

            if wellness.get("daily"):
                lines.append("\n| Date | Meditation | Sauna | Cold Plunge |")
                lines.append("|------|-----------|-------|-------------|")
                for d in wellness["daily"]:
                    lines.append(
                        f"| {d['date']} | {d['meditation'] or '—'} | "
                        f"{d['sauna'] or '—'} | {d['cold_plunge'] or '—'} |"
                    )

    # Bodyweight
    weight = None
    if weight_entries is not None or is_weekly:
        weight = analyze_weight(weight_entries or [])
        metadata["weight"] = weight
        lines.append("\n## Bodyweight")
        if weight.get("error"):
            _empty("No bodyweight entries logged this week.")
        else:
            lines.append(f"- **Current:** {weight['current']} lbs")
            lines.append(f"- **4-week avg:** {weight['weekly_avg']} lbs")
            lines.append(f"- **Direction:** {weight['direction']}")
            if weight.get("rate_per_week") is not None:
                lines.append(f"- **Rate:** {weight['rate_per_week']} lbs/week")

    # Blood Pressure
    if bp_entries is not None or is_weekly:
        lines.append("\n## Blood Pressure")
        if not bp_entries:
            _empty("No blood pressure readings captured this week.")
        else:
            bp = analyze_bp(bp_entries, weekly=is_weekly, baselines=baselines)
            metadata["bp"] = bp
            if bp.get("error"):
                _empty("No blood pressure readings captured this week.")
            else:
                def _avg_line(label, sys_key, dia_key, hr_key):
                    if bp.get(sys_key) and bp.get(dia_key):
                        hr = f" · {bp[hr_key]} bpm" if bp.get(hr_key) else ""
                        lines.append(f"- **{label}:** {bp[sys_key]}/{bp[dia_key]} mmHg{hr}")

                if not bp.get("daily") and is_weekly:
                    _empty("No blood pressure readings captured this week.")
                _avg_line("AM Avg", "avg_systolic_am", "avg_diastolic_am", "avg_hr_am")
                _avg_line("PM Avg", "avg_systolic_pm", "avg_diastolic_pm", "avg_hr_pm")
                if bp.get("systolic_trend"):
                    t = bp["systolic_trend"]
                    lines.append(f"- **Systolic Trend:** {t['arrow']} {t['delta']} mmHg vs last week")
                if bp.get("diastolic_trend"):
                    t = bp["diastolic_trend"]
                    lines.append(f"- **Diastolic Trend:** {t['arrow']} {t['delta']} mmHg vs last week")
                if bp.get("hr_trend"):
                    t = bp["hr_trend"]
                    lines.append(f"- **Resting HR Trend:** {t['arrow']} {t['delta']} bpm vs last week")
                if bp.get("flags"):
                    for f in bp["flags"]:
                        lines.append(f"- ⚠️ {f}")
                if bp.get("daily"):
                    lines.append("\n| Date | AM (sys/dia) | PM (sys/dia) |")
                    lines.append("|------|-------------|-------------|")
                    for d in bp["daily"]:
                        lines.append(f"| {d['date']} | {d['am']} | {d['pm']} |")
                    noted = [d for d in bp["daily"] if d.get("notes")]
                    if noted:
                        lines.append("\n**Notes:**")
                        for d in noted:
                            lines.append(f"- {d['date']} — {d['notes']}")
                if bp.get("standing"):
                    def _win(s):
                        if not s:
                            return "—"
                        hr = f" · {s['hr']}" if s.get("hr") else ""
                        return f"{s['systolic']}/{s['diastolic']}{hr}"

                    lines.append("\n**Averages** (sys/dia · HR)")
                    lines.append("\n| Window | AM | PM |")
                    lines.append("|--------|----|----|")
                    for w in bp["standing"]:
                        lines.append(f"| {w['label']} | {_win(w['am'])} | {_win(w['pm'])} |")

    # New files in Health folder (weekly only)
    if is_weekly:
        lines.append("\n## What's New in Health Folder")
        has_changes = new_files and (new_files.get("new") or new_files.get("modified"))
        if not has_changes:
            _empty("No new or modified files this week.")
        else:
            for f in new_files.get("new", []):
                lines.append(f"- **New:** {f}")
            for f in new_files.get("modified", []):
                lines.append(f"- **Modified:** {f}")
            if new_files.get("summaries"):
                for s in new_files["summaries"]:
                    lines.append(f"\n### {s['file']}")
                    lines.append(f"```\n{s['preview']}\n```")

    # Blood tests longitudinal (weekly only). Suppressed once these results
    # have already been shown in a prior weekly email (see show_blood_tests).
    if is_weekly and show_blood_tests:
        lines.append("\n## Blood Test Trends")
        has_trends = False
        if blood_tests:
            for marker, history in blood_tests.items():
                if len(history) < 2:
                    continue
                has_trends = True
                lines.append(f"\n### {marker}")
                lines.append(f"| Date | Value | Flag |")
                lines.append(f"|------|-------|------|")
                for h in history:
                    flag_icon = "✅" if h["flag"] == "normal" else "⚠️"
                    lines.append(f"| {h['date']} | {h['value']} {h['unit']} | {flag_icon} {h['flag']} |")
        if not has_trends:
            _empty("No blood test history available.")

        # Add explanations for the latest test if parsed data is available
        if blood_tests_parsed:
            try:
                from blood_tests import explain_results, compare_to_history
                latest = max(blood_tests_parsed, key=lambda t: t.get("date", ""))
                if latest.get("results"):
                    explanation = explain_results(latest)
                    if explanation:
                        lines.append("\n## Latest Results Explained")
                        lines.append(explanation)
                    # Pass the longitudinal view we already have so this works
                    # on Cloud Run, where re-loading from the local JSON is empty.
                    comparison = compare_to_history(latest, longitudinal=blood_tests)
                    if comparison:
                        lines.append(f"\n{comparison}")
            except ImportError:
                pass

    # Previous responses context (weekly only)
    if responses and report_type == "weekly":
        rendered = []
        for r in responses[-3:]:
            if isinstance(r, dict):
                date_str = r.get("date") or r.get("timestamp") or ""
                question = r.get("question") or r.get("q") or ""
                answer = r.get("answer") or r.get("response") or r.get("a") or ""
                header = f"**{date_str}** — " if date_str else ""
                if question:
                    rendered.append(f"- {header}Q: {question}")
                    if answer:
                        rendered.append(f"  A: {answer}")
                elif answer:
                    rendered.append(f"- {header}{answer}")
            elif r:
                rendered.append(f"- {r}")
        if rendered:
            lines.append("\n## Your Previous Responses")
            lines.extend(rendered)

    # Cross-source insights
    try:
        from correlate import generate_insights
        insights = generate_insights(
            sleep_data=sleep_data,
            hrv_data=hrv_rhr_data,
            workouts=workouts,
            sleep_analysis=metadata.get("sleep"),
            heart_analysis=metadata.get("heart"),
            exercise_analysis=exercise,
            weight_analysis=weight,
            wellness_analysis=metadata.get("wellness"),
            blood_tests_parsed=blood_tests_parsed,
            readiness_analysis=metadata.get("readiness"),
            report_type=report_type,
        )
        if insights:
            metadata["insights"] = insights
            lines.append("\n## Insights")
            for insight in insights:
                lines.append(f"- {insight}")
    except Exception as e:
        print(f"[analyze] Insights skipped: {e}")

    # Questions & Suggestions (weekly only)
    if report_type == "weekly":
        sleep_a = metadata.get("sleep", {})
        exercise_a = exercise or {}
        weight_a = weight or {}
        heart_a = metadata.get("heart", {})

        questions = generate_questions(sleep_a, exercise_a, weight_a, heart_a)
        suggestions = generate_suggestions(sleep_a, exercise_a, weight_a, heart_a)

        if questions:
            lines.append("\n## Questions")
            for q in questions:
                lines.append(q)

        if suggestions:
            lines.append("\n## Suggestions")
            for s in suggestions:
                lines.append(f"- {s}")

    if report_type == "daily":
        trend_note = "_Trends compare the latest day to the previous day. "
    else:
        trend_note = "_Trends compare this week to last week. "
    lines.append(f"\n---\n{trend_note}"
                 f"↑ = increasing, ↓ = decreasing, → = flat._")
    lines.append(f"\n_Generated by Health OS on {today}_")
    return "\n".join(lines), metadata
