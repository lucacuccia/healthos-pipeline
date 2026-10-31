"""Cloud Run HTTP entrypoint for Health OS scheduled reports.

Routes:
  POST /daily   — triggers run_daily()
  POST /weekly  — triggers run_weekly()
  GET  /health  — unauthenticated liveness probe

Auth: Authorization: Bearer <CLOUD_RUN_AUTH_TOKEN>
"""

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, request, jsonify

app = Flask(__name__)

_AUTH_TOKEN = os.getenv("CLOUD_RUN_AUTH_TOKEN", "").strip()


def _check_auth():
    if not _AUTH_TOKEN:
        return False  # fail-safe: reject all requests if token not configured
    return request.headers.get("Authorization", "") == f"Bearer {_AUTH_TOKEN}"


def _run_report(report_type):
    try:
        from main import run_daily, run_weekly, claim_report_slot, release_report_slot
        run_fn = run_daily if report_type == "daily" else run_weekly
        if not claim_report_slot(report_type):
            return jsonify({"status": "skipped", "reason": "already reported today"}), 200
        try:
            result = run_fn()
        except Exception:
            # Release the claim, otherwise the scheduler's retry would see
            # "already reported today" and the report would never send.
            release_report_slot(report_type)
            raise
        if result is None:
            release_report_slot(report_type)
            return jsonify({"status": "skipped", "reason": "data not ready"}), 200
        return jsonify({"status": "ok", "chars": len(result)}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/daily", methods=["POST"])
def daily():
    if not _check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    return _run_report("daily")


@app.route("/weekly", methods=["POST"])
def weekly():
    if not _check_auth():
        return jsonify({"error": "Unauthorized"}), 401
    return _run_report("weekly")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
