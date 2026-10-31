"""Notification delivery — Telegram Bot and Email (Gmail SMTP)."""

import re
import smtplib
import time
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email_template import render_email
from config import (
    GMAIL_ADDRESS, GMAIL_APP_PASSWORD,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_telegram(message):
    """Send a message via Telegram Bot API."""
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        print("[notify] Telegram not configured — skipping")
        return False

    # Telegram limit is 4096 chars per message — split if needed
    chunks = []
    if len(message) <= 4096:
        chunks = [message]
    else:
        lines = message.split("\n")
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 4000:
                chunks.append(chunk)
                chunk = line
            else:
                chunk += "\n" + line if chunk else line
        if chunk:
            chunks.append(chunk)

    for i, chunk in enumerate(chunks):
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "parse_mode": "Markdown",
            },
            timeout=15,
        )
        if resp.ok:
            print(f"[notify] Telegram sent ({i+1}/{len(chunks)})")
        else:
            # Retry without Markdown if parsing fails
            resp2 = requests.post(
                f"{TELEGRAM_API}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": chunk,
                },
                timeout=15,
            )
            if resp2.ok:
                print(f"[notify] Telegram sent plain ({i+1}/{len(chunks)})")
            else:
                print(f"[notify] Telegram failed: {resp2.text}")
                return False

    return True


def send_email(subject, body_markdown, max_attempts=3):
    """Send email via Gmail SMTP with the full report.

    Returns True on success, False after exhausting retries, None if Gmail
    isn't configured (intentional skip, not a failure).
    """
    if not all([GMAIL_ADDRESS, GMAIL_APP_PASSWORD]):
        print("[notify] Gmail not configured — skipping email")
        return None

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS  # send to self

    # Plain text fallback
    msg.attach(MIMEText(body_markdown, "plain"))

    # Branded HTML version
    styled_html = render_email(body_markdown)
    msg.attach(MIMEText(styled_html, "html"))

    for attempt in range(1, max_attempts + 1):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
                server.send_message(msg)
            print(f"[notify] Email sent: {subject}")
            return True
        except Exception as e:
            print(f"[notify] Email attempt {attempt}/{max_attempts} failed: {e}")
            if attempt < max_attempts:
                time.sleep(2 ** attempt)
    return False


def _trend_str(trend_dict):
    """Format a duration trend dict as '↑12m' or '→'."""
    if not trend_dict:
        return ""
    if trend_dict["delta_min"] == 0:
        return " →"
    return f" {trend_dict['arrow']}{trend_dict['delta_min']}m vs prev"


def _score_trend_str(trend):
    """Format a score trend as '↑3' or '→'."""
    if trend is None:
        return ""
    if trend == 0:
        return " →"
    arrow = "↑" if trend > 0 else "↓"
    return f" {arrow}{abs(trend)} vs prev"


from analyze import _fmt_duration


def format_telegram_summary(report_markdown, questions=None, metadata=None):
    """Create a concise Telegram-friendly summary.

    If metadata (analysis dicts) is provided, builds a clean structured message.
    Otherwise falls back to parsing the markdown.
    """
    if metadata and metadata.get("sleep"):
        return _format_telegram_from_metadata(metadata, questions)

    # Fallback: parse markdown (for weekly/full reports without metadata)
    return _format_telegram_from_markdown(report_markdown, questions)


