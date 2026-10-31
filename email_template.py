"""HTML email template for Health OS reports.

Renders report data as a clean, branded email that works across
Gmail, Apple Mail, and Outlook.
"""

import re
import markdown


# -- Design tokens --
BLUE_DARK = "#0A1628"
BLUE_PRIMARY = "#1A73E8"
BLUE_LIGHT = "#E8F0FE"
BLUE_ACCENT = "#4A90D9"
GRAY_50 = "#F8FAFC"
GRAY_100 = "#F1F5F9"
GRAY_200 = "#E2E8F0"
GRAY_400 = "#94A3B8"
GRAY_600 = "#475569"
GRAY_900 = "#0F172A"
WHITE = "#FFFFFF"
RED_LIGHT = "#FEF2F2"
RED_TEXT = "#DC2626"
GREEN_LIGHT = "#F0FDF4"
GREEN_TEXT = "#16A34A"
GREEN_SOFT = "#22C55E"
RED_SOFT = "#EF4444"


def _section_icon(title):
    """Map section titles to emoji icons."""
    icons = {
        "sleep": "🌙",
        "readiness": "🔋",
        "activity": "🏃",
        "hrv": "❤️",
        "exercise": "💪",
        "wellness": "🧘",
        "bodyweight": "⚖️",
        "blood test": "🩸",
        "blood pressure": "🩺",
        "what's new": "📂",
        "questions": "💬",
        "suggestions": "💡",
        "previous responses": "🔄",
    }
    lower = title.lower()
    for key, icon in icons.items():
        if key in lower:
            return icon
    return "📊"


def _render_table_html(md_table_lines):
    """Convert markdown table lines to styled HTML table."""
    if len(md_table_lines) < 2:
        return ""

    # Parse header
    headers = [h.strip() for h in md_table_lines[0].strip("|").split("|")]

    # Parse rows (skip separator line at index 1)
    rows = []
    for line in md_table_lines[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)

    html = f"""<table width="100%" cellpadding="0" cellspacing="0" style="
        border-collapse: collapse; margin: 16px 0 8px 0; font-size: 14px;">
        <thead>
            <tr>"""
    for h in headers:
        html += f"""
                <th style="padding: 10px 12px; text-align: left;
                    background: {BLUE_LIGHT}; color: {BLUE_DARK};
                    font-weight: 600; font-size: 12px;
                    text-transform: uppercase; letter-spacing: 0.5px;
                    border-bottom: 2px solid {BLUE_PRIMARY};">{h}</th>"""
    html += """
            </tr>
        </thead>
        <tbody>"""

    for i, row in enumerate(rows):
        bg = WHITE if i % 2 == 0 else GRAY_50
        html += f"""
            <tr style="background: {bg};">"""
        for cell in row:
            # Style flag icons
            styled_cell = cell
            if "⚠️" in cell:
                styled_cell = f'<span style="color: {RED_TEXT};">{cell}</span>'
            elif "✅" in cell:
                styled_cell = f'<span style="color: {GREEN_TEXT};">{cell}</span>'
            html += f"""
                <td style="padding: 9px 12px; border-bottom: 1px solid {GRAY_200};
                    color: {GRAY_900};">{styled_cell}</td>"""
        html += """
            </tr>"""

    html += """
        </tbody>
    </table>"""
    return html


def _render_flag(text):
    """Render a flag/warning line as a styled alert."""
    return f"""<div style="background: {RED_LIGHT}; border-left: 3px solid {RED_TEXT};
        padding: 8px 12px; margin: 6px 0; border-radius: 0 6px 6px 0;
        font-size: 14px; color: {RED_TEXT};">{text}</div>"""


def _render_pr(text):
    """Render a personal record as a styled highlight."""
    return f"""<div style="background: {GREEN_LIGHT}; border-left: 3px solid {GREEN_TEXT};
        padding: 8px 12px; margin: 6px 0; border-radius: 0 6px 6px 0;
        font-size: 14px; color: {GREEN_TEXT};">🏆 {text}</div>"""


_LOWER_IS_BETTER = {"systolic trend", "diastolic trend", "rhr trend", "resting heart rate trend"}


