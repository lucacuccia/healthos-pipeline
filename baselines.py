"""Health OS — Personal baselines.

Computes rolling per-metric baselines (mean ± SD over ~60 days) so flags and
alerts fire on deviation from *your* normal instead of universal constants.
Shared by analyze.py (report flags) and monitor.py (Telegram alerts) — this is
the single definition of "abnormal".

Env overrides:
  BASELINE_SD_THRESHOLD  — SDs from the mean that count as abnormal (default 1.75)
  BASELINE_MIN_SAMPLES   — non-null samples required to trust a baseline (default 14)
"""

import os
from datetime import date, timedelta

DEFAULT_SD_THRESHOLD = 1.75
DEFAULT_MIN_SAMPLES = 14
DEFAULT_WINDOW_DAYS = 60


def _env_float(name, default):
    val = os.getenv(name)
    if val is not None:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
    return default


def sd_threshold():
    return _env_float("BASELINE_SD_THRESHOLD", DEFAULT_SD_THRESHOLD)


def min_samples():
    return int(_env_float("BASELINE_MIN_SAMPLES", DEFAULT_MIN_SAMPLES))


def compute_baseline(values):
    """Compute {mean, sd, n} from a list of numbers (Nones ignored).

    Returns None when there are too few samples to trust a personal baseline
    (< BASELINE_MIN_SAMPLES) — callers should fall back to fixed constants.
    """
    nums = [v for v in values or [] if v is not None]
    n = len(nums)
    if n < min_samples():
        return None
    mean = sum(nums) / n
    variance = sum((v - mean) ** 2 for v in nums) / (n - 1)
    sd = variance ** 0.5
    return {"mean": mean, "sd": sd, "n": n}


def deviation(value, baseline):
    """Z-score of value against baseline, or None if not computable."""
    if value is None or not baseline or not baseline.get("sd"):
        return None
    return (value - baseline["mean"]) / baseline["sd"]


def is_abnormal(value, baseline, direction="both", threshold=None):
    """One shared definition of abnormal: deviation beyond N SDs in the bad direction.

    direction: "low" (bad when below, e.g. HRV/sleep), "high" (bad when above,
    e.g. RHR/systolic), or "both" (e.g. weight).
    Returns (abnormal: bool, z: float) or (False, None) when not computable.
    """
    z = deviation(value, baseline)
    if z is None:
        return False, None
    if threshold is None:
        threshold = sd_threshold()
    if direction == "low":
        return z < -threshold, z
    if direction == "high":
        return z > threshold, z
    return abs(z) > threshold, z


def describe(baseline, unit="", decimals=0):
    """Format a baseline as '48 ± 7 ms' for flag copy."""
    mean = round(baseline["mean"], decimals) if decimals else round(baseline["mean"])
    sd = round(baseline["sd"], decimals) if decimals else round(baseline["sd"])
    text = f"{mean:g} ± {sd:g}"
    return f"{text} {unit}".strip()


def get_baselines(days=DEFAULT_WINDOW_DAYS):
    """Fetch ~60 days of history and compute per-metric baselines.

    Returns {"hrv", "rhr", "sleep_score", "sleep_duration", "weight"} — each a
    {mean, sd, n} dict or None. Every fetch is fail-safe: an error just leaves
    that metric's baseline as None so callers fall back to constants.
    """
    result = {
        "hrv": None,
        "rhr": None,
        "sleep_score": None,
        "sleep_duration": None,
        "weight": None,
        "systolic": None,
    }

    today = date.today()
    start = today - timedelta(days=days)

    try:
        from sources import get_hrv_data
        hrv_rhr = get_hrv_data(days=days) or []
        result["hrv"] = compute_baseline([d.get("avg_hrv") for d in hrv_rhr])
        result["rhr"] = compute_baseline([d.get("lowest_hr") for d in hrv_rhr])
    except Exception as e:
        print(f"[baselines] HRV/RHR baseline unavailable: {e}")

    try:
        from sources import get_sleep_data
        sleep = get_sleep_data(start, today) or []
        result["sleep_score"] = compute_baseline([s.get("score") for s in sleep])
    except Exception as e:
        print(f"[baselines] Sleep score baseline unavailable: {e}")

    try:
        from sources import get_sleep_durations
        durations = get_sleep_durations(days=days) or []
        result["sleep_duration"] = compute_baseline(
            [d.get("total_sleep_sec") for d in durations]
        )
    except Exception as e:
        print(f"[baselines] Sleep duration baseline unavailable: {e}")

    try:
        from sources import get_bp_data
        bp = get_bp_data(start, today) or []
        # AM readings only — consistent context (pre-coffee, rested)
        result["systolic"] = compute_baseline([e.get("systolic_am") for e in bp])
    except Exception as e:
        print(f"[baselines] Systolic baseline unavailable: {e}")

    try:
        from sources import get_weight
        entries = get_weight(start, today) or []
        result["weight"] = compute_baseline([e.get("weight") for e in entries])
    except Exception as e:
        print(f"[baselines] Weight baseline unavailable: {e}")

    return result