def _format_telegram_from_metadata(metadata, questions=None):
    """Build a clean daily Telegram message from analysis dicts."""
    from datetime import date, datetime

    sleep = metadata.get("sleep", {})
    heart = metadata.get("heart", {})

    # Use the actual date from the data, not today's date
    last_night = sleep.get("last_night", {})
    data_day = last_night.get("day")
    if data_day:
        try:
            day_date = datetime.strptime(data_day, "%Y-%m-%d").date()
            day_str = day_date.strftime("%a %b %-d")
        except (ValueError, TypeError):
            day_str = date.today().strftime("%a %b %-d")
    else:
        day_str = date.today().strftime("%a %b %-d")

    msg = [f"🌙 *Sleep — {day_str}*"]

    # Last night's score + trend vs 7-day
    score = sleep.get("last_score")
    trend = sleep.get("trend")
    if score is not None:
        msg.append(f"Score: {score}{_score_trend_str(trend)}")

    # Last night's durations + trends
    last = sleep.get("last_night", {})
    deep_str = _fmt_duration(last.get("deep_sec"))
    rem_str = _fmt_duration(last.get("rem_sec"))
    total_str = _fmt_duration(last.get("total_sec"))

    msg.append(f"Deep: {deep_str}{_trend_str(sleep.get('deep_sleep_trend'))}")
    msg.append(f"REM: {rem_str}{_trend_str(sleep.get('rem_sleep_trend'))}")
    msg.append(f"Total: {total_str}{_trend_str(sleep.get('total_sleep_trend'))}")

    # Heart section
    if heart and not heart.get("error"):
        msg.append("")
        msg.append("❤️ *Heart*")
        daily = heart.get("daily", [])
        last_hrv = daily[-1]["hrv"] if daily and daily[-1].get("hrv") is not None else heart.get("avg_hrv")
        last_rhr = daily[-1]["rhr"] if daily and daily[-1].get("rhr") is not None else heart.get("avg_rhr")
        hrv_trend = heart.get("hrv_trend")
        rhr_trend = heart.get("rhr_trend")

        hrv_trend_str = ""
        if hrv_trend is not None:
            if hrv_trend == 0:
                hrv_trend_str = " →"
            else:
                arrow = "↑" if hrv_trend > 0 else "↓"
                hrv_trend_str = f" {arrow}{abs(hrv_trend)}ms vs prev"

        rhr_trend_str = ""
        if rhr_trend is not None:
            if rhr_trend == 0:
                rhr_trend_str = " →"
            else:
                arrow = "↑" if rhr_trend > 0 else "↓"
                rhr_trend_str = f" {arrow}{abs(rhr_trend)}bpm vs prev"

        if last_hrv is not None:
            msg.append(f"HRV: {last_hrv}ms{hrv_trend_str}")
        if last_rhr is not None:
            msg.append(f"RHR: {last_rhr}bpm{rhr_trend_str}")

    # Wellness section
    wellness = metadata.get("wellness")
    if wellness and not wellness.get("error"):
        msg.append("")
        msg.append("🧘 *Wellness*")
        for key, label in [("meditation", "Meditation"), ("sauna", "Sauna"), ("cold_plunge", "Cold Plunge")]:
            w = wellness.get(key, {})
            if not (w.get("sessions_this") or w.get("sessions_last")):
                continue
            delta = w.get("delta_total_min", 0)
            if delta > 0:
                delta_str = f" ↑{abs(delta)}min vs prev"
            elif delta < 0:
                delta_str = f" ↓{abs(delta)}min vs prev"
            else:
                delta_str = " →"
            msg.append(f"{label}: {w['sessions_this']}x · {w['total_min_this']}min{delta_str}")

    # Flags
    all_flags = sleep.get("flags", []) + heart.get("flags", [])
    if all_flags:
        msg.append("")
        for f in all_flags:
            msg.append(f"⚠️ {f}")

    # Top insights
    insights = metadata.get("insights", []) if metadata else []
    if insights:
        msg.append("")
        msg.append("💡 *Insight*")
        for insight in insights[:2]:
            msg.append(insight)

    if questions:
        msg.append("\n*Questions:*")
        for q in questions:
            msg.append(q)
        msg.append("\n_Reply with the question number + your answer_")

    return "\n".join(msg)


