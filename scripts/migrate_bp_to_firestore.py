"""One-time migration: BP Monitoring Google Sheet -> Firestore `bloodpressure`.

Reads the daily table (Date, AM Sys./Dias./HR, PM Sys./Dias./HR,
Notes/Observations), splits each row into AM and PM session docs matching
the iOS app's BloodPressureEntry schema, and writes them with deterministic
IDs (YYYY-MM-DD-am / YYYY-MM-DD-pm) so reruns are idempotent.

Usage:
    venv/bin/python3 scripts/migrate_bp_to_firestore.py --dry-run
    venv/bin/python3 scripts/migrate_bp_to_firestore.py
"""

import argparse
import re
import sys
from datetime import datetime, time, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gspread  # noqa: E402

from config import BP_SHEET_KEY  # noqa: E402
from sheets import _get_client, _parse_date  # noqa: E402
from firestore_client import _get_client as _get_firestore  # noqa: E402


def _find_col(headers, terms, exclude=None):
    for i, h in enumerate(headers):
        if all(t in h for t in terms):
            if exclude and any(e in h for e in exclude):
                continue
            return i
    return None


def _num(row, col):
    if col is None or col >= len(row):
        return None
    text = row[col].strip()
    if not text:
        return None
    try:
        return int(round(float(text)))
    except ValueError:
        return None


def _split_notes(raw):
    """Split 'AM: ... PM: ...' into (am_notes, pm_notes)."""
    raw = (raw or "").strip()
    if not raw:
        return "", ""
    match = re.search(r"\bPM:", raw)
    if match:
        am, pm = raw[: match.start()], raw[match.end():]
    else:
        am, pm = raw, ""
    am = re.sub(r"^\s*AM:\s*", "", am).strip()
    return am, pm.strip()


def read_sheet_rows():
    """Read the BP sheet's daily table. Returns list of per-day dicts."""
    sheet = _get_client().open_by_key(BP_SHEET_KEY).sheet1
    all_values = sheet.get_all_values()
    if len(all_values) < 2:
        return []

    headers = [h.strip().lower() for h in all_values[0]]
    date_col = _find_col(headers, ["date"])
    sys_am_col = _find_col(headers, ["am", "sys"])
    dia_am_col = _find_col(headers, ["am", "dia"])
    hr_am_col = _find_col(headers, ["am", "hr"])
    sys_pm_col = _find_col(headers, ["pm", "sys"])
    dia_pm_col = _find_col(headers, ["pm", "dia"])
    hr_pm_col = _find_col(headers, ["pm", "hr"])
    notes_col = _find_col(headers, ["notes"])

    # PM diastolic header may lack the "pm" prefix (just "Dias."): take the
    # first "dia" column after PM systolic.
    if dia_pm_col is None and sys_pm_col is not None:
        for i in range(sys_pm_col + 1, len(headers)):
            if "dia" in headers[i]:
                dia_pm_col = i
                break

    if date_col is None:
        raise SystemExit("Could not find Date column in the BP sheet")

    rows = []
    for row in all_values[1:]:
        if not row or date_col >= len(row) or not row[date_col].strip():
            continue
        d = _parse_date(row[date_col])
        if not d:
            continue
        notes_am, notes_pm = _split_notes(
            row[notes_col] if notes_col is not None and notes_col < len(row) else ""
        )
        rows.append({
            "date": d,
            "am": (_num(row, sys_am_col), _num(row, dia_am_col), _num(row, hr_am_col)),
            "pm": (_num(row, sys_pm_col), _num(row, dia_pm_col), _num(row, hr_pm_col)),
            "notes_am": notes_am,
            "notes_pm": notes_pm,
        })
    return rows


def build_docs(rows):
    """Turn per-day rows into (doc_id, doc) pairs, one per AM/PM session."""
    session_hour = {"am": 8, "pm": 20}
    docs = []
    for row in rows:
        for session in ("am", "pm"):
            systolic, diastolic, heart_rate = row[session]
            if systolic is None or diastolic is None:
                continue
            doc_id = f"{row['date'].isoformat()}-{session}"
            docs.append((doc_id, {
                "date": datetime.combine(
                    row["date"], time(session_hour[session], 0), tzinfo=timezone.utc
                ),
                "session": session,
                "readings": [],  # sheet only kept the averaged summary
                "systolic": systolic,
                "diastolic": diastolic,
                "heartRate": heart_rate if heart_rate is not None else 0,
                "notes": row[f"notes_{session}"],
                "createdAt": datetime.now(timezone.utc),
            }))
    return docs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print docs without writing")
    args = parser.parse_args()

    rows = read_sheet_rows()
    docs = build_docs(rows)
    am_count = sum(1 for _, d in docs if d["session"] == "am")
    pm_count = len(docs) - am_count
    print(f"Sheet rows with a date: {len(rows)}")
    print(f"Session docs to write: {len(docs)} ({am_count} AM, {pm_count} PM)")

    if args.dry_run:
        for doc_id, doc in docs:
            note = f"  | {doc['notes']}" if doc["notes"] else ""
            print(f"  {doc_id}: {doc['systolic']}/{doc['diastolic']} · {doc['heartRate']} bpm{note}")
        print("\nDry run — nothing written.")
        return

    db = _get_firestore()
    collection = db.collection("bloodpressure")
    existing_before = len(list(collection.select([]).stream()))

    batch = db.batch()
    pending = 0
    for doc_id, doc in docs:
        batch.set(collection.document(doc_id), doc)
        pending += 1
        if pending == 400:  # Firestore batch limit is 500
            batch.commit()
            batch = db.batch()
            pending = 0
    if pending:
        batch.commit()

    existing_after = len(list(collection.select([]).stream()))
    print(f"Collection size: {existing_before} -> {existing_after}")


if __name__ == "__main__":
    main()
