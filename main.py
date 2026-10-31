#!/usr/bin/env python3
"""Health OS — Orchestrator. Pulls data, analyzes, generates reports, delivers."""

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Ensure health_os is on the path
sys.path.insert(0, str(Path(__file__).parent))

from config import REPORTS_DIR

MIN_REPORT_HOUR = 6  # Don't generate reports before 6 AM — Oura data won't be ready


def _latest_blood_test_date(blood_tests_parsed):
    """Newest test date across parsed blood tests. Returns date|None."""
    if not blood_tests_parsed:
        return None
    from firestore_client import _coerce_date
    dates = [d for d in (_coerce_date(t.get("date")) for t in blood_tests_parsed) if d]
    return max(dates) if dates else None


def _alert_firestore_error(action, error, consequence):
    """Telegram-alert a Firestore failure so dedup fallbacks are never silent."""
    try:
        from notify import send_telegram
        send_telegram(f"⚠️ Health OS: Firestore error during {action}: {error}. {consequence}.")
    except Exception as e:
        print(f"[main] Could not send Firestore error alert: {e}")


def already_reported(report_type):
    """Check if today's report has already been generated."""
    today = date.today()
    if (REPORTS_DIR / f"{report_type}_{today}.md").exists():
        return True
    try:
        from firestore_client import _get_client
        doc = _get_client().collection("report_log").document(str(today)).get()
        if doc.exists:
            data = doc.to_dict() or {}
            return bool(data.get(report_type))
    except Exception as e:
        print(f"[main] Could not check Firestore report_log: {e} — assuming already reported to prevent duplicates")
        _alert_firestore_error(
            "report_log check", e,
            f"Skipping the {report_type} report as a duplicate-send precaution — send it manually if it never arrives"
        )
        return True
    return False


def claim_report_slot(report_type):
    """Atomically claim the report slot via Firestore transaction.

    Returns True if this caller successfully claimed it (proceed with report).
    Returns False if already claimed or completed by another instance.
    Falls back to True (allow) if Firestore is unavailable.
    """
    from google.cloud import firestore as _fs
    try:
        from firestore_client import _get_client
        today = str(date.today())
        db = _get_client()
        doc_ref = db.collection("report_log").document(today)

        @_fs.transactional
        def _txn(transaction, ref):
            snap = ref.get(transaction=transaction)
            data = (snap.to_dict() or {}) if snap.exists else {}
            if data.get(report_type) or data.get(f"{report_type}_claimed"):
                return False
            transaction.set(ref, {f"{report_type}_claimed": True}, merge=True)
            return True

        return _txn(db.transaction(), doc_ref)
    except Exception as e:
        print(f"[main] Could not claim report slot in Firestore ({e}) — proceeding anyway")
        _alert_firestore_error(
            "report slot claim", e,
            f"Proceeding with the {report_type} report anyway — a duplicate email is possible"
        )
        return True


def release_report_slot(report_type):
    """Clear the claimed flag so a later retry trigger can proceed.

    Called when data wasn't ready — the slot was claimed but no report was sent.
    """
    try:
        from google.cloud.firestore import DELETE_FIELD
        from firestore_client import _get_client
        today = str(date.today())
        _get_client().collection("report_log").document(today).set(
            {f"{report_type}_claimed": DELETE_FIELD}, merge=True
        )
        print(f"[main] Released {report_type} slot — retry trigger can proceed")
    except Exception as e:
        print(f"[main] Could not release report slot: {e}")


def _deliver_and_log(report_type, report, questions=None, metadata=None):
    """Deliver via email, then save and log to Firestore + Sheets.

    Returns None if email delivery failed — the report is not saved or logged,
    so the caller releases the slot and a retry trigger can resend.
    """
    today = date.today()

    from notify import deliver_report, format_telegram_summary, send_telegram
    result = deliver_report(report)

    if result.get("email") is False:  # None = Gmail not configured (intentional skip)
        send_telegram(
            f"⚠️ Health OS: {report_type} report was generated but email delivery "
            "failed after retries. It will be resent on the next trigger."
        )
        print(f"[main] {report_type} report NOT saved or logged — email delivery failed")
        print(report)
        return None

    if not os.getenv("SKIP_LOCAL_REPORT_WRITE"):
        path = REPORTS_DIR / f"{report_type}_{today}.md"
        path.write_text(report)
        print(f"[main] {report_type.title()} report saved: {path}")

    try:
        from firestore_client import _get_client
        _get_client().collection("report_log").document(str(today)).set(
            {report_type: True, f"{report_type}_at": datetime.utcnow().isoformat()},
            merge=True,
        )
        print(f"[main] Firestore report_log/{today} updated: {report_type}=True")
    except Exception as e:
        print(f"[main] Could not update Firestore report_log: {e}")

    try:
        from sheets import log_report_to_sheets
        summary = format_telegram_summary(report, questions, metadata=metadata)
        log_report_to_sheets(report_type, summary, report, result)
    except Exception as e:
        print(f"[main] Could not log report to Sheets: {e}")

    print(report)
    return report


