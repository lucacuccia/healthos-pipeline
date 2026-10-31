# syntax=docker/dockerfile:1
FROM python:3.12-slim

# grpcio (Firestore) needs gcc/g++ on slim
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt flask gunicorn

COPY *.py ./

ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV SKIP_LOCAL_REPORT_WRITE=1

# Single worker — prevents race conditions on same-day dedup checks.
# Timeout 3600s — Oura polling can take up to 30 min; gunicorn default (30s) would kill it.
CMD exec gunicorn --bind "0.0.0.0:$PORT" --workers 1 --threads 1 --timeout 3600 cloudrun_handler:app