def _render_stat(label, value, sublabel=None):
    """Render a key metric as a stat card."""
    lower_is_better = label.lower() in _LOWER_IS_BETTER
    # For lower-is-better metrics (BP, RHR): ↑ is bad (red), ↓ is good (green)
    up_color = RED_SOFT if lower_is_better else GREEN_SOFT
    down_color = GREEN_SOFT if lower_is_better else RED_SOFT
    up_text = RED_TEXT if lower_is_better else GREEN_TEXT
    down_text = GREEN_TEXT if lower_is_better else RED_TEXT

    sub_html = ""
    if sublabel:
        if "↑" in sublabel or "up" in sublabel.lower():
            sub_color = up_text
        elif "↓" in sublabel or "down" in sublabel.lower():
            sub_color = down_text
        else:
            sub_color = GRAY_400
        sub_html = f'<div style="font-size: 12px; color: {sub_color}; margin-top: 2px;">{sublabel}</div>'

    # Color-code trend values
    value_color = GRAY_900
    if "↑" in str(value):
        value_color = up_color
    elif "↓" in str(value):
        value_color = down_color

    return f"""<td style="padding: 12px 16px; text-align: center;
        background: {GRAY_50}; border-radius: 8px;">
        <div style="font-size: 12px; color: {GRAY_400}; text-transform: uppercase;
            letter-spacing: 0.5px; font-weight: 500;">{label}</div>
        <div style="font-size: 24px; font-weight: 700; color: {value_color};
            margin-top: 4px;">{value}</div>
        {sub_html}
    </td>"""


def _parse_stat_value(line):
    """Extract label and value from a markdown stat line like '- **Label:** value'."""
    m = re.match(r'-\s*\*\*(.+?)\*\*:?\s*(.*)', line.strip())
    if m:
        return m.group(1).strip(":"), m.group(2).strip()
    return None, None