def _get_baselines():
    """Personal 60-day baselines for flag thresholds. Fail-safe: None on error."""
    try:
        from baselines import get_baselines
        return get_baselines()
    except Exception as e:
        print(f"[main] Baselines unavailable, using fixed thresholds: {e}")
        return None


def run_daily():
    """Daily snapshot: last night's sleep + HRV/RHR vs 7-day average."""
    if datetime.now().hour < MIN_REPORT_HOUR:
        print(f"[main] Too early to run daily report — skipping (current hour: {datetime.now().hour})")
        return None
    from sources import get_sleep_data, get_hrv_data, get_sleep_durations, wait_for_fresh_data, get_blood_tests
    from sources import get_readiness_data, get_activity_data
    from analyze import generate_report

    if not wait_for_fresh_data(max_wait_minutes=30, interval_minutes=5, report_type="daily"):
        print("[main] Skipping daily report — no fresh sleep data")
        return None

    today = date.today()
    sleep_data = get_sleep_data(today - timedelta(days=7), today)
    hrv_rhr_data = get_hrv_data(days=7)
    sleep_durations = get_sleep_durations(days=7)
    readiness_data = get_readiness_data(today - timedelta(days=7), today)
    activity_data = get_activity_data(today - timedelta(days=7), today)
    baselines = _get_baselines()
    blood_result = get_blood_tests()
    _, blood_tests_parsed = blood_result if blood_result else (None, None)

    report, metadata = generate_report(
        sleep_data=sleep_data,
        hrv_rhr_data=hrv_rhr_data,
        sleep_durations=sleep_durations,
        readiness_data=readiness_data,
        activity_data=activity_data,
        baselines=baselines,
        blood_tests_parsed=blood_tests_parsed,
        report_type="daily",
    )

    return _deliver_and_log("daily", report, metadata=metadata)


def run_weekly():
    """Full weekly report: sleep + exercise + weight + new files."""
    if datetime.now().hour < MIN_REPORT_HOUR:
        print(f"[main] Too early to run weekly report — skipping (current hour: {datetime.now().hour})")
        return None
    from sources import get_sleep_data, get_hrv_data, get_sleep_durations, wait_for_fresh_data
    from sources import get_workouts, get_weight, get_responses, get_bp_data, get_blood_tests, get_extras
    from sources import get_readiness_data, get_activity_data
    from analyze import generate_report, generate_questions
    from watcher import check_for_changes

    if not wait_for_fresh_data(max_wait_minutes=30, interval_minutes=5, report_type="weekly"):
        print("[main] Skipping weekly report — no fresh sleep data")
        return None

    today = date.today()
    start = today - timedelta(days=7)
    prev_start = today - timedelta(days=14)

    sleep_data = get_sleep_data(prev_start, today)
    hrv_rhr_data = get_hrv_data(days=14)
    sleep_durations = get_sleep_durations(days=14)
    # Defer the manifest write — if delivery fails, these changes must show
    # up again on the retry instead of being silently marked as seen.
    new_files = check_for_changes(commit=False)
    # Fetch 14 days of workouts for week-over-week weight comparison
    workouts = get_workouts(today - timedelta(days=14), today)
    # Fetch 28 days of weight for 4-week average
    weight_entries = get_weight(today - timedelta(days=28), today)
    responses = get_responses(limit=5)
    # BP spans year-to-date so the report's standing averages (week/30d/YTD) can render
    bp_entries = get_bp_data(date(today.year, 1, 1), today)
    # Fetch 14 days of wellness extras for week-over-week comparison
    wellness_data = get_extras(today - timedelta(days=14), today)
    readiness_data = get_readiness_data(prev_start, today)
    activity_data = get_activity_data(prev_start, today)
    baselines = _get_baselines()
    blood_result = get_blood_tests()
    blood_tests, blood_tests_parsed = blood_result if blood_result else (None, None)

    # Suppress blood test results that have already been shown in a prior weekly
    # email. Only show them when there's a test newer than the last one reported.
    latest_bt_date = _latest_blood_test_date(blood_tests_parsed)
    reported_bt_date = None
    try:
        from firestore_client import get_blood_test_reported_date
        reported_bt_date = get_blood_test_reported_date()
    except Exception as e:
        print(f"[main] Could not read blood test reported date: {e} — showing results")
    show_blood_tests = latest_bt_date is not None and (
        reported_bt_date is None or latest_bt_date > reported_bt_date
    )

    report, metadata = generate_report(
        sleep_data=sleep_data,
        workouts=workouts,
        weight_entries=weight_entries,
        new_files=new_files,
        blood_tests=blood_tests,
        blood_tests_parsed=blood_tests_parsed,
        responses=responses,
        hrv_rhr_data=hrv_rhr_data,
        sleep_durations=sleep_durations,
        bp_entries=bp_entries,
        wellness_data=wellness_data,
        readiness_data=readiness_data,
        activity_data=activity_data,
        baselines=baselines,
        report_type="weekly",
        start_date=start,
        end_date=today,
        show_blood_tests=show_blood_tests,
    )

    # Reuse cached analysis from generate_report() for Telegram questions
    questions = generate_questions(
        metadata.get("sleep", {}),
        metadata.get("exercise", {}),
        metadata.get("weight", {}),
        metadata.get("heart", {}),
    )

    result = _deliver_and_log("weekly", report, questions=questions)

    if result:
        from watcher import commit_manifest
        commit_manifest(new_files)

    _check_blood_test_sync_staleness()

    # Record that these results have now been shown, so they're suppressed next week.
    # Only after a successful delivery — otherwise they'd be suppressed without being seen.
    if result and show_blood_tests and latest_bt_date:
        try:
            from firestore_client import set_blood_test_reported_date
            set_blood_test_reported_date(latest_bt_date)
            print(f"[main] Marked blood test {latest_bt_date} as reported")
        except Exception as e:
            print(f"[main] Could not persist blood test reported date: {e}")

    return result


