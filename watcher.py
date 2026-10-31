"""Health folder watcher — detects new/modified files via manifest comparison."""

import json
import os
from datetime import datetime
from pathlib import Path
from config import (
    HEALTH_FOLDER,
    FILE_MANIFEST,
    GOOGLE_SERVICE_ACCOUNT_FILE,
    HEALTH_NOTES_DRIVE_ID,
    TEST_RESULTS_DRIVE_ID,
)

GDOC_MIME = "application/vnd.google-apps.document"
FOLDER_MIME = "application/vnd.google-apps.folder"

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
except ImportError:
    service_account = None
    build = None

_drive_service = None


def _get_drive_service():
    global _drive_service
    if _drive_service is not None:
        return _drive_service
    if service_account is None or build is None:
        return None
    if not Path(GOOGLE_SERVICE_ACCOUNT_FILE).exists():
        return None
    creds = service_account.Credentials.from_service_account_file(
        str(GOOGLE_SERVICE_ACCOUNT_FILE),
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    _drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _drive_service


def _export_gdoc_by_id(doc_id, max_chars=2000):
    """Export a Google Doc as plain text via the Drive API."""
    service = _get_drive_service()
    if service is None:
        return "(Drive API unavailable — service account not configured)"
    try:
        data = service.files().export(fileId=doc_id, mimeType="text/plain").execute()
        text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
        return text[:max_chars]
    except Exception as e:
        return f"(Could not export Google Doc: {e})"


def _extract_gdoc_text(path, max_chars=2000):
    """Read a .gdoc pointer file and export the underlying Doc as plain text."""
    try:
        pointer = json.loads(Path(path).read_text())
        doc_id = pointer.get("doc_id") or pointer.get("resource_id", "").split(":")[-1]
    except Exception as e:
        return f"(Could not read .gdoc pointer: {e})"
    if not doc_id:
        return "(No doc_id in .gdoc pointer)"
    return _export_gdoc_by_id(doc_id, max_chars=max_chars)


EXCLUDED_PATH_SUBSTRINGS = ("HealthOS Reports", "Reports Log", "BP Monitoring")


def _is_excluded(rel_path):
    lower = rel_path.lower()
    for ex in EXCLUDED_PATH_SUBSTRINGS:
        if ex.lower() in lower:
            return True
    return False


def _scan_folder(folder):
    """Recursively scan folder, return dict of {relative_path: mtime}.

    Skips paths matching EXCLUDED_PATH_SUBSTRINGS — already covered elsewhere in the report.
    """
    files = {}
    folder = Path(folder)
    if not folder.exists():
        return files

    for path in folder.rglob("*"):
        if path.is_file() and not path.name.startswith("."):
            rel = str(path.relative_to(folder))
            if _is_excluded(rel):
                continue
            files[rel] = os.path.getmtime(path)
    return files


def _load_manifest():
    if FILE_MANIFEST.exists():
        return json.loads(FILE_MANIFEST.read_text())
    return {}


def _save_manifest(manifest):
    FILE_MANIFEST.write_text(json.dumps(manifest, indent=2))


def _extract_pdf_text(path, max_pages=5):
    """Extract text from a PDF file."""
    if PdfReader is None:
        return "(PyPDF2 not installed — cannot extract PDF text)"
    try:
        reader = PdfReader(str(path))
        text = ""
        for i, page in enumerate(reader.pages[:max_pages]):
            text += page.extract_text() or ""
        return text[:2000]  # cap at 2000 chars
    except Exception as e:
        return f"(Could not parse PDF: {e})"


def _drive_scan_folder(folder_id, label, parent_path=""):
    """Recursively list files under a Drive folder.

    Returns dict keyed by file ID:
      {file_id: {"name", "path", "modified_time", "mime_type", "label"}}
    where `path` is "<label>/<sub>/<name>" for display and `label` is the
    top-level folder name (e.g. "Health Notes" or "Test Results").
    """
    service = _get_drive_service()
    if service is None:
        return {}

    files = {}
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, modifiedTime, mimeType)",
            pageSize=100,
            pageToken=page_token,
        ).execute()
        for f in resp.get("files", []):
            name = f["name"]
            display_path = f"{parent_path}/{name}" if parent_path else f"{label}/{name}"
            if f["mimeType"] == FOLDER_MIME:
                files.update(_drive_scan_folder(f["id"], label, parent_path=display_path))
            else:
                files[f["id"]] = {
                    "name": name,
                    "path": display_path,
                    "modified_time": f["modifiedTime"],
                    "mime_type": f["mimeType"],
                    "label": label,
                }
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def _check_drive_changes(commit=True):
    """Drive-API-based watcher. Used when HEALTH_NOTES_DRIVE_ID and TEST_RESULTS_DRIVE_ID are set."""
    from firestore_client import get_file_manifest, set_file_manifest

    if _get_drive_service() is None:
        return {"error": "Drive API unavailable — service account not configured"}

    try:
        current = {}
        current.update(_drive_scan_folder(HEALTH_NOTES_DRIVE_ID, "Health Notes"))
        current.update(_drive_scan_folder(TEST_RESULTS_DRIVE_ID, "Test Results"))
    except Exception as e:
        return {"error": f"Drive scan failed: {e}"}

    try:
        old_manifest = get_file_manifest()
    except Exception as e:
        return {"error": f"Could not load file manifest from Firestore: {e}"}

    # Persist current state in serializable form (only the keys we need to compare).
    new_manifest = {fid: {"path": v["path"], "modified_time": v["modified_time"]}
                    for fid, v in current.items()}

    # First run (manifest empty / missing) — silently seed it without flooding the report.
    if not old_manifest:
        if commit:
            try:
                set_file_manifest(new_manifest)
            except Exception as e:
                return {"error": f"Could not write file manifest to Firestore: {e}"}
        return {"new": [], "modified": [], "deleted": [], "summaries": [],
                "total_files": len(current), "manifest": new_manifest}

    new_ids = []
    modified_ids = []
    for fid, meta in current.items():
        prev = old_manifest.get(fid)
        if prev is None:
            new_ids.append(fid)
        elif prev.get("modified_time") != meta["modified_time"]:
            modified_ids.append(fid)

    deleted_paths = [v["path"] for fid, v in old_manifest.items() if fid not in current]

    new_paths = sorted(current[fid]["path"] for fid in new_ids)
    modified_paths = sorted(current[fid]["path"] for fid in modified_ids)

    # Previews: only Health Notes .gdoc files (Test Results are list-only by design).
    summaries = []
    for fid in new_ids + modified_ids:
        meta = current[fid]
        if meta["label"] != "Health Notes":
            continue
        if meta["mime_type"] != GDOC_MIME:
            continue
        text = _export_gdoc_by_id(fid)
        summaries.append({"file": meta["path"], "preview": text[:500]})

    if commit:
        try:
            set_file_manifest(new_manifest)
        except Exception as e:
            print(f"[watcher] Warning: could not persist file manifest: {e}")

    return {
        "new": new_paths,
        "modified": modified_paths,
        "deleted": deleted_paths,
        "summaries": summaries,
        "total_files": len(current),
        "manifest": new_manifest,
    }


