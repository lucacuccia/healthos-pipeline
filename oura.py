"""Oura Ring API v2 client with local caching."""

import json
import time
import requests
from datetime import date, timedelta
from config import OURA_TOKEN, OURA_CACHE_DIR

BASE_URL = "https://api.ouraring.com/v2/usercollection"
HEADERS = {"Authorization": f"Bearer {OURA_TOKEN}"}


def _cache_path(endpoint, start, end):
    return OURA_CACHE_DIR / f"{endpoint}_{start}_{end}.json"


def _fetch(endpoint, start_date, end_date):
    """Fetch from Oura API with caching.

    Skips cache for date ranges that include today, since data may still be syncing.
    See the +1 day comment below for Oura's end_date semantics.
    """
    includes_today = start_date <= date.today() <= end_date

    cache = _cache_path(endpoint, start_date, end_date)
    if cache.exists() and not includes_today:
        return json.loads(cache.read_text())

    # Oura v2 end_date semantics differ per endpoint (verified against the live API
    # 2026-07-31): daily_sleep and daily_readiness include the end date, while sleep
    # and daily_activity exclude it. Adding a day is required for the exclusive ones
    # and only over-fetches a day we already want for the inclusive ones, so it is
    # applied uniformly here. Do not remove it — dropping it silently loses the most
    # recent day from sleep periods and activity.
    # NOTE: has_fresh_sleep_data() deliberately does NOT add a day; it queries
    # daily_sleep, which is inclusive. Keep the two in sync with reality, not with
    # each other.
    api_end_date = end_date + timedelta(days=1)
    url = f"{BASE_URL}/{endpoint}"
    params = {"start_date": str(start_date), "end_date": str(api_end_date)}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)

    if resp.status_code == 401:
        raise RuntimeError(
            "Oura API returned 401 — token is invalid or expired. "
            "Generate a new one at https://cloud.ouraring.com/personal-access-tokens"
        )
    resp.raise_for_status()

    data = resp.json().get("data", [])

    # Only cache if the date range is fully in the past
    if not includes_today:
        cache.write_text(json.dumps(data, indent=2))
    return data


def get_sleep(start_date=None, end_date=None):
    """Get daily sleep data. Returns list of dicts with sleep metrics."""
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=7)
    return _fetch("daily_sleep", start_date, end_date)



def get_sleep_periods(start_date=None, end_date=None):
    """Get detailed sleep period data (includes HRV and resting HR)."""
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=7)
    return _fetch("sleep", start_date, end_date)


def get_daily_readiness(start_date=None, end_date=None):
    """Get daily readiness data (score + contributors like hrv_balance, recovery_index)."""
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=7)
    return _fetch("daily_readiness", start_date, end_date)


def get_daily_activity(start_date=None, end_date=None):
    """Get daily activity data (score, steps, active/total calories)."""
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=7)
    return _fetch("daily_activity", start_date, end_date)


def _main_sleep_by_day(periods):
    """Pick one sleep period per day: the longest "long_sleep" (main sleep, not naps).

    Oura can return several long_sleep entries for the same day (e.g. a short
    early-morning segment after the main night). Keeping the longest one keeps
    HRV/RHR and duration metrics anchored to the same period.

    Returns dict of {day: period}.
    """
    by_day = {}
    for p in periods:
        if p.get("type") != "long_sleep":
            continue
        day = p.get("day")
        if not day:
            continue
        existing = by_day.get(day)
        if existing and (existing.get("total_sleep_duration") or 0) > (p.get("total_sleep_duration") or 0):
            continue
        by_day[day] = p
    return by_day


