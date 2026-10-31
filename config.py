import base64
import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv

# Load environment
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

# Oura
OURA_TOKEN = os.getenv("OURA_TOKEN")

# Gmail
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Cloudflare Worker
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
RESPONSES_SECRET = os.getenv("RESPONSES_SECRET")

# Google Sheets
_SA_JSON_B64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
if _SA_JSON_B64:
    _sa_tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    _sa_tmp.write(base64.b64decode(_SA_JSON_B64).decode("utf-8"))
    _sa_tmp.flush()
    GOOGLE_SERVICE_ACCOUNT_FILE = Path(_sa_tmp.name)
else:
    GOOGLE_SERVICE_ACCOUNT_FILE = BASE_DIR / os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service_account.json"
    )
EXERCISE_SHEET_NAME = os.getenv("EXERCISE_SHEET_NAME", "Health OS - Exercise Log")
REPORTS_LOG_SHEET_NAME = os.getenv("REPORTS_LOG_SHEET_NAME", "Health OS - Reports Log")
BP_SHEET_KEY = os.getenv("BP_SHEET_KEY", "")

# Firestore (HealthOS App)
FIRESTORE_PROJECT_ID = os.getenv("FIRESTORE_PROJECT_ID", "your-firebase-project")

# Data source preferences (defaults match current behavior)
# Valid values: oura, apple_health, manual
SLEEP_SOURCE = os.getenv("SLEEP_SOURCE", "oura")
# Valid values: firestore, sheets, apple_health, manual
WORKOUT_SOURCE = os.getenv("WORKOUT_SOURCE", "firestore")
WEIGHT_SOURCE = os.getenv("WEIGHT_SOURCE", "firestore")

# Apple Health
APPLE_HEALTH_EXPORT = Path(os.getenv("APPLE_HEALTH_EXPORT")) if os.getenv("APPLE_HEALTH_EXPORT") else None

# Manual data entry
MANUAL_DATA_DIR = BASE_DIR / os.getenv("MANUAL_DATA_DIR", "data/manual")

# Paths
HEALTH_FOLDER = Path(os.getenv("HEALTH_FOLDER", ""))

# Drive folder IDs for "What's New" detection (Cloud Run can't see the local mount).
# Pull from the Drive URL: drive.google.com/drive/folders/<id>
HEALTH_NOTES_DRIVE_ID = os.getenv("HEALTH_NOTES_DRIVE_ID", "").strip()
TEST_RESULTS_DRIVE_ID = os.getenv("TEST_RESULTS_DRIVE_ID", "").strip()
OURA_CACHE_DIR = BASE_DIR / "data" / "oura_cache"
BLOOD_TESTS_JSON = BASE_DIR / "data" / "blood_tests.json"
FILE_MANIFEST = BASE_DIR / "data" / "file_manifest.json"
REPORTS_DIR = BASE_DIR / "reports"

# Ensure directories exist
OURA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
MANUAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
(BASE_DIR / "logs").mkdir(exist_ok=True)
