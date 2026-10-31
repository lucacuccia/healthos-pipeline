"""Apple Health export.xml parser.

Streaming XML parser for large Apple Health exports (1GB+).
Uses stdlib iterparse to keep memory usage flat.
"""

import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from collections import defaultdict
from config import APPLE_HEALTH_EXPORT


# Apple Health record type identifiers
_SLEEP = "HKCategoryTypeIdentifierSleepAnalysis"
_HRV = "HKQuantityTypeIdentifierHeartRateVariabilitySDNN"
_RESTING_HR = "HKQuantityTypeIdentifierRestingHeartRate"
_HEART_RATE = "HKQuantityTypeIdentifierHeartRate"
_BODY_MASS = "HKQuantityTypeIdentifierBodyMass"

# Sleep stage values (Apple Health uses these as Record values)
_DEEP_STAGES = {"HKCategoryValueSleepAnalysisAsleepDeep"}
_REM_STAGES = {"HKCategoryValueSleepAnalysisAsleepREM"}
_SLEEP_STAGES = {
    "HKCategoryValueSleepAnalysisAsleepCore",
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
    "HKCategoryValueSleepAnalysisAsleep",  # Pre-iOS 16 (no stage breakdown)
}

# Workout type prefix to friendly name
_WORKOUT_NAMES = {
    "HKWorkoutActivityTypeRunning": "Running",
    "HKWorkoutActivityTypeCycling": "Cycling",
    "HKWorkoutActivityTypeWalking": "Walking",
    "HKWorkoutActivityTypeSwimming": "Swimming",
    "HKWorkoutActivityTypeHiking": "Hiking",
    "HKWorkoutActivityTypeYoga": "Yoga",
    "HKWorkoutActivityTypeFunctionalStrengthTraining": "Strength Training",
    "HKWorkoutActivityTypeTraditionalStrengthTraining": "Strength Training",
    "HKWorkoutActivityTypeHighIntensityIntervalTraining": "HIIT",
    "HKWorkoutActivityTypeElliptical": "Elliptical",
    "HKWorkoutActivityTypeRowing": "Rowing",
    "HKWorkoutActivityTypeCrossTraining": "Cross Training",
    "HKWorkoutActivityTypeDance": "Dance",
    "HKWorkoutActivityTypePilates": "Pilates",
    "HKWorkoutActivityTypeSoccer": "Soccer",
    "HKWorkoutActivityTypeBasketball": "Basketball",
    "HKWorkoutActivityTypeTennis": "Tennis",
}

# Pounds per kilogram
_KG_TO_LBS = 2.20462


def _parse_apple_date(date_str):
    """Parse Apple Health date format: '2025-03-15 23:04:12 -0700'."""
    return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")


def _get_export_path():
    """Return the export.xml path, or raise if not configured."""
    if not APPLE_HEALTH_EXPORT:
        raise FileNotFoundError("APPLE_HEALTH_EXPORT not set in .env")
    if not APPLE_HEALTH_EXPORT.exists():
        raise FileNotFoundError(f"Apple Health export not found: {APPLE_HEALTH_EXPORT}")
    return APPLE_HEALTH_EXPORT


def _iter_records(record_type, start=None, end=None):
    """Stream <Record> elements of a given type, filtered by date range.

    Yields dicts with: startDate, endDate, value, unit, sourceName.
    Clears elements after processing to keep memory flat.
    """
    path = _get_export_path()

    for event, elem in ET.iterparse(str(path), events=("end",)):
        if elem.tag != "Record" or elem.get("type") != record_type:
            elem.clear()
            continue

        start_dt = _parse_apple_date(elem.get("startDate"))
        end_dt = _parse_apple_date(elem.get("endDate"))
        record_date = start_dt.date()

        if start and record_date < start:
            elem.clear()
            continue
        if end and record_date > end:
            elem.clear()
            continue

        yield {
            "startDate": start_dt,
            "endDate": end_dt,
            "value": elem.get("value", ""),
            "unit": elem.get("unit", ""),
            "sourceName": elem.get("sourceName", ""),
        }
        elem.clear()


def _iter_workouts(start=None, end=None):
    """Stream <Workout> elements, filtered by date range.

    Yields dicts with: workoutActivityType, duration, totalDistance,
    totalEnergyBurned, startDate, endDate, sourceName.
    """
    path = _get_export_path()

    for event, elem in ET.iterparse(str(path), events=("end",)):
        if elem.tag != "Workout":
            elem.clear()
            continue

        start_dt = _parse_apple_date(elem.get("startDate"))
        record_date = start_dt.date()

        if start and record_date < start:
            elem.clear()
            continue
        if end and record_date > end:
            elem.clear()
            continue

        yield {
            "workoutActivityType": elem.get("workoutActivityType", ""),
            "duration": float(elem.get("duration", 0)),
            "durationUnit": elem.get("durationUnit", "min"),
            "totalDistance": float(elem.get("totalDistance", 0) or 0),
            "totalDistanceUnit": elem.get("totalDistanceUnit", "mi"),
            "totalEnergyBurned": float(elem.get("totalEnergyBurned", 0) or 0),
            "energyUnit": elem.get("totalEnergyBurnedUnit", "Cal"),
            "startDate": start_dt,
            "sourceName": elem.get("sourceName", ""),
        }
        elem.clear()


