"""Google Sheets reader for exercise and weight data (per-tab PPL format)."""

import re
import gspread
from datetime import datetime
from config import GOOGLE_SERVICE_ACCOUNT_FILE, EXERCISE_SHEET_NAME, REPORTS_LOG_SHEET_NAME, BP_SHEET_KEY


def _get_client():
    return gspread.service_account(filename=str(GOOGLE_SERVICE_ACCOUNT_FILE))


def _parse_date(date_str):
    """Parse date string from sheet. Tries common formats."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%m/%d/%y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_exercise_name(header):
    """Extract exercise name from header like 'Bench [3×10] lbs' or 'Bench Reps'."""
    # Remove trailing 'lbs', 'Reps', set/rep info in brackets
    name = re.sub(r'\s*\[.*?\]\s*', ' ', header)
    name = re.sub(r'\s*(lbs|Reps)$', '', name)
    return name.strip()


def _parse_default_sets(header):
    """Extract default sets from header like 'Bench [3×10-15] lbs' -> 3."""
    m = re.search(r'\[(\d+)×', header)
    return int(m.group(1)) if m else 3


def _read_workout_tab(client, sheet_name, tab_name, start=None, end=None):
    """Read a workout tab (Push/Pull/Legs) and return structured workout dicts."""
    try:
        sheet = client.open(sheet_name).worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        return []

    all_values = sheet.get_all_values()
    if len(all_values) < 2:
        return []

    headers = all_values[0]
    workouts = []

    # Find exercise columns: pairs of (weight_col, reps_col)
    # Headers ending in 'lbs' are weight columns, 'Reps' are rep columns
    exercises = []
    i = 0
    while i < len(headers):
        h = headers[i]
        if h == "Date" or h == "Notes" or "Type" in h:
            i += 1
            continue

        if h.endswith("lbs"):
            exercise_name = _parse_exercise_name(h)
            default_sets = _parse_default_sets(h)
            reps_col = i + 1 if i + 1 < len(headers) else None
            exercises.append({
                "name": exercise_name,
                "weight_col": i,
                "reps_col": reps_col,
                "default_sets": default_sets,
            })
            i += 2  # skip reps column
        elif h.endswith("Reps") and not any(e["reps_col"] == i for e in exercises):
            # Standalone reps column (like Dips — bodyweight)
            exercise_name = _parse_exercise_name(h)
            default_sets = _parse_default_sets(h)
            exercises.append({
                "name": exercise_name,
                "weight_col": None,
                "reps_col": i,
                "default_sets": default_sets,
            })
            i += 1
        else:
            i += 1

    # Find special columns
    date_col = headers.index("Date") if "Date" in headers else 0
    notes_col = headers.index("Notes") if "Notes" in headers else None
    type_cols = {i: headers[i] for i in range(len(headers)) if "Type" in headers[i]}

    # Parse data rows (skip row 2 if it's the helper text)
    for row_idx, row in enumerate(all_values[1:], start=2):
        if not row or not row[date_col].strip():
            continue

        d = _parse_date(row[date_col])
        if not d:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue

        # Check for type columns (e.g., Bench Type, Ham Curl Type)
        variant_info = {}
        for col_idx, col_name in type_cols.items():
            if col_idx < len(row) and row[col_idx].strip():
                variant_info[col_name] = row[col_idx].strip()

        notes = row[notes_col].strip() if notes_col and notes_col < len(row) else ""

        for ex in exercises:
            weight = 0
            reps = 0

            if ex["weight_col"] is not None and ex["weight_col"] < len(row):
                try:
                    weight = float(row[ex["weight_col"]]) if row[ex["weight_col"]].strip() else 0
                except ValueError:
                    weight = 0

            if ex["reps_col"] is not None and ex["reps_col"] < len(row):
                try:
                    reps = int(row[ex["reps_col"]]) if row[ex["reps_col"]].strip() else 0
                except ValueError:
                    reps = 0

            # Skip if no data entered for this exercise
            if weight == 0 and reps == 0:
                continue

            sets = ex["default_sets"]
            workouts.append({
                "date": d,
                "day_type": tab_name,
                "exercise": ex["name"],
                "sets": sets,
                "reps": reps,
                "weight": weight,
                "volume": sets * reps * weight,
                "variant": variant_info,
                "notes": notes,
            })

    return workouts


def get_workouts(start=None, end=None):
    """Read all workout tabs and combine."""
    client = _get_client()
    all_workouts = []
    for tab in ["Push", "Pull", "Legs"]:
        all_workouts.extend(_read_workout_tab(client, EXERCISE_SHEET_NAME, tab, start, end))
    return all_workouts


def get_bodyweight(start=None, end=None):
    """Read bodyweight entries from Google Sheet."""
    client = _get_client()
    try:
        sheet = client.open(EXERCISE_SHEET_NAME).worksheet("Bodyweight")
    except gspread.exceptions.WorksheetNotFound:
        return []

    rows = sheet.get_all_records()
    entries = []
    for row in rows:
        d = _parse_date(str(row.get("Date", "")))
        if not d:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue

        entries.append({
            "date": d,
            "weight": float(row.get("Weight (lbs)", 0) or 0),
            "notes": row.get("Notes", ""),
        })

    return entries


def get_bp_data(start=None, end=None):
    """Read blood pressure entries from the BP Monitoring Google Sheet.

    Expected columns (case-insensitive): Date, AM Systolic, AM Diastolic,
    PM Systolic, PM Diastolic. Returns list of dicts with date + am/pm readings.
    """
    client = _get_client()
    try:
        sheet = client.open_by_key(BP_SHEET_KEY).sheet1
    except (gspread.exceptions.SpreadsheetNotFound, PermissionError):
        return []

    all_values = sheet.get_all_values()
    if len(all_values) < 2:
        return []

    headers = [h.strip().lower() for h in all_values[0]]

    def _col(terms, exclude=None):
        """Return index of first header containing all terms (optionally excluding others)."""
        for i, h in enumerate(headers):
            if all(t in h for t in terms):
                if exclude and any(e in h for e in exclude):
                    continue
                return i
        return None

    date_col = _col(["date"])
    sys_am_col = _col(["am", "sys"])
    dia_am_col = _col(["am", "dia"])
    sys_pm_col = _col(["pm", "sys"])
    # PM diastolic may lack "pm" prefix (e.g. just "dias.") — find the column
    # after the PM systolic column that contains "dia"
    dia_pm_col = _col(["pm", "dia"])
    if dia_pm_col is None and sys_pm_col is not None:
        # Fall back: first "dia" column after sys_pm_col
        for i in range(sys_pm_col + 1, len(headers)):
            if "dia" in headers[i]:
                dia_pm_col = i
                break

    if date_col is None:
        return []

    def _num(row, col):
        if col is None or col >= len(row):
            return None
        try:
            return float(row[col].strip()) if row[col].strip() else None
        except ValueError:
            return None

    entries = []
    for row in all_values[1:]:
        if not row or not row[date_col].strip():
            continue
        d = _parse_date(row[date_col])
        if not d:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue

        sys_am = _num(row, sys_am_col)
        dia_am = _num(row, dia_am_col)
        sys_pm = _num(row, sys_pm_col)
        dia_pm = _num(row, dia_pm_col)

        if sys_am is None and dia_am is None and sys_pm is None and dia_pm is None:
            continue

        entries.append({
            "date": d,
            "systolic_am": sys_am,
            "diastolic_am": dia_am,
            "systolic_pm": sys_pm,
            "diastolic_pm": dia_pm,
        })

    return entries


def get_responses(limit=10):
    """Read recent responses from the Cloudflare Worker KV store."""
    import requests as req
    from config import WEBHOOK_URL, RESPONSES_SECRET
    if not WEBHOOK_URL or not RESPONSES_SECRET:
        return []
    try:
        resp = req.get(
            f"{WEBHOOK_URL}responses",
            params={"secret": RESPONSES_SECRET},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            return data[-limit:] if data else []
    except Exception:
        pass
    return []


def log_report_to_sheets(report_type, summary, full_report, delivery_status):
    """Append a report row to the Reports Log sheet for historical tracking.

    Creates the sheet with headers if it doesn't exist yet.
    """
    from datetime import date

    client = _get_client()
    try:
        spreadsheet = client.open(REPORTS_LOG_SHEET_NAME)
        sheet = spreadsheet.sheet1
    except gspread.SpreadsheetNotFound:
        print(f"[sheets] Sheet '{REPORTS_LOG_SHEET_NAME}' not found — skipping report log")
        return False

    # Add headers if the sheet has no content yet
    first_cell = sheet.acell("A1").value
    if not first_cell:
        sheet.update("A1:E1", [["Date", "Type", "Summary", "Full Report", "Delivery Status"]])

    # Format delivery status
    status_parts = []
    for channel, ok in delivery_status.items():
        status_parts.append(f"{channel}: {'✓' if ok else '✗'}")
    status_str = ", ".join(status_parts)

    row = [
        str(date.today()),
        report_type,
        summary,
        full_report,
        status_str,
    ]

    try:
        sheet.append_row(row, value_input_option="RAW")
        print(f"[sheets] Report logged to '{REPORTS_LOG_SHEET_NAME}'")
        return True
    except Exception as e:
        print(f"[sheets] Failed to log report: {e}")
        return False


def find_prs(workouts):
    """Find personal records — highest weight per exercise."""
    best = {}
    prs = []
    for w in sorted(workouts, key=lambda x: x["date"]):
        ex = w["exercise"]
        if ex not in best or w["weight"] > best[ex]["weight"]:
            if ex in best:
                prs.append({
                    "exercise": ex,
                    "date": w["date"],
                    "weight": w["weight"],
                    "previous": best[ex]["weight"],
                })
            best[ex] = w
    return prs
