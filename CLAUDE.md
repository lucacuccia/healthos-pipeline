# Health OS — Project Instructions

Personal health operating system that pulls data from Oura Ring, Firestore (HealthOS iOS app), and Google Drive, then analyzes trends and delivers reports via email. Telegram is reserved for alerts and operational notices (sync failures, anomalies, data errors).

## How to run manually
```bash
# Daily sleep snapshot
venv/bin/python3 main.py --daily

# Weekly full report
venv/bin/python3 main.py --weekly

# Check for new health folder files
venv/bin/python3 main.py --new-files

# Full report including blood test longitudinal analysis
venv/bin/python3 main.py --full

# Parse and explain a single blood test PDF
venv/bin/python3 main.py --labs path/to/blood_test.pdf

# Run missed reports (skips if already sent today)
venv/bin/python3 main.py --catchup

# Interactive setup wizard
venv/bin/python3 main.py --setup

# Show config and data source status
venv/bin/python3 main.py --status

# Run anomaly checks and send alerts
venv/bin/python3 main.py --monitor
```

## Tests
```bash
venv/bin/python3 -m pytest tests/ -q
```
No network — Firestore, SMTP, and Telegram are mocked. The blood test parser golden-file tests (real lab PDFs) are kept out of this public copy. Dev deps: `venv/bin/pip install -r requirements-dev.txt`.

## Key paths
- **Config & secrets:** `.env` (gitignored)
- **Google service account:** `credentials/service_account.json` (gitignored)
- **Health folder:** Google Drive > Health (mounted at `~/Library/CloudStorage/GoogleDrive-<your-gmail>/My Drive/Health`)
- **Drive folder IDs (Cloud Run "What's New"):** `HEALTH_NOTES_DRIVE_ID`, `TEST_RESULTS_DRIVE_ID` env vars; manifest stored in Firestore `health_folder_manifest/current`
- **Blood test data (Cloud Run):** full parsed data — latest test date, longitudinal view, and per-test results — mirrored to Firestore `health_meta/blood_tests` by `blood_tests.py` on every local parse. Cloud Run can't see the Drive PDFs, so it reads this to render blood test trends + the latest-results explanation in the weekly report (and to fire the 6-month reminder). New tests reach Firestore only when `parse_all_blood_tests()` runs locally, and nothing runs it automatically. Local `--labs <pdf>`, `--daily`, `--weekly`, and `--full` runs call it (so does `--catchup`, but only when it actually sends a report). After adding a PDF to Drive, run `main.py --labs <pdf>` locally to sync it; the PDF must be under the Health folder's `Test Results/Blood Tests/` to be included. The weekly run sends a Telegram alert if a Drive PDF is newer than the mirror (`_check_blood_test_sync_staleness` in `main.py`).
- **Reports:** `reports/`
- **Oura cache:** `data/oura_cache/`

## Scheduling
- Daily Mon–Sat 9 AM ET: sleep snapshot via Cloud Scheduler → Cloud Run (`healthos-reports` service, `/daily`)
- Weekly Sunday 9 AM ET: full report via Cloud Scheduler → Cloud Run (`healthos-reports` service, `/weekly`)
- Both first attempts run at 9 AM so Oura has time to sync before the "no data yet" Telegram nudge fires
- Retries: Cloud Scheduler retry jobs at 10 AM ET (`healthos-daily-retry` Mon–Sat, `healthos-weekly-retry` Sun) re-trigger if the 9 AM run missed. Safe because Cloud Run dedups via `claim_report_slot()` (atomic Firestore transaction on `report_log/<date>`); the slot is released if the run errors, data isn't ready, or email fails, so the retry can still send
- On-demand: `/health-report` skill in Claude Code, or `main.py --catchup` locally

## Deploying to Cloud Run
**Any code change that affects report output requires a redeploy** — Cloud Run runs from a Docker image, not the local repo. Push to `main` does NOT auto-deploy.