def _sleep_night_date(end_dt):
    """Determine which 'night' a sleep record belongs to.

    Records ending before noon belong to that date (you woke up that day).
    Records ending after noon belong to the next day (you'll wake up tomorrow).
    Matches Oura's convention where 'day' = wake-up date.
    """
    if end_dt.hour < 12:
        return end_dt.date()
    return end_dt.date() + timedelta(days=1)


# ---------------------------------------------------------------------------
# Public API — matches signatures used by sources.py
# ---------------------------------------------------------------------------

def get_sleep_data(start, end):
    """Fetch daily sleep data for the given date range.

    Returns minimal dicts compatible with analyze_sleep() —
    Apple Health has no sleep score, so score=None.
    """
    nights = set()

    for rec in _iter_records(_SLEEP, start, end):
        if rec["value"] not in _SLEEP_STAGES:
            continue
        nights.add(_sleep_night_date(rec["endDate"]))

    results = []
    for day in sorted(nights):
        results.append({
            "day": str(day),
            "score": None,
            "contributors": {},
        })
    return results


def get_sleep_durations(days=7):
    """Fetch sleep phase durations (deep, REM, total) for recent nights."""
    end = date.today()
    start = end - timedelta(days=days)

    nights = defaultdict(lambda: {"deep": 0, "rem": 0, "total": 0})

    for rec in _iter_records(_SLEEP, start, end):
        if rec["value"] not in _SLEEP_STAGES:
            continue
        night = _sleep_night_date(rec["endDate"])
        duration = (rec["endDate"] - rec["startDate"]).total_seconds()
        nights[night]["total"] += duration

        if rec["value"] in _DEEP_STAGES:
            nights[night]["deep"] += duration
        elif rec["value"] in _REM_STAGES:
            nights[night]["rem"] += duration

    results = []
    for day in sorted(nights):
        n = nights[day]
        results.append({
            "day": str(day),
            "deep_sleep_sec": int(n["deep"]),
            "rem_sleep_sec": int(n["rem"]),
            "total_sleep_sec": int(n["total"]),
        })
    return results


def get_hrv_rhr(days=7):
    """Fetch HRV and resting heart rate data.

    Returns [{day, avg_hrv, lowest_hr, avg_hr}, ...].
    """
    end = date.today()
    start = end - timedelta(days=days)

    # Collect HRV samples per day
    hrv_by_day = defaultdict(list)
    for rec in _iter_records(_HRV, start, end):
        day = rec["startDate"].date()
        hrv_by_day[day].append(float(rec["value"]))

    # Collect resting HR per day (try RestingHeartRate first, fall back to HeartRate)
    rhr_by_day = defaultdict(list)
    for rec in _iter_records(_RESTING_HR, start, end):
        day = rec["startDate"].date()
        rhr_by_day[day].append(float(rec["value"]))

    # If no resting HR records, use general heart rate during sleep hours (midnight-6am)
    if not rhr_by_day:
        for rec in _iter_records(_HEART_RATE, start, end):
            hour = rec["startDate"].hour
            if hour < 6:  # Approximate resting HR from overnight readings
                day = rec["startDate"].date()
                rhr_by_day[day].append(float(rec["value"]))

    all_days = sorted(set(hrv_by_day) | set(rhr_by_day))
    results = []
    for day in all_days:
        hrvs = hrv_by_day.get(day, [])
        hrs = rhr_by_day.get(day, [])
        results.append({
            "day": str(day),
            "avg_hrv": round(sum(hrvs) / len(hrvs), 1) if hrvs else None,
            "lowest_hr": round(min(hrs), 1) if hrs else None,
            "avg_hr": round(sum(hrs) / len(hrs), 1) if hrs else None,
        })
    return results


def get_bodyweight(start, end):
    """Fetch body weight entries. Converts kg to lbs if needed."""
    results = []
    for rec in _iter_records(_BODY_MASS, start, end):
        weight = float(rec["value"])
        if rec["unit"] == "kg":
            weight = round(weight * _KG_TO_LBS, 1)
        results.append({
            "date": rec["startDate"].date(),
            "weight": weight,
            "notes": "",
        })
    return sorted(results, key=lambda r: r["date"])


def get_workouts(start, end):
    """Fetch workouts as cardio-style entries.

    Apple Health workouts don't have sets/reps/weight — they map to
    the same format as Firestore's cardio entries (duration + distance + calories).
    """
    results = []
    for w in _iter_workouts(start, end):
        activity = w["workoutActivityType"]
        exercise = _WORKOUT_NAMES.get(activity, activity.replace("HKWorkoutActivityType", ""))

        # Convert duration to minutes
        duration_min = w["duration"]
        if w["durationUnit"] == "s":
            duration_min = round(duration_min / 60, 1)

        # Convert distance to miles
        distance_miles = w["totalDistance"]
        if w["totalDistanceUnit"] == "km":
            distance_miles = round(distance_miles * 0.621371, 2)

        results.append({
            "date": w["startDate"].date(),
            "day_type": "Cardio",
            "exercise": exercise,
            "sets": 1,
            "reps": 1,
            "weight": 0,
            "volume": 0,
            "variant": {
                "duration_min": round(duration_min, 1),
                "distance_miles": round(distance_miles, 2),
                "calories": round(w["totalEnergyBurned"]),
            },
            "notes": "",
        })
    return sorted(results, key=lambda r: r["date"])