def _check_filesystem_changes(commit=True):
    """Local filesystem watcher (fallback when Drive IDs aren't configured)."""
    # Path("") resolves to PosixPath('.') — guard against unset env var, which would
    # otherwise scan the current working directory (e.g. /app on Cloud Run).
    raw = os.getenv("HEALTH_FOLDER", "").strip()
    if not raw or not Path(raw).exists():
        return {"error": f"Health folder not configured or not found: {raw or '<unset>'}"}

    old_manifest = _load_manifest()
    current = _scan_folder(HEALTH_FOLDER)

    new_files = []
    modified_files = []
    deleted_files = []

    for path, mtime in current.items():
        if path not in old_manifest:
            new_files.append(path)
        elif mtime > old_manifest[path]:
            modified_files.append(path)

    for path in old_manifest:
        if path not in current:
            deleted_files.append(path)

    # Extract summaries for new/modified files
    summaries = []
    for path in new_files + modified_files:
        full_path = Path(HEALTH_FOLDER) / path
        lower = path.lower()
        if lower.endswith(".pdf"):
            text = _extract_pdf_text(full_path)
            summaries.append({"file": path, "preview": text[:500]})
        elif lower.endswith((".txt", ".md")):
            try:
                text = full_path.read_text(errors="replace")
                summaries.append({"file": path, "preview": text[:500]})
            except Exception as e:
                summaries.append({"file": path, "preview": f"(Could not read: {e})"})
        elif lower.endswith(".gdoc"):
            text = _extract_gdoc_text(full_path)
            summaries.append({"file": path, "preview": text[:500]})
        else:
            summaries.append({"file": path, "preview": f"({full_path.suffix} file)"})

    if commit:
        _save_manifest(current)

    return {
        "new": new_files,
        "modified": modified_files,
        "deleted": deleted_files,
        "summaries": summaries,
        "total_files": len(current),
        "manifest": current,
    }


def check_for_changes(commit=True):
    """Detect new/modified files. Uses Drive API when configured, else filesystem.

    commit=False defers persisting the manifest — the detected changes stay
    pending until the caller confirms delivery via commit_manifest(changes).
    Report flows use this so changes aren't marked seen if the report fails.
    """
    if HEALTH_NOTES_DRIVE_ID and TEST_RESULTS_DRIVE_ID:
        return _check_drive_changes(commit=commit)
    return _check_filesystem_changes(commit=commit)


def commit_manifest(changes):
    """Persist the manifest captured by check_for_changes(commit=False)."""
    manifest = (changes or {}).get("manifest")
    if manifest is None:
        return
    if HEALTH_NOTES_DRIVE_ID and TEST_RESULTS_DRIVE_ID:
        try:
            from firestore_client import set_file_manifest
            set_file_manifest(manifest)
        except Exception as e:
            print(f"[watcher] Warning: could not persist file manifest: {e}")
    else:
        _save_manifest(manifest)
