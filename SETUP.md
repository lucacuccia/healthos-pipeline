# Health OS — Setup Guide

Get Health OS running with your own data sources. The fastest path is the interactive wizard (`--setup`), but this doc covers everything if you prefer manual setup.

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/lucacuccia/healthos-pipeline.git
cd health-os
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 2. Run the setup wizard
venv/bin/python3 main.py --setup

# 3. Verify everything works
venv/bin/python3 main.py --status
```

The wizard walks you through each credential, validates as you go, and writes your `.env` file. You can also copy `.env.template` to `.env` and fill it in manually.

## Credential Setup

### Oura Ring (sleep, HRV, resting HR)

1. Go to [cloud.ouraring.com/personal-access-tokens](https://cloud.ouraring.com/personal-access-tokens)
2. Create a new personal access token
3. Copy the token — you won't see it again

### Google Cloud Service Account (Sheets + Firestore)

Used for both Google Sheets and Firestore. You only need one service account.

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project (or use an existing one)
3. Enable the **Google Sheets API** and **Cloud Firestore API**
4. Go to **IAM & Admin > Service Accounts** and create a new service account
5. Create a JSON key and download it
6. Place the file at `credentials/service_account.json`
7. If using Sheets: share your Google Sheet with the service account email (the `client_email` in the JSON)

### Telegram Bot (report delivery)

1. Open Telegram and message [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow the prompts to create a bot
3. Copy the bot token
4. To get your chat ID, message [@userinfobot](https://t.me/userinfobot)
5. Send any message to your new bot first (so it has permission to message you)

### Gmail App Password (email delivery)

1. Enable 2-Factor Authentication on your Google account
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Create an app password for "Mail"
4. Copy the 16-character password

### Apple Health Export (optional)

1. On your iPhone: **Health app > Profile picture > Export All Health Data**
2. Unzip the export
3. Set `APPLE_HEALTH_EXPORT` to the path of `export.xml`

Note: Apple Health exports are snapshots — re-export periodically for fresh data.

## Data Source Options

You can mix and match sources for each data type:

| Data Type | Options | Default |
|-----------|---------|---------|
| **Sleep** | `oura`, `apple_health`, `manual` | `oura` |
| **Workouts** | `firestore`, `sheets`, `apple_health`, `manual` | `firestore` |
| **Weight** | `firestore`, `sheets`, `apple_health`, `manual` | `firestore` |

Set these in `.env` via `SLEEP_SOURCE`, `WORKOUT_SOURCE`, `WEIGHT_SOURCE`.

**Recommended starting point:** If you have an Oura Ring, start with `oura` for sleep and `manual` for workouts/weight. Add Firestore or Sheets later when you want automated tracking.

### Manual Data Entry

Place JSON or CSV files in `data/manual/`:

- `sleep.json` — fields: `day`, `score`, `contributors`
- `workouts.json` — fields: `date`, `day_type`, `exercise`, `sets`, `reps`, `weight`, `volume`
- `weight.json` — fields: `date`, `weight`
- `hrv.json` — fields: `day`, `avg_hrv`, `lowest_hr`, `avg_hr`

## Verifying Your Setup

Run `--status` to see what's working:

```bash
venv/bin/python3 main.py --status
```

- **OK** — source is configured and reachable
- **ERR** — configured but failing (check the error message)
- **--** — not configured (fine if you're not using that source)

## Scheduling Reports

Reports are automated via **Google Cloud Scheduler → Cloud Run** (`healthos-reports` service, `europe-west1`) — no local scheduling required.

| Schedule (ET) | Job | Endpoint |
|---------------|-----|----------|
| Daily 9 AM Mon–Sat | `healthos-daily` | `/daily` |
| Weekly Sunday 9 AM | `healthos-weekly` | `/weekly` |
| Retries 10 AM | `healthos-daily-retry` / `healthos-weekly-retry` | `/daily`, `/weekly` |

To run a missed report manually: `python main.py --catchup` (skips anything already sent).

## Troubleshooting

**"OURA_TOKEN not set" or "HTTP 401"**
- Token may be expired — regenerate at [cloud.ouraring.com](https://cloud.ouraring.com/personal-access-tokens)

**"Could not open sheet"**
- Make sure the Google Sheet is shared with the service account email
- Check that `EXERCISE_SHEET_NAME` matches the exact sheet name

**"Firestore connection failed"**
- Verify the Firestore API is enabled in your Google Cloud project
- Check that `FIRESTORE_PROJECT_ID` matches your project

**"Gmail authentication failed"**
- Must use an App Password, not your regular Gmail password
- 2FA must be enabled on the Google account

**"Apple Health file not found"**
- Check the path in `APPLE_HEALTH_EXPORT` — must point to `export.xml`, not the zip

**No sleep data in daily report**
- Oura data syncs when you open the app — open it and wait a few minutes
- The 10 AM Cloud Scheduler retry jobs will re-attempt automatically; or run `python main.py --catchup` manually
