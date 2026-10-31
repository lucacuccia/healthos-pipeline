# Health OS

Personal health operating system that aggregates data from wearables, spreadsheets, and medical records — then delivers automated reports via email, with Telegram used for alerts and operational notices.

## What it does

- **Daily sleep snapshots** — last night's sleep quality, HRV, resting heart rate, and activity vs. 7-day averages (delivered every morning)
- **Weekly health reports** — sleep trends, readiness/activity summary, exercise summary, weight tracking, blood pressure trends, and new health document alerts
- **Personal baselines** — rolling 60-day mean ± SD per metric, so report flags and anomaly alerts fire on deviation from *your* normal instead of universal thresholds
- **Wellness tracking** — meditation, sauna, and cold plunge sessions from the iOS app, with week-over-week trends and sleep/HRV correlations
- **Blood test analysis** — parses lab result PDFs with plain-language explanations, optimal range flags, and longitudinal tracking
- **Health folder monitoring** — detects new files in a Google Drive health folder, with text previews for PDFs and Google Docs

Reports are delivered via branded HTML email and logged to Google Sheets for history. Telegram is used only for operational alerts (sync failures, anomalies, data errors).

## Data sources

| Source | Data |
|--------|------|
| Oura Ring API | Sleep, HRV, resting heart rate, readiness, activity |
| Firestore (HealthOS iOS app) | Workouts, bodyweight, blood pressure, wellness (meditation/sauna/cold plunge) |
| Google Sheets | Exercise log, bodyweight, blood pressure (all fallback), report logging |
| Google Drive | Health documents (lab results, medical records) |
| Blood test PDFs | Parsed biomarker values over time |

## Architecture

```
main.py                CLI orchestrator (--daily, --weekly, --full, --labs, --new-files, --catchup, --setup, --status, --monitor)
cloudrun_handler.py    Flask HTTP entrypoint for Cloud Run (POST /daily, POST /weekly)
sources.py             Unified data layer with configurable source preferences + fallback chains
oura.py                Oura API v2 client (sleep, readiness, activity) with local caching + data freshness checks
firestore_client.py    Firestore reader/writer — workouts/weight/BP/extras (from iOS app), Drive file manifest, parsed blood test data (for Cloud Run)
sheets.py              Google Sheets reader/writer (fallback for workout/weight/BP + report log)
baselines.py           Personal baselines (rolling 60-day mean ± SD per metric) shared by report flags and alerts
analyze.py             Trend analysis + report generation
correlate.py           Cross-source insights (sleep vs workouts, HRV vs training, recovery from Oura readiness)
monitor.py             Anomaly detection with baseline-aware thresholds + Telegram alerts
blood_tests.py         PDF parser for blood test results + plain-language explanations
lab_reference.py       Optimal ranges, system groupings, and explanations for 61 lab markers
apple_health.py        Apple Health export.xml streaming parser (sleep, HRV, weight, workouts)
manual_entry.py        JSON/CSV manual data entry for backfilling gaps
watcher.py             Health folder change detection (Drive API on Cloud Run, filesystem locally)
notify.py              Telegram Bot + Gmail SMTP delivery
email_template.py      Branded HTML email rendering
onboarding.py          Interactive setup wizard + status dashboard
config.py              Environment variable loading + path configuration
```

## Setup

### Prerequisites

- Python 3.12+
- [Oura Ring](https://ouraring.com/) personal access token
- Google Cloud service account with Sheets, Drive, and Firestore APIs enabled
- Telegram bot (via [@BotFather](https://t.me/botfather))
- Gmail app password for email delivery

### Installation

```bash
git clone https://github.com/lucacuccia/healthos-pipeline.git
cd health-os
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

The easiest way to configure is the interactive wizard:

```bash
python main.py --setup
```

Or copy `.env.template` to `.env` and fill in your values manually. See [SETUP.md](SETUP.md) for detailed credential setup instructions.

## Usage

```bash
# Daily sleep snapshot
python main.py --daily

# Weekly full report
python main.py --weekly

# Check for new health folder files
python main.py --new-files

# Full report including blood test longitudinal analysis
python main.py --full

# Parse and explain a single blood test PDF
python main.py --labs path/to/blood_test.pdf

# Run missed reports (skips if already sent today)
python main.py --catchup

# Interactive setup wizard
python main.py --setup

# Show config and data source status
python main.py --status

# Run anomaly checks and send Telegram alerts
python main.py --monitor
```

## Scheduling

Automated via **Google Cloud Scheduler → Cloud Run** (fires even when laptop is off):

- **Daily Mon–Sat at 8:00 AM ET** — sleep snapshot (`healthos-reports` Cloud Run service, `/daily`)
- **Weekly Sunday at 9:00 AM ET** — full report (`healthos-reports` Cloud Run service, `/weekly`)
- **Retries at 10:00 AM ET** — Cloud Scheduler retry jobs (`healthos-daily-retry` Mon–Sat, `healthos-weekly-retry` Sunday) re-trigger if the scheduled run missed

All reports wait for fresh Oura sleep data before generating. If data hasn't synced yet, a Telegram alert is sent and the script retries every 5 minutes for up to 30 minutes.

Deduplication is tracked in Firestore (`report_log/{date}`) so retries and simultaneous triggers never produce duplicate deliveries.

## License

Personal project, shared for reference. No license is granted for reuse.