def _check_blood_test_sync_staleness():
    """Alert if a blood test PDF in Drive is newer than the Firestore mirror.

    Cloud Run can't parse the Drive PDFs itself — new tests only reach reports
    after a local parse mirrors them to Firestore. A newer PDF means reports
    are rendering stale blood test data until a local run happens.
    """
    from config import TEST_RESULTS_DRIVE_ID
    if not TEST_RESULTS_DRIVE_ID:
        return
    try:
        from watcher import _drive_scan_folder, _get_drive_service
        if _get_drive_service() is None:
            return
        files = _drive_scan_folder(TEST_RESULTS_DRIVE_ID, "Test Results")
        pdf_times = [
            datetime.fromisoformat(v["modified_time"].replace("Z", "+00:00"))
            for v in files.values()
            if v["name"].lower().endswith(".pdf")
        ]
        if not pdf_times:
            return
        newest = max(pdf_times)
        from firestore_client import get_blood_tests_updated_at
        synced = get_blood_tests_updated_at()
        if synced is None or newest > synced:
            synced_str = "never" if synced is None else f"{synced:%Y-%m-%d}"
            from notify import send_telegram
            send_telegram(
                "⚠️ Health OS: a blood test PDF in Drive is newer than the parsed data "
                f"(PDF modified {newest:%Y-%m-%d}, last local parse: {synced_str}). "
                "Run any local report or `main.py --labs <pdf>` to sync it."
            )
    except Exception as e:
        print(f"[main] Blood test staleness check failed: {e}")


def run_new_files():
    """Just check for new health folder additions."""
    from watcher import check_for_changes

    changes = check_for_changes()
    if changes.get("error"):
        print(f"[main] Error: {changes['error']}")
        return

    print(f"[main] Total files: {changes['total_files']}")
    print(f"[main] New: {len(changes.get('new', []))}")
    print(f"[main] Modified: {len(changes.get('modified', []))}")
    print(f"[main] Deleted: {len(changes.get('deleted', []))}")

    for s in changes.get("summaries", []):
        print(f"\n--- {s['file']} ---")
        print(s["preview"][:300])