```bash
gcloud run deploy healthos-reports --source . --region europe-west1
```

The Dockerfile copies every root-level `*.py` file, so a change to **any** of them (including `main.py`, which holds `run_daily`/`run_weekly`, plus `baselines.py`, `blood_tests.py`, `lab_reference.py`, `sheets.py`, `config.py`) needs a redeploy to reach Cloud Run. Same for `requirements.txt` and `Dockerfile`.

There is no local scheduling (no launchd jobs); Cloud Scheduler → Cloud Run handles it so reports fire even when the laptop is off. Locally, `--daily`, `--weekly`, and `--catchup` check `already_reported()` (local `reports/` file or Firestore `report_log/<date>`) before sending as a dedup safety net. On Firestore errors it returns True (skip) to avoid duplicates.

All reports wait for fresh Oura data before generating. If sleep data isn't synced yet, a Telegram alert is sent and the script retries for up to 30 min.

## Architecture
- `sources.py` — Unified data layer with configurable source preferences + fallback chains
- `oura.py` — Oura API v2 client with local caching + data freshness checks
- `firestore_client.py` — Firestore reader/writer. Reads workouts, bodyweight, wellness extras, and blood pressure (`bloodpressure` — one doc per AM/PM session, merged per day with HR + notes) written by the HealthOS iOS app (primary source). Also reads/writes the Drive file manifest (`health_folder_manifest/current`) and the full parsed blood test data (`health_meta/blood_tests` — latest date, longitudinal view, per-test results) used by Cloud Run, and the `report_log/<date>` dedup doc.
- `sheets.py` — Google Sheets reader/writer (fallback for workout/weight/BP + report logging). The BP Monitoring sheet is only a silent fallback for BP; new entries go through the iOS app into Firestore (`scripts/migrate_bp_to_firestore.py` is the idempotent sheet-to-Firestore importer).
- `analyze.py` — Trend analysis + report generation
- `notify.py` — Email (Gmail SMTP) for reports; Telegram Bot for alerts/errors only
- `watcher.py` — Health folder change detection. Drive API mode (Cloud Run) when `HEALTH_NOTES_DRIVE_ID` + `TEST_RESULTS_DRIVE_ID` are set; manifest in Firestore. Filesystem fallback otherwise (manifest in `data/file_manifest.json`).
- `apple_health.py` — Apple Health export.xml streaming parser (sleep, HRV, weight, workouts)
- `manual_entry.py` — JSON/CSV manual data entry for backfilling gaps
- `blood_tests.py` — PDF parser for blood test results + plain-language explanations + history comparison
- `lab_reference.py` — Optimal ranges, system groupings, and plain-language descriptions for 61 lab markers
- `correlate.py` — Cross-source insights: recovery score, sleep-workout correlation, HRV-training analysis, blood test reminders
- `monitor.py` — Anomaly detection with configurable thresholds, alert deduplication, Telegram push alerts
- `onboarding.py` — Interactive setup wizard (`--setup`) and status dashboard (`--status`)
- `main.py` — CLI orchestrator; also holds `run_daily`/`run_weekly` and the dedup helpers (`already_reported`, `claim_report_slot`, `release_report_slot`) used by Cloud Run
- `baselines.py` — Rolling ~60-day per-metric baselines (mean ± SD); the single definition of "abnormal" shared by `analyze.py` flags and `monitor.py` alerts (`BASELINE_SD_THRESHOLD`, `BASELINE_MIN_SAMPLES`)
- `config.py` — Environment variable loading + path configuration
- `email_template.py` — Branded HTML email rendering
- `cloudrun_handler.py` — Flask HTTP entrypoint for Cloud Run (POST /daily, POST /weekly with `Authorization: Bearer $CLOUD_RUN_AUTH_TOKEN`; unauthenticated GET /health liveness probe)
- Telegram reply handling runs in a separate Cloudflare Worker (not included in this public copy)

## GitHub
Public snapshot of a private working repo. Development, issues, and history live there.
