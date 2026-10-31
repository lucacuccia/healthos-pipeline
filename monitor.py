"""Health OS — Persistent monitoring with configurable anomaly detection.

Runs health checks against recent data and sends alerts via Telegram
when thresholds are crossed. Designed to run more frequently than
daily reports (e.g., every few hours via launchd) for faster feedback.

Thresholds can be customized via MONITOR_* env vars in .env.
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
ALERT_LOG = BASE_DIR / "data" / "monitor_alerts.json"


# =============================================================================
# Configurable thresholds (override via .env MONITOR_* vars)
# =============================================================================

def _threshold(name, default):
    """Read a MONITOR_* threshold from env, falling back to default."""
    val = os.getenv(f"MONITOR_{name}")
    if val is not None:
        try:
            return type(default)(val)
        except (ValueError, TypeError):
            pass
    return default


def _get_thresholds():
    """Load all thresholds, applying env overrides.

    These are fallbacks — when a personal baseline exists (baselines.py),
    checks fire on deviation from the 60-day norm instead.
    Note: MONITOR_RECOVERY_LOW is on a 0-100 scale (was 0-10 before the
    switch to Oura readiness).
    """
    return {
        "sleep_score_low": _threshold("SLEEP_SCORE_LOW", 65),
        "hrv_drop": _threshold("HRV_DROP", 15),
        "rhr_spike": _threshold("RHR_SPIKE", 5),
        "recovery_low": _threshold("RECOVERY_LOW", 40),
        "missed_workouts_days": _threshold("MISSED_WORKOUTS_DAYS", 5),
        "weight_change_lbs": _threshold("WEIGHT_CHANGE_LBS", 3.0),
    }


# =============================================================================
# Alert deduplication — don't spam the same alert within a cooldown window
# =============================================================================

def _load_alert_log():
    """Load previous alerts from JSON."""
    if ALERT_LOG.exists():
        try:
            return json.loads(ALERT_LOG.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_alert_log(log):
    """Save alert log to JSON."""
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    ALERT_LOG.write_text(json.dumps(log, indent=2))


def _should_alert(alert_key, cooldown_hours=12):
    """Check if enough time has passed since the last alert of this type."""
    log = _load_alert_log()
    last = log.get(alert_key)
    if last:
        try:
            from datetime import datetime
            last_time = datetime.fromisoformat(last)
            if (datetime.now() - last_time).total_seconds() < cooldown_hours * 3600:
                return False
        except (ValueError, TypeError):
            pass
    return True


def _record_alert(alert_key):
    """Record that an alert was sent."""
    from datetime import datetime
    log = _load_alert_log()
    log[alert_key] = datetime.now().isoformat()
    _save_alert_log(log)


# =============================================================================
# Check functions — each returns (alert_key, message) or None
# =============================================================================

def _check_sleep(sleep_data, thresholds, baselines=None):
    """Alert if last night's sleep score is critically low.

    Uses the personal 60-day baseline when available, fixed threshold otherwise.
    """
    if not sleep_data:
        return None

    last = sleep_data[-1]
    score = last.get("score")
    if score is None:
        return None

    baseline = (baselines or {}).get("sleep_score")
    if baseline:
        from baselines import is_abnormal, describe
        abnormal, _ = is_abnormal(score, baseline, direction="low")
        if abnormal:
            return ("sleep_low", f"Sleep score dropped to {score} — well below your 60-day norm ({describe(baseline)})")
        return None

    if score < thresholds["sleep_score_low"]:
        return ("sleep_low", f"Sleep score dropped to {score} (threshold: {thresholds['sleep_score_low']})")

    return None


def _check_hrv(hrv_data, thresholds, baselines=None):
    """Alert if HRV dropped significantly below the personal norm."""
    if not hrv_data:
        return None

    latest = hrv_data[-1].get("avg_hrv")
    if latest is None:
        return None

    baseline = (baselines or {}).get("hrv")
    if baseline:
        from baselines import is_abnormal, describe
        abnormal, _ = is_abnormal(latest, baseline, direction="low")
        if abnormal:
            return ("hrv_drop", f"HRV dropped to {latest:.0f}ms — well below your 60-day norm ({describe(baseline, unit='ms')})")
        return None

    # Fallback: average of the recent window (minus latest) as a rough baseline
    if len(hrv_data) < 3:
        return None
    recent_vals = [d["avg_hrv"] for d in hrv_data[:-1] if d.get("avg_hrv") is not None]
    if not recent_vals:
        return None
    recent_avg = sum(recent_vals) / len(recent_vals)
    drop = recent_avg - latest

    if drop >= thresholds["hrv_drop"]:
        return ("hrv_drop", f"HRV dropped to {latest:.0f}ms (baseline: {recent_avg:.0f}ms, drop: {drop:.0f}ms)")

    return None


def _check_rhr(hrv_data, thresholds, baselines=None):
    """Alert if resting heart rate spiked above the personal norm."""
    if not hrv_data:
        return None

    latest = hrv_data[-1].get("lowest_hr")
    if latest is None:
        return None

    baseline = (baselines or {}).get("rhr")
    if baseline:
        from baselines import is_abnormal, describe
        abnormal, _ = is_abnormal(latest, baseline, direction="high")
        if abnormal:
            return ("rhr_spike", f"Resting HR spiked to {latest}bpm — well above your 60-day norm ({describe(baseline, unit='bpm')})")
        return None

    if len(hrv_data) < 3:
        return None
    recent_vals = [d["lowest_hr"] for d in hrv_data[:-1] if d.get("lowest_hr") is not None]
    if not recent_vals:
        return None
    recent_avg = sum(recent_vals) / len(recent_vals)
    spike = latest - recent_avg

    if spike >= thresholds["rhr_spike"]:
        return ("rhr_spike", f"Resting HR spiked to {latest}bpm (baseline: {recent_avg:.0f}bpm, +{spike:.0f}bpm)")

    return None


def _check_recovery(sleep_data, hrv_data, thresholds, readiness_data=None):
    """Alert if the recovery score is critically low.

    Consumes the numeric score from correlate.recovery_status — Oura readiness
    when available, legacy heuristic otherwise. Threshold is on a 0-100 scale.
    """
    try:
        from correlate import recovery_status
        from analyze import analyze_sleep, analyze_heart_metrics, analyze_readiness

        readiness_analysis = analyze_readiness(readiness_data) if readiness_data else None
        sleep_analysis = analyze_sleep(sleep_data) if sleep_data else None
        heart_analysis = analyze_heart_metrics(hrv_data) if hrv_data else None

        status = recovery_status(readiness_analysis, sleep_analysis, heart_analysis)
        if not status:
            return None

        if status["score"] <= thresholds["recovery_low"]:
            return ("recovery_low", f"Recovery score is {status['score']}/100 — consider rest or light activity only")

    except Exception:
        pass

    return None


def _check_missed_workouts(workouts, thresholds, fetch_failed=False):
    """Alert if no workouts for N consecutive days.

    `fetch_failed` distinguishes "the fetch errored" from "genuinely no
    workouts logged" — the former gets its own alert instead of being
    misreported as missing data (#69).
    """
    if fetch_failed:
        return ("workout_source_unreachable", "Workout data source unreachable — couldn't check for missed workouts")

    if workouts:
        workout_dates = set()
        for w in workouts:
            d = w.get("date") or w.get("day")
            if d:
                if isinstance(d, str):
                    workout_dates.add(d[:10])
                else:
                    workout_dates.add(d.isoformat())

        if workout_dates:
            from datetime import datetime
            latest = max(datetime.strptime(d, "%Y-%m-%d").date() for d in workout_dates)
            gap = (date.today() - latest).days
            if gap < thresholds["missed_workouts_days"]:
                return None
            return ("missed_workouts", f"No workouts in {gap} days (threshold: {thresholds['missed_workouts_days']})")

    # No workout data at all — only alert if source is configured
    workout_source = os.getenv("WORKOUT_SOURCE", "firestore")
    if workout_source != "manual":
        return ("missed_workouts", f"No workout data found for the past week")

    return None


def _check_weight(weight_entries, thresholds, baselines=None):
    """Alert on rapid weight change (or deviation from the 60-day norm)."""
    if not weight_entries:
        return None

    sorted_entries = sorted(weight_entries, key=lambda e: str(e.get("date", "")))
    last = sorted_entries[-1].get("weight")

    baseline = (baselines or {}).get("weight")
    if baseline and last is not None:
        from baselines import is_abnormal, describe
        abnormal, z = is_abnormal(last, baseline, direction="both")
        if abnormal:
            direction = "up" if z > 0 else "down"
            return ("weight_change", f"Weight is {direction} at {last:.1f}lbs — outside your 60-day norm ({describe(baseline, unit='lbs', decimals=1)})")
        return None

    if len(sorted_entries) < 2:
        return None
    first = sorted_entries[0].get("weight")
    if first is None or last is None:
        return None

    change = last - first
    if abs(change) >= thresholds["weight_change_lbs"]:
        direction = "up" if change > 0 else "down"
        return ("weight_change", f"Weight moved {direction} {abs(change):.1f}lbs in the past week (threshold: {thresholds['weight_change_lbs']}lbs)")

    return None


# =============================================================================
# Main entry point
# =============================================================================

def run_monitor():
    """Run all health checks and send alerts for any anomalies."""
    from sources import get_sleep_data, get_hrv_data, get_workouts, get_weight, get_readiness_data

    print("[monitor] Running health checks...")

    today = date.today()
    start = today - timedelta(days=7)

    thresholds = _get_thresholds()

    # Personal baselines — shared "abnormal" definition with analyze.py.
    # Fail-safe: missing baselines just mean the fixed thresholds apply.
    baselines = {}
    try:
        from baselines import get_baselines
        baselines = get_baselines()
    except Exception as e:
        print(f"[monitor] Baselines unavailable, using fixed thresholds: {e}")

    # Fetch data (silently skip failures)
    sleep_data = None
    hrv_data = None
    workouts = None
    weight_entries = None
    readiness_data = None

    try:
        sleep_data = get_sleep_data(start, today)
    except Exception as e:
        print(f"[monitor] Could not fetch sleep data: {e}")

    try:
        hrv_data = get_hrv_data(days=7)
    except Exception as e:
        print(f"[monitor] Could not fetch HRV data: {e}")

    workouts_fetch_failed = False
    try:
        workouts = get_workouts(start, today)
    except Exception as e:
        workouts_fetch_failed = True
        print(f"[monitor] Could not fetch workouts: {e}")

    try:
        weight_entries = get_weight(start, today)
    except Exception as e:
        print(f"[monitor] Could not fetch weight: {e}")

    try:
        readiness_data = get_readiness_data(start, today)
    except Exception as e:
        print(f"[monitor] Could not fetch readiness: {e}")

    # Run checks
    checks = [
        _check_sleep(sleep_data, thresholds, baselines),
        _check_hrv(hrv_data, thresholds, baselines),
        _check_rhr(hrv_data, thresholds, baselines),
        _check_recovery(sleep_data, hrv_data, thresholds, readiness_data),
        _check_missed_workouts(workouts, thresholds, fetch_failed=workouts_fetch_failed),
        _check_weight(weight_entries, thresholds, baselines),
    ]

    alerts = [c for c in checks if c is not None]

    if not alerts:
        print("[monitor] All clear — no anomalies detected")
        return []

    # Filter by cooldown (don't repeat alerts within 12 hours)
    new_alerts = []
    for key, message in alerts:
        if _should_alert(key, cooldown_hours=12):
            new_alerts.append((key, message))
        else:
            print(f"[monitor] Skipping (cooldown): {message}")

    if not new_alerts:
        print("[monitor] Alerts detected but within cooldown — skipping")
        return []

    # Send via Telegram
    alert_text = "🔔 *Health OS Alert*\n\n" + "\n".join(f"⚠️ {msg}" for _, msg in new_alerts)
    print(f"[monitor] Sending {len(new_alerts)} alert(s)...")

    try:
        from notify import send_telegram
        send_telegram(alert_text)
    except Exception as e:
        print(f"[monitor] Could not send Telegram alert: {e}")

    # Record alerts to prevent re-sending
    for key, message in new_alerts:
        _record_alert(key)
        print(f"[monitor] Alert: {message}")

    return new_alerts