def run_full():
    """Everything including blood test longitudinal analysis."""
    if datetime.now().hour < MIN_REPORT_HOUR:
        print(f"[main] Too early to run full report — skipping (current hour: {datetime.now().hour})")
        return None
    from sources import get_sleep_data, get_hrv_data, get_sleep_durations, wait_for_fresh_data
    from sources import get_workouts, get_weight, get_blood_tests, get_responses, get_bp_data
    from sources import get_readiness_data, get_activity_data
    from analyze import generate_report, generate_questions
    from watcher import check_for_changes

    if not wait_for_fresh_data(max_wait_minutes=30, interval_minutes=5, report_type="full"):
        print("[main] Skipping full report — no fresh sleep data")
        return None

    today = date.today()
    start = today - timedelta(days=7)
    prev_start = today - timedelta(days=14)

    sleep_data = get_sleep_data(prev_start, today)
    hrv_rhr_data = get_hrv_data(days=14)
    sleep_durations = get_sleep_durations(days=14)
    new_files = check_for_changes(commit=False)
    blood_result = get_blood_tests()
    blood_tests, blood_tests_parsed = blood_result if blood_result else (None, None)
    workouts = get_workouts(today - timedelta(days=14), today)
    weight_entries = get_weight(today - timedelta(days=28), today)
    responses = get_responses(limit=5)
    # BP spans year-to-date so the report's standing averages (week/30d/YTD) can render
    bp_entries = get_bp_data(date(today.year, 1, 1), today)
    readiness_data = get_readiness_data(prev_start, today)
    activity_data = get_activity_data(prev_start, today)
    baselines = _get_baselines()

    report, metadata = generate_report(
        sleep_data=sleep_data,
        workouts=workouts,
        weight_entries=weight_entries,
        new_files=new_files,
        blood_tests=blood_tests,
        blood_tests_parsed=blood_tests_parsed,
        responses=responses,
        hrv_rhr_data=hrv_rhr_data,
        sleep_durations=sleep_durations,
        bp_entries=bp_entries,
        readiness_data=readiness_data,
        activity_data=activity_data,
        baselines=baselines,
        report_type="weekly",
    )

    questions = generate_questions(
        metadata.get("sleep", {}),
        metadata.get("exercise", {}),
        metadata.get("weight", {}),
        metadata.get("heart", {}),
    )

    result = _deliver_and_log("full", report, questions=questions)

    if result:
        from watcher import commit_manifest
        commit_manifest(new_files)

    return result


def run_labs(pdf_path):
    """Parse a single blood test PDF and print plain-language explanation."""
    from blood_tests import parse_blood_test_pdf, explain_results, compare_to_history, parse_all_blood_tests

    pdf = Path(pdf_path)
    if not pdf.exists():
        print(f"[main] File not found: {pdf_path}")
        return None

    parsed = parse_blood_test_pdf(pdf)

    if not parsed["results"]:
        print(f"[main] No results extracted from {pdf_path}")
        return None

    # Re-parse the whole Health folder so the comparison sees every test and
    # the Firestore mirror Cloud Run reads picks up a newly added PDF.
    parse_all_blood_tests()

    explanation = explain_results(parsed)
    comparison = compare_to_history(parsed)

    output = explanation
    if comparison:
        output += "\n\n" + comparison

    print(output)

    report_path = REPORTS_DIR / f"labs_{parsed['date']}.md"
    report_path.write_text(output)
    print(f"\n[main] Report saved: {report_path}")
    return output


def main():
    parser = argparse.ArgumentParser(description="Health OS — Personal Health Operating System")
    parser.add_argument("--daily", action="store_true", help="Daily sleep snapshot")
    parser.add_argument("--weekly", action="store_true", help="Full weekly report")
    parser.add_argument("--new-files", action="store_true", help="Check for new health folder additions")
    parser.add_argument("--full", action="store_true", help="Everything including blood test analysis")
    parser.add_argument("--catchup", action="store_true", help="Run missed daily/weekly reports (skips if already sent today)")
    parser.add_argument("--labs", metavar="PDF", help="Parse and explain a single blood test PDF")
    parser.add_argument("--setup", action="store_true", help="Interactive setup wizard")
    parser.add_argument("--status", action="store_true", help="Show config and data source status")
    parser.add_argument("--monitor", action="store_true", help="Run anomaly checks and send alerts")

    args = parser.parse_args()

    if args.setup:
        from onboarding import run_setup
        run_setup()
    elif args.status:
        from onboarding import run_status
        run_status()
    elif args.monitor:
        from monitor import run_monitor
        run_monitor()
    elif args.catchup:
        # Run any reports that haven't been successfully sent today
        from sources import has_fresh_sleep_data

        ran = False
        if not already_reported("daily"):
            if has_fresh_sleep_data(date.today()):
                print("[main] Catch-up: running daily report...")
                run_daily()
                ran = True
            else:
                print("[main] Catch-up: daily report needed but sleep data not synced yet — skipping")
        else:
            print("[main] Daily report already sent today — skipping")

        # Check if it's Sunday and weekly hasn't run
        if date.today().weekday() == 6 and not already_reported("weekly"):
            if has_fresh_sleep_data(date.today()):
                print("[main] Catch-up: running weekly report...")
                run_weekly()
                ran = True
            else:
                print("[main] Catch-up: weekly report needed but sleep data not synced yet — skipping")

        if not ran:
            print("[main] Nothing to catch up — all reports already sent or data not ready")
    elif args.daily:
        if already_reported("daily"):
            print("[main] Daily report already sent today — skipping")
        else:
            run_daily()
    elif args.weekly:
        if already_reported("weekly"):
            print("[main] Weekly report already sent today — skipping")
        else:
            run_weekly()
    elif args.new_files:
        run_new_files()
    elif args.full:
        run_full()
    elif args.labs:
        run_labs(args.labs)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