def render_email(report_markdown):
    """Convert a Health OS markdown report to a branded HTML email."""

    lines = report_markdown.split("\n")
    html_sections = []
    title = "Health OS Report"

    i = 0
    while i < len(lines):
        line = lines[i]

        # Main title
        if line.startswith("# "):
            title = line.lstrip("# ").strip()
            i += 1
            continue

        # Section header
        if line.startswith("## "):
            section_title = line.lstrip("## ").strip()
            icon = _section_icon(section_title)
            section_content = []
            stats = []
            table_lines = []
            i += 1

            # Collect section content until next ## or end
            while i < len(lines) and not lines[i].startswith("## "):
                sline = lines[i]

                # Subsection header (###)
                if sline.startswith("### "):
                    sub_title = sline.lstrip("# ").strip()
                    section_content.append(
                        f'<div style="font-size: 15px; font-weight: 600; color: {GRAY_900}; '
                        f'margin: 16px 0 8px 0;">{sub_title}</div>'
                    )
                    i += 1
                    continue

                # Table
                if sline.strip().startswith("|"):
                    table_lines = []
                    while i < len(lines) and lines[i].strip().startswith("|"):
                        table_lines.append(lines[i])
                        i += 1
                    section_content.append(_render_table_html(table_lines))
                    continue

                # Stat line (- **Label:** value)
                label, value = _parse_stat_value(sline)
                if label:
                    if "flag" in label.lower():
                        # Flags section — collect child items
                        i += 1
                        while i < len(lines) and lines[i].strip().startswith("- ⚠️"):
                            section_content.append(_render_flag(lines[i].strip().lstrip("- ")))
                            i += 1
                        continue
                    elif "contributors" in label.lower() or "durations" in label.lower():
                        # Contributors sub-list
                        i += 1
                        contrib_items = []
                        while i < len(lines) and lines[i].strip().startswith("- "):
                            item = lines[i].strip().lstrip("- ")
                            contrib_items.append(
                                f'<span style="display: inline-block; background: {BLUE_LIGHT}; '
                                f'color: {BLUE_PRIMARY}; padding: 4px 10px; border-radius: 12px; '
                                f'font-size: 13px; margin: 3px 4px 3px 0;">{item}</span>'
                            )
                            i += 1
                        section_content.append(
                            f'<div style="margin: 8px 0;">{"".join(contrib_items)}</div>'
                        )
                        continue
                    else:
                        stats.append((label, value))
                        i += 1
                        continue

                # Flag lines at root level
                if "⚠️" in sline:
                    section_content.append(_render_flag(sline.strip().lstrip("- ")))
                    i += 1
                    continue

                # PR lines
                if sline.strip().startswith("- **") and "PR" in section_title:
                    pr_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', sline.strip().lstrip("- "))
                    section_content.append(_render_pr(pr_text))
                    i += 1
                    continue

                # Italic text (errors)
                if sline.strip().startswith("_") and sline.strip().endswith("_"):
                    section_content.append(
                        f'<div style="color: {GRAY_400}; font-style: italic; '
                        f'font-size: 14px;">{sline.strip().strip("_")}</div>'
                    )
                    i += 1
                    continue

                # Regular bullet
                if sline.strip().startswith("- "):
                    item = sline.strip().lstrip("- ")
                    item = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', item)
                    section_content.append(
                        f'<div style="padding: 4px 0; font-size: 14px; color: {GRAY_900};">'
                        f'<span style="color: {BLUE_PRIMARY}; margin-right: 6px;">•</span>{item}</div>'
                    )
                    i += 1
                    continue

                # Numbered list (questions)
                if re.match(r'\d+\.', sline.strip()):
                    item = sline.strip()
                    item = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', item)
                    section_content.append(
                        f'<div style="padding: 6px 0; font-size: 14px; color: {GRAY_900}; '
                        f'border-bottom: 1px solid {GRAY_100};">{item}</div>'
                    )
                    i += 1
                    continue

                # Code block
                if sline.strip().startswith("```"):
                    code_lines = []
                    i += 1
                    while i < len(lines) and not lines[i].strip().startswith("```"):
                        code_lines.append(lines[i])
                        i += 1
                    i += 1  # skip closing ```
                    code = "\n".join(code_lines)
                    section_content.append(
                        f'<pre style="background: {GRAY_100}; padding: 12px; '
                        f'border-radius: 6px; font-size: 13px; '
                        f'white-space: pre-wrap; word-break: break-word; '
                        f'font-family: monospace; margin: 8px 0;">{code}</pre>'
                    )
                    continue

                # Skip empty lines
                i += 1

            # Build the stats grid
            stats_html = ""
            if stats:
                # Render as a row of stat cards (max 4 per row)
                cells = ""
                for label, value in stats:
                    cells += _render_stat(label, value)
                    cells += '<td width="8"></td>'  # spacer
                stats_html = f"""<table cellpadding="0" cellspacing="0" style="
                    width: 100%; margin: 8px 0 12px 0;">
                    <tr>{cells}</tr></table>"""

            # Assemble section
            section_html = f"""
            <div style="background: {WHITE}; border-radius: 12px;
                border: 1px solid {GRAY_200}; margin: 12px 0; overflow: hidden;">
                <div style="padding: 16px 20px 4px 20px;">
                    <div style="font-size: 17px; font-weight: 600; color: {GRAY_900};">
                        <span style="margin-right: 8px;">{icon}</span>{section_title}
                    </div>
                </div>
                <div style="padding: 4px 20px 16px 20px;">
                    {stats_html}
                    {"".join(section_content)}
                </div>
            </div>"""
            html_sections.append(section_html)
            continue

        # Footer
        if line.strip().startswith("---"):
            i += 1
            continue
        if line.strip().startswith("_Generated"):
            footer_text = line.strip().strip("_")
            html_sections.append(
                f'<div style="text-align: center; color: {GRAY_400}; font-size: 12px; '
                f'padding: 16px 0 8px 0;">{footer_text}</div>'
            )
            i += 1
            continue

        i += 1

    # Parse date from title
    date_match = re.search(r'\((.+?)\)', title)
    date_str = date_match.group(1) if date_match else ""
    clean_title = re.sub(r'\s*\(.+?\)', '', title)

    # Full email HTML
    return f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background: {GRAY_100};
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
    'Helvetica Neue', Arial, sans-serif; -webkit-font-smoothing: antialiased;">

<!-- Wrapper -->
<table width="100%" cellpadding="0" cellspacing="0" style="background: {GRAY_100};">
<tr><td align="center" style="padding: 24px 16px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; width: 100%;">

    <!-- Header -->
    <tr><td style="background: linear-gradient(135deg, {BLUE_DARK} 0%, {BLUE_PRIMARY} 100%);
        border-radius: 16px 16px 0 0; padding: 32px 24px; text-align: center;">
        <div style="font-size: 13px; font-weight: 500; color: {BLUE_ACCENT};
            text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px;">
            Luca's Health Dashboard</div>
        <div style="font-size: 24px; font-weight: 700; color: {WHITE};
            margin-bottom: 4px;">{clean_title}</div>
        <div style="font-size: 14px; color: {BLUE_ACCENT};">{date_str}</div>
    </td></tr>

    <!-- Body -->
    <tr><td style="background: {GRAY_50}; padding: 8px 16px 24px 16px;
        border-radius: 0 0 16px 16px;">
        {"".join(html_sections)}
    </td></tr>

    <!-- Footer -->
    <tr><td style="padding: 16px; text-align: center;">
        <div style="font-size: 11px; color: {GRAY_400};">
            Health OS — Your personal health operating system
        </div>
    </td></tr>

</table>
</td></tr>
</table>

</body>
</html>"""
