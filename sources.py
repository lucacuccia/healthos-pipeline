"""Health OS — Unified data source layer.

Centralizes all health data fetching with configurable source preferences
and automatic fallback chains. Consumers (main.py, analyze.py) get data
without knowing which provider served it.
"""

from config import SLEEP_SOURCE, WORKOUT_SOURCE, WEIGHT_SOURCE


def _try_sources(sources_list, label="data"):
    """Try each (name, fetch_fn) in order. Return first success or None."""
    for name, fetch_fn in sources_list:
        try:
            result = fetch_fn()
            print(f"[sources] {label}: loaded from {name}")
            return result
        except Exception as e:
            print(f"[sources] {label}: {name} failed ({e})")
    print(f"[sources] {label}: all sources failed")
    return None


# ---------------------------------------------------------------------------
# Sleep
# ---------------------------------------------------------------------------

def get_sleep_data(start, end):
    """Fetch daily sleep data for the given date range."""
    if SLEEP_SOURCE == "oura":
        from oura import get_sleep
        return _try_sources([("oura", lambda: get_sleep(start, end))], label="sleep")
    elif SLEEP_SOURCE == "apple_health":
        from apple_health import get_sleep_data as _ah_sleep
        return _try_sources([("apple_health", lambda: _ah_sleep(start, end))], label="sleep")
    elif SLEEP_SOURCE == "manual":
        from manual_entry import get_sleep_data as _man_sleep
        return _try_sources([("manual", lambda: _man_sleep(start, end))], label="sleep")
    print(f"[sources] Unknown SLEEP_SOURCE: {SLEEP_SOURCE}")
    return None


def get_hrv_data(days=7):
    """Fetch HRV and resting heart rate data. Follows SLEEP_SOURCE (same wearable)."""
    if SLEEP_SOURCE == "oura":
        from oura import get_hrv_rhr
        return _try_sources([("oura", lambda: get_hrv_rhr(days=days))], label="hrv")
    elif SLEEP_SOURCE == "apple_health":
        from apple_health import get_hrv_rhr as _ah_hrv
        return _try_sources([("apple_health", lambda: _ah_hrv(days=days))], label="hrv")
    elif SLEEP_SOURCE == "manual":
        from manual_entry import get_hrv_rhr as _man_hrv
        return _try_sources([("manual", lambda: _man_hrv(days=days))], label="hrv")
    print(f"[sources] Unknown SLEEP_SOURCE for HRV: {SLEEP_SOURCE}")
    return None


def get_sleep_durations(days=7):
    """Fetch sleep phase durations (deep, REM, total). Follows SLEEP_SOURCE."""
    if SLEEP_SOURCE == "oura":
        from oura import get_sleep_durations as _oura_durations
        return _try_sources([("oura", lambda: _oura_durations(days=days))], label="sleep_durations")
    elif SLEEP_SOURCE == "apple_health":
        from apple_health import get_sleep_durations as _ah_durations
        return _try_sources([("apple_health", lambda: _ah_durations(days=days))], label="sleep_durations")
    elif SLEEP_SOURCE == "manual":
        from manual_entry import get_sleep_durations as _man_durations
        return _try_sources([("manual", lambda: _man_durations(days=days))], label="sleep_durations")
    print(f"[sources] Unknown SLEEP_SOURCE for durations: {SLEEP_SOURCE}")
    return None


def get_readiness_data(start, end):
    """Fetch daily readiness data. Oura-only — other sources have no equivalent."""
    if SLEEP_SOURCE == "oura":
        from oura import get_daily_readiness
        return _try_sources([("oura", lambda: get_daily_readiness(start, end))], label="readiness")
    return None


def get_activity_data(start, end):
    """Fetch daily activity data (steps, calories). Oura-only."""
    if SLEEP_SOURCE == "oura":
        from oura import get_daily_activity
        return _try_sources([("oura", lambda: get_daily_activity(start, end))], label="activity")
    return None


# ---------------------------------------------------------------------------
# Exercise & Weight
# ---------------------------------------------------------------------------

def get_workouts(start, end):
    """Fetch workout data with configurable source and fallback."""
    sources = []

    if WORKOUT_SOURCE == "firestore":
        from firestore_client import get_workouts as _fs_workouts
        sources.append(("firestore", lambda: _fs_workouts(start, end)))
        # Auto-fallback to sheets
        from sheets import get_workouts as _sh_workouts
        sources.append(("sheets", lambda: _sh_workouts(start, end)))
    elif WORKOUT_SOURCE == "sheets":
        from sheets import get_workouts as _sh_workouts
        sources.append(("sheets", lambda: _sh_workouts(start, end)))
    elif WORKOUT_SOURCE == "apple_health":
        from apple_health import get_workouts as _ah_workouts
        sources.append(("apple_health", lambda: _ah_workouts(start, end)))
    elif WORKOUT_SOURCE == "manual":
        from manual_entry import get_workouts as _man_workouts
        sources.append(("manual", lambda: _man_workouts(start, end)))
    else:
        print(f"[sources] Unknown WORKOUT_SOURCE: {WORKOUT_SOURCE}")
        return None

    return _try_sources(sources, label="workouts")


