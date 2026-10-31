"""Manual data entry from JSON and CSV files.

Reads data from MANUAL_DATA_DIR (default: data/manual/) for backfilling
gaps in wearable data. Files are named by data type:
  sleep.json / sleep.csv
  hrv.json / hrv.csv
  workouts.json / workouts.csv
  weight.json / weight.csv
"""

import csv
import json
from datetime import date, datetime, timedelta
from config import MANUAL_DATA_DIR


_DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y"]


def _parse_date(val):
    """Parse a date string trying common formats. Returns a date object."""
    if isinstance(val, date):
        return val
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(str(val), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {val}")


def _load_data(name, start=None, end=None, date_field="date"):
    """Load data from JSON or CSV file, filtered by date range.

    Looks for {name}.json first, then {name}.csv.
    Returns list of dicts with parsed dates and numeric types.
    """
    json_path = MANUAL_DATA_DIR / f"{name}.json"
    csv_path = MANUAL_DATA_DIR / f"{name}.csv"

    rows = []
    if json_path.exists():
        with open(json_path) as f:
            rows = json.load(f)
    elif csv_path.exists():
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    else:
        return []

    # Parse dates and filter by range
    results = []
    for row in rows:
        if date_field not in row and "day" in row:
            date_field = "day"

        raw_date = row.get(date_field) or row.get("day")
        if not raw_date:
            continue

        row_date = _parse_date(raw_date)
        if start and row_date < start:
            continue
        if end and row_date > end:
            continue

        # Convert numeric fields
        parsed = {}
        for k, v in row.items():
            if k in (date_field, "day"):
                parsed[k] = row_date if k == date_field else str(row_date)
            elif isinstance(v, str):
                # Try numeric conversion
                try:
                    parsed[k] = int(v)
                except ValueError:
                    try:
                        parsed[k] = float(v)
                    except ValueError:
                        parsed[k] = v
            else:
                parsed[k] = v
        results.append(parsed)

    return sorted(results, key=lambda r: r.get(date_field, r.get("day", "")))


# ---------------------------------------------------------------------------
# Public API — matches signatures used by sources.py
# ---------------------------------------------------------------------------

def get_sleep_data(start, end):
    """Read sleep data from sleep.json/csv.

    Expected fields: day, score (optional), contributors (optional).
    """
    rows = _load_data("sleep", start, end, date_field="day")
    results = []
    for row in rows:
        results.append({
            "day": str(row.get("day", "")),
            "score": row.get("score"),
            "contributors": row.get("contributors", {}),
        })
    return results


def get_sleep_durations(days=7):
    """Read sleep duration data from sleep.json/csv.

    Expected fields: day, deep_sleep_sec, rem_sleep_sec, total_sleep_sec.
    """
    end = date.today()
    start = end - timedelta(days=days)
    rows = _load_data("sleep", start, end, date_field="day")
    results = []
    for row in rows:
        if "total_sleep_sec" not in row:
            continue
        results.append({
            "day": str(row.get("day", "")),
            "deep_sleep_sec": row.get("deep_sleep_sec", 0),
            "rem_sleep_sec": row.get("rem_sleep_sec", 0),
            "total_sleep_sec": row.get("total_sleep_sec", 0),
        })
    return results


def get_hrv_rhr(days=7):
    """Read HRV and resting heart rate from hrv.json/csv.

    Expected fields: day, avg_hrv, lowest_hr, avg_hr.
    """
    end = date.today()
    start = end - timedelta(days=days)
    rows = _load_data("hrv", start, end, date_field="day")
    results = []
    for row in rows:
        results.append({
            "day": str(row.get("day", "")),
            "avg_hrv": row.get("avg_hrv"),
            "lowest_hr": row.get("lowest_hr"),
            "avg_hr": row.get("avg_hr"),
        })
    return results


def get_workouts(start, end):
    """Read workout data from workouts.json/csv.

    Expected fields: date, day_type, exercise, sets, reps, weight, volume, notes.
    """
    rows = _load_data("workouts", start, end)
    results = []
    for row in rows:
        results.append({
            "date": row.get("date", ""),
            "day_type": row.get("day_type", ""),
            "exercise": row.get("exercise", ""),
            "sets": row.get("sets", 0),
            "reps": row.get("reps", 0),
            "weight": row.get("weight", 0),
            "volume": row.get("volume", 0),
            "variant": row.get("variant", {}),
            "notes": row.get("notes", ""),
        })
    return results


def get_bodyweight(start, end):
    """Read body weight from weight.json/csv.

    Expected fields: date, weight, notes (optional).
    """
    rows = _load_data("weight", start, end)
    results = []
    for row in rows:
        results.append({
            "date": row.get("date", ""),
            "weight": row.get("weight", 0),
            "notes": row.get("notes", ""),
        })
    return results
