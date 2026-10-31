"""Firestore reader/writer.

Reads workouts, bodyweight, and wellness extras written by the HealthOS
iOS app (dicts match the sheets.py format). Also stores the Drive file
manifest and the mirrored blood test data that Cloud Run reads, since it
has no access to the local Drive mount.
"""

import json
from datetime import date, datetime
from google.cloud import firestore
from config import GOOGLE_SERVICE_ACCOUNT_FILE, FIRESTORE_PROJECT_ID


def _get_client():
    try:
        return firestore.Client.from_service_account_json(
            str(GOOGLE_SERVICE_ACCOUNT_FILE),
            project=FIRESTORE_PROJECT_ID,
            database="(default)",
        )
    except Exception as e:
        raise RuntimeError(
            f"[firestore_client] Cannot build Firestore client. "
            f"Check GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE. Original: {e}"
        ) from e


def get_file_manifest():
    """Read the Drive folder file manifest. Returns dict keyed by file ID."""
    doc = _get_client().collection("health_folder_manifest").document("current").get()
    return (doc.to_dict() or {}) if doc.exists else {}


def set_file_manifest(manifest):
    """Overwrite the Drive folder file manifest."""
    _get_client().collection("health_folder_manifest").document("current").set(manifest)


def get_latest_blood_test_date():
    """Read the latest blood test date from Firestore. Returns date or None.

    Local runs write this whenever blood test PDFs are parsed (see
    blood_tests.parse_all_blood_tests). Cloud Run reads it so the
    weekly 6-month reminder can still fire without filesystem access.
    """
    doc = _get_client().collection("health_meta").document("blood_tests").get()
    if not doc.exists:
        return None
    return _coerce_date((doc.to_dict() or {}).get("latest_date"))


def set_latest_blood_test_date(d):
    """Persist the latest blood test date to Firestore."""
    if isinstance(d, datetime):
        d = d.date()
    if not isinstance(d, date):
        return
    _get_client().collection("health_meta").document("blood_tests").set({
        "latest_date": d.isoformat(),
        "updated_at": datetime.utcnow(),
    }, merge=True)


def _coerce_date(raw):
    """Best-effort coercion of a Firestore value to a date. Returns date|None."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw[:10]).date()
        except ValueError:
            return None
    return None


def get_blood_test_reported_date():
    """Read the date of the newest blood test already shown in a weekly report.

    Used to suppress blood test results from the weekly email once they've
    already been sent, until a newer test becomes available. Returns date|None.
    """
    doc = _get_client().collection("health_meta").document("blood_tests").get()
    if not doc.exists:
        return None
    return _coerce_date((doc.to_dict() or {}).get("reported_date"))


def set_blood_test_reported_date(d):
    """Persist the date of the newest blood test shown in a weekly report."""
    if isinstance(d, datetime):
        d = d.date()
    if not isinstance(d, date):
        return
    _get_client().collection("health_meta").document("blood_tests").set({
        "reported_date": d.isoformat(),
        "reported_at": datetime.utcnow(),
    }, merge=True)


def set_blood_tests_data(longitudinal, all_tests):
    """Mirror the full parsed blood test data to Firestore as JSON strings.

    Cloud Run has no Drive mount and can't parse the PDFs itself, so local
    runs publish the longitudinal view + parsed results here. The weekly
    report (which runs on Cloud Run) reads this to render trends and the
    latest-results explanation. Stored as JSON strings to sidestep Firestore's
    nested-array restrictions; the bulky raw_text_preview is dropped to stay
    well under the 1 MB document limit.
    """
    payload = {}
    if longitudinal is not None:
        payload["longitudinal_json"] = json.dumps(longitudinal, default=str)
    if all_tests is not None:
        slim = [
            {k: v for k, v in t.items() if k != "raw_text_preview"}
            for t in all_tests
        ]
        payload["all_tests_json"] = json.dumps(slim, default=str)
    if not payload:
        return
    payload["updated_at"] = datetime.utcnow()
    _get_client().collection("health_meta").document("blood_tests").set(payload, merge=True)


def get_blood_tests_updated_at():
    """When the blood test mirror was last written by a local parse.

    Returns a tz-aware datetime or None. Used by the weekly staleness check
    to detect Drive PDFs newer than the mirrored data.
    """
    doc = _get_client().collection("health_meta").document("blood_tests").get()
    if not doc.exists:
        return None
    return (doc.to_dict() or {}).get("updated_at")


def get_blood_tests_data():
    """Read full parsed blood test data from Firestore.

    Returns (longitudinal dict|None, all_tests list|None). Used by Cloud Run
    as the fallback when the local PDF parse finds nothing.
    """
    doc = _get_client().collection("health_meta").document("blood_tests").get()
    if not doc.exists:
        return None, None
    data = doc.to_dict() or {}

    def _load(key):
        raw = data.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    return _load("longitudinal_json"), _load("all_tests_json")


def _range_query(collection, start=None, end=None):
    """Build a date-descending query on a collection, bounded by [start, end]."""
    query = _get_client().collection(collection).order_by(
        "date", direction=firestore.Query.DESCENDING
    )
    if start:
        if isinstance(start, date) and not isinstance(start, datetime):
            start = datetime.combine(start, datetime.min.time())
        query = query.where(filter=firestore.FieldFilter("date", ">=", start))
    if end:
        if isinstance(end, date) and not isinstance(end, datetime):
            end = datetime.combine(end, datetime.max.time())
        query = query.where(filter=firestore.FieldFilter("date", "<=", end))
    return query


def _doc_date(raw):
    """Coerce a document's date field (datetime or ISO string) to a date."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str):
        return datetime.fromisoformat(raw).date()
    return raw