def get_weight(start, end):
    """Fetch body weight data with configurable source and fallback."""
    sources = []

    if WEIGHT_SOURCE == "firestore":
        from firestore_client import get_bodyweight as _fs_weight
        sources.append(("firestore", lambda: _fs_weight(start, end)))
        # Auto-fallback to sheets
        from sheets import get_bodyweight as _sh_weight
        sources.append(("sheets", lambda: _sh_weight(start, end)))
    elif WEIGHT_SOURCE == "sheets":
        from sheets import get_bodyweight as _sh_weight
        sources.append(("sheets", lambda: _sh_weight(start, end)))
    elif WEIGHT_SOURCE == "apple_health":
        from apple_health import get_bodyweight as _ah_weight
        sources.append(("apple_health", lambda: _ah_weight(start, end)))
    elif WEIGHT_SOURCE == "manual":
        from manual_entry import get_bodyweight as _man_weight
        sources.append(("manual", lambda: _man_weight(start, end)))
    else:
        print(f"[sources] Unknown WEIGHT_SOURCE: {WEIGHT_SOURCE}")
        return None

    return _try_sources(sources, label="weight")


def get_extras(start, end):
    """Fetch wellness extras (meditation, sauna, cold plunge). Always Firestore."""
    from firestore_client import get_extras as _fs_extras
    return _try_sources([("firestore", lambda: _fs_extras(start, end))], label="extras")


# ---------------------------------------------------------------------------
# Blood Tests
# ---------------------------------------------------------------------------

def get_blood_tests():
    """Parse all blood test PDFs and return (longitudinal_view, parsed_tests).

    On Cloud Run (no local Drive mount) the PDF parse returns an empty list;
    we fall back to the latest test date persisted in Firestore so the
    6-month reminder can still fire. The fallback returns a one-element stub
    list whose only field is `date` — enough for correlate.blood_test_reminder.

    Returns:
        tuple: (longitudinal dict|None, list of parsed test dicts) or None on failure
    """
    from blood_tests import parse_all_blood_tests, get_longitudinal_view

    def _fetch_local():
        all_tests = parse_all_blood_tests()
        longitudinal = get_longitudinal_view()
        return longitudinal, all_tests

    def _fetch_firestore():
        from firestore_client import get_blood_tests_data, get_latest_blood_test_date
        longitudinal, all_tests = get_blood_tests_data()
        if all_tests:
            return longitudinal, all_tests
        # Older data: only the latest date was mirrored. Still enough for the
        # 6-month reminder, even though trends/explanations won't render.
        d = get_latest_blood_test_date()
        if not d:
            raise RuntimeError("no blood test data in Firestore")
        return None, [{"date": d.isoformat()}]

    result = _try_sources([("pdf", _fetch_local)], label="blood_tests")
    if result is None:
        return None
    longitudinal, all_tests = result
    if all_tests:
        return result

    # Local parse found nothing (e.g. Cloud Run with no Drive mount) — read the
    # full data the latest local run mirrored to Firestore.
    fallback = _try_sources([("firestore", _fetch_firestore)], label="blood_tests_fallback")
    return fallback if fallback is not None else result


# ---------------------------------------------------------------------------
# Blood Pressure
# ---------------------------------------------------------------------------

def get_bp_data(start, end):
    """Fetch blood pressure data — Firestore (iOS app) first, Sheet fallback."""
    from firestore_client import get_bp_data as _fs_bp
    from sheets import get_bp_data as _sh_bp
    return _try_sources([
        ("firestore", lambda: _fs_bp(start, end)),
        ("sheets", lambda: _sh_bp(start, end)),
    ], label="bp_data")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

def get_responses(limit=5):
    """Fetch user responses from Cloudflare Worker via Sheets."""
    from sheets import get_responses as _sh_responses
    return _try_sources([("sheets", lambda: _sh_responses(limit=limit))], label="responses")


# ---------------------------------------------------------------------------
# Data freshness (Oura-specific, but routed through sources for future use)
# ---------------------------------------------------------------------------

def wait_for_fresh_data(max_wait_minutes=30, interval_minutes=5, report_type="daily"):
    """Wait for fresh sleep data from the configured source."""
    if SLEEP_SOURCE == "oura":
        from oura import wait_for_fresh_data as _wait
        return _wait(max_wait_minutes=max_wait_minutes, interval_minutes=interval_minutes,
                      report_type=report_type)
    # Non-Oura sources don't need freshness checks
    return True


def has_fresh_sleep_data(target_date=None):
    """Check if fresh sleep data is available from the configured source."""
    if SLEEP_SOURCE == "oura":
        from oura import has_fresh_sleep_data as _has_fresh
        return _has_fresh(target_date) if target_date else _has_fresh()
    # Non-Oura sources are assumed fresh
    return True