def _format_telegram_from_markdown(report_markdown, questions=None):
    """Legacy fallback: parse markdown into Telegram message."""
    lines = report_markdown.split("\n")
    sections = {}
    current_section = None

    for line in lines:
        if line.startswith("## "):
            current_section = line.lstrip("# ").strip()
            sections[current_section] = []
        elif current_section and (line.startswith("- **") or line.startswith("  - ")):
            sections[current_section].append(line)
        elif current_section and "⚠️" in line:
            sections[current_section].append(line.strip().lstrip("- "))

    msg = ["*Health OS Report*"]
    # Extract date range from markdown title if available
    title_line = lines[0] if lines else ""
    date_match = re.search(r'\((.+?)\)', title_line)
    subheader = f"_{date_match.group(1)}_" if date_match else "_7-day averages_"
    msg.append(subheader)

    if "Sleep" in sections:
        msg.append("\n🌙 *Sleep*")
        for line in sections["Sleep"]:
            if "Sleep Durations" in line and ":" in line and not any(c.isdigit() for c in line.split(":")[-1]):
                continue
            clean = line.strip().lstrip("- ")
            clean = clean.replace("7-Day ", "")
            msg.append(clean)

    for key in sections:
        if "HRV" in key or "Heart" in key:
            msg.append("\n❤️ *Heart*")
            for line in sections[key]:
                clean = line.strip().lstrip("- ")
                clean = clean.replace("7-Day ", "")
                msg.append(clean)
            break

    if "Wellness" in sections and sections["Wellness"]:
        msg.append("\n🧘 *Wellness*")
        for line in sections["Wellness"]:
            clean = line.strip().lstrip("- ")
            msg.append(clean)

    flags = []
    for items in sections.values():
        for line in items:
            if "⚠️" in line:
                flags.append(line.strip().lstrip("- "))
    if flags:
        msg.append("")
        for f in flags:
            msg.append(f)

    if questions:
        msg.append("\n*Questions:*")
        for q in questions:
            msg.append(q)
        msg.append("\n_Reply with the question number + your answer_")

    return "\n".join(msg)


def _build_email_subject(report_markdown):
    """Extract key metrics from the report to build a glanceable subject line."""
    from datetime import date

    today = date.today()
    is_daily = "Daily Snapshot" in report_markdown
    parts = []

    # Count flags
    flag_count = report_markdown.count("⚠️")
    if flag_count:
        parts.append(f"⚠️ {flag_count} flag{'s' if flag_count > 1 else ''}")

    # Sleep score + trend
    score_m = re.search(r"Average Score:\*\*\s*(\d+)", report_markdown)
    trend_m = re.search(r"Week Trend:\*\*\s*([↑↓→])\s*([\d.]+)", report_markdown)
    if score_m:
        sleep_str = f"Sleep {score_m.group(1)}"
        if trend_m:
            sleep_str += f" {trend_m.group(1)}{trend_m.group(2)}"
        parts.append(sleep_str)

    # HRV
    hrv_m = re.search(r"Avg HRV:\*\*\s*([\d.]+)\s*ms", report_markdown)
    if hrv_m:
        parts.append(f"HRV {hrv_m.group(1)}ms")

    # Resting HR
    rhr_m = re.search(r"Avg Resting HR:\*\*\s*([\d.]+)\s*bpm", report_markdown)
    if rhr_m:
        parts.append(f"RHR {rhr_m.group(1)}")

    # Workouts
    sessions_m = re.search(r"Total workouts:\*\*\s*(\d+)", report_markdown)
    if sessions_m and int(sessions_m.group(1)) > 0:
        n = sessions_m.group(1)
        parts.append(f"{n} session{'s' if int(n) != 1 else ''}")

    # Weight
    weight_m = re.search(r"Current:\*\*\s*([\d.]+)\s*lbs", report_markdown)
    if weight_m:
        parts.append(f"{weight_m.group(1)} lbs")

    date_str = today.strftime("%b %-d")
    if parts:
        metrics = " · ".join(parts)
        if is_daily:
            return f"{metrics} — {date_str}"
        else:
            return f"{metrics} — Week of {date_str}"

    # Fallback
    label = "Daily Snapshot" if is_daily else "Weekly Report"
    return f"Health OS {label} — {date_str}"


def deliver_report(report_markdown):
    """Send report via email only. Telegram is reserved for alerts and errors."""
    subject = _build_email_subject(report_markdown)
    email_ok = send_email(subject, report_markdown)

    return {"telegram": None, "email": email_ok}