def get_hrv_rhr(days=7):
    """Extract daily HRV and resting heart rate from sleep periods.

    Returns list of dicts: [{day, avg_hrv, lowest_hr, avg_hr}, ...]
    """
    end = date.today()
    start = end - timedelta(days=days)
    periods = get_sleep_periods(start, end)

    results = [
        {
            "day": day,
            "avg_hrv": p.get("average_hrv"),
            "lowest_hr": p.get("lowest_heart_rate"),
            "avg_hr": p.get("average_heart_rate"),
        }
        for day, p in _main_sleep_by_day(periods).items()
    ]

    return sorted(results, key=lambda x: x["day"])


def get_sleep_durations(days=7):
    """Extract daily sleep durations from sleep periods (long_sleep only).

    Returns list of dicts: [{day, deep_sleep_sec, rem_sleep_sec, total_sleep_sec}, ...]
    """
    end = date.today()
    start = end - timedelta(days=days)
    periods = get_sleep_periods(start, end)

    results = [
        {
            "day": day,
            "deep_sleep_sec": p.get("deep_sleep_duration"),
            "rem_sleep_sec": p.get("rem_sleep_duration"),
            "total_sleep_sec": p.get("total_sleep_duration"),
        }
        for day, p in _main_sleep_by_day(periods).items()
    ]

    return sorted(results, key=lambda x: x["day"])



def has_fresh_sleep_data(target_date=None):
    """Check if Oura API has sleep data for the target date (default: last night).

    Makes a direct API call (bypasses cache) to check freshness.
    Returns True if data for the target date is present.
    """
    if target_date is None:
        target_date = date.today()

    # daily_sleep treats end_date as inclusive, so a single-day window is correct and
    # the missing +1 is not a bug. _fetch()'s +1 exists for the endpoints that treat
    # end_date as exclusive (sleep, daily_activity); mirroring it here would only
    # widen the window to a day the result filter below discards anyway.
    url = f"{BASE_URL}/daily_sleep"
    params = {"start_date": str(target_date), "end_date": str(target_date)}
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return any(d.get("day") == str(target_date) for d in data)
    except Exception as e:
        print(f"[oura] Freshness check failed: {e}")
        return False


def wait_for_fresh_data(max_wait_minutes=30, interval_minutes=5, report_type="daily"):
    """Wait until Oura has last night's sleep data, retrying periodically.

    Sends a Telegram nudge if data isn't immediately available.
    Returns True if fresh data became available, False if timed out.
    """
    target = date.today()
    label = {"daily": "daily", "weekly": "weekly", "full": "full"}.get(report_type, report_type)

    # First check — if data is already there, no wait needed
    if has_fresh_sleep_data(target):
        return True

    # Data not available — nudge via Telegram
    try:
        from notify import send_telegram
        emoji = "🗓️" if report_type == "weekly" else "☀️"
        send_telegram(
            f"{emoji} *Health OS*\n\n"
            f"Your {label} report is ready to generate but I don't have last night's sleep data yet.\n\n"
            f"Open the Oura app to sync your ring — I'll wait up to {max_wait_minutes} min and send "
            f"the report once your data comes through."
        )
    except Exception as e:
        print(f"[oura] Could not send sync reminder: {e}")

    # Now retry
    attempts = max_wait_minutes // interval_minutes
    for i in range(attempts):
        print(f"[oura] No sleep data for {target} yet — retrying in {interval_minutes} min "
              f"(attempt {i + 1}/{attempts})")
        time.sleep(interval_minutes * 60)
        if has_fresh_sleep_data(target):
            print(f"[oura] Fresh sleep data available after {(i + 1) * interval_minutes} min wait")
            return True

    print(f"[oura] No sleep data for {target} after {max_wait_minutes} min — skipping report")

    try:
        from notify import send_telegram
        send_telegram(
            f"⏳ *Health OS*\n\n"
            f"Couldn't get last night's sleep data after waiting {max_wait_minutes} min, "
            f"so I'm skipping the {label} report.\n\n"
            f"Sync your Oura ring and run `main.py --catchup` (or wait for the scheduled retry) "
            f"to send it once data's available."
        )
    except Exception:
        pass

    return False