def get_workouts(start=None, end=None):
    """Read workouts from Firestore. Returns list of dicts matching sheets.py format.

    Each dict: {date, day_type, exercise, sets, reps, weight, volume, variant, notes}
    One dict per exercise entry (a single workout produces multiple dicts).
    """
    workouts = []
    for doc in _range_query("workouts", start, end).stream():
        data = doc.to_dict()
        workout_date = _doc_date(data.get("date"))

        day_type = (data.get("dayType") or "").capitalize()  # push -> Push
        notes = data.get("notes", "")

        for ex in data.get("exercises", []):
            weight = float(ex.get("weight", 0) or 0)
            reps = int(ex.get("reps", 0) or 0)
            sets = int(ex.get("sets", 0) or 0)
            variant_raw = ex.get("variant")
            variant = {"Type": variant_raw} if variant_raw else {}

            workouts.append({
                "date": workout_date,
                "day_type": day_type,
                "exercise": ex.get("exerciseName", ""),
                "sets": sets,
                "reps": reps,
                "weight": weight,
                "volume": sets * reps * weight,
                "variant": variant,
                "notes": notes,
            })

        # Cardio entries (stored as a workout with dayType "cardio")
        cardio = data.get("cardio")
        if cardio and (cardio.get("duration", 0) > 0 or cardio.get("distance", 0) > 0):
            workouts.append({
                "date": workout_date,
                "day_type": "Cardio",
                "exercise": "Cardio",
                "sets": 1,
                "reps": 1,
                "weight": 0,
                "volume": 0,
                "variant": {
                    "duration_min": cardio.get("duration", 0),
                    "distance_miles": cardio.get("distance", 0),
                },
                "notes": notes,
            })

    return workouts


def get_bodyweight(start=None, end=None):
    """Read body weight entries from Firestore. Returns list of dicts matching sheets.py format.

    Each dict: {date, weight, notes}
    """
    entries = []
    for doc in _range_query("bodyweight", start, end).stream():
        data = doc.to_dict()
        entries.append({
            "date": _doc_date(data.get("date")),
            "weight": float(data.get("weight", 0) or 0),
            "notes": data.get("notes", ""),
        })

    return entries


def get_bp_data(start=None, end=None):
    """Read blood pressure sessions from Firestore, merged per day.

    The iOS app (and the sheet migration) writes one doc per AM/PM session.
    Returns per-day dicts matching the sheets.py format, extended with
    heart rate and notes:
      {date, systolic_am, diastolic_am, hr_am, notes_am,
             systolic_pm, diastolic_pm, hr_pm, notes_pm}
    """
    by_date = {}
    for doc in _range_query("bloodpressure", start, end).stream():
        data = doc.to_dict()
        d = _doc_date(data.get("date"))
        entry = by_date.setdefault(d, {
            "date": d,
            "systolic_am": None, "diastolic_am": None, "hr_am": None, "notes_am": "",
            "systolic_pm": None, "diastolic_pm": None, "hr_pm": None, "notes_pm": "",
        })
        suffix = "am" if data.get("session") == "am" else "pm"
        entry[f"systolic_{suffix}"] = data.get("systolic")
        entry[f"diastolic_{suffix}"] = data.get("diastolic")
        entry[f"hr_{suffix}"] = data.get("heartRate") or None
        entry[f"notes_{suffix}"] = data.get("notes", "")

    return sorted(by_date.values(), key=lambda e: e["date"])


def get_extras(start=None, end=None):
    """Read wellness extras (meditation, sauna, cold plunge) from Firestore.

    Each dict: {date, meditation, sauna, cold_plunge}
      meditation:  {style: "Seated"|"Walking", duration: int} or None
      sauna:       {duration: int, temperature: float|None}   or None
      cold_plunge: {duration: int, temperature: float}        or None
    """
    extras = []
    for doc in _range_query("extras", start, end).stream():
        data = doc.to_dict()
        extras.append({
            "date": _doc_date(data.get("date")),
            "meditation": data.get("meditation"),
            "sauna": data.get("sauna"),
            "cold_plunge": data.get("coldPlunge"),
        })

    return extras
