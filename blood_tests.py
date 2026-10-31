"""Parse blood test PDFs into structured JSON for longitudinal tracking."""

import json
import re
from pathlib import Path
from datetime import datetime
from config import HEALTH_FOLDER, BLOOD_TESTS_JSON

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    from lab_reference import SYSTEMS, get_marker_info, get_optimal_flag, get_system_for_marker
    _HAS_LAB_REF = True
except ImportError:
    _HAS_LAB_REF = False


# Canonical test name mapping — normalizes across NHS, Quest, and MyChart naming
_NAME_MAP = {
    "cholesterol, total": "Total Cholesterol",
    "serum cholesterol": "Total Cholesterol",
    "hdl cholesterol": "HDL Cholesterol",
    "serum hdl cholesterol level": "HDL Cholesterol",
    "triglycerides": "Triglycerides",
    "serum triglycerides": "Triglycerides",
    "ldl-cholesterol": "LDL Cholesterol",
    "ldl cholesterol calc": "LDL Cholesterol",
    "white blood cell": "WBC",
    "total white cell count": "WBC",
    "red blood cell": "RBC",
    "red blood cell (rbc) count": "RBC",
    "hemoglobin": "Hemoglobin",
    "haemoglobin estimation": "Hemoglobin",
    "hematocrit": "Hematocrit",
    "haematocrit": "Hematocrit",
    "mean cell volume": "MCV",
    "mean corpuscular volume (mcv)": "MCV",
    "mean cell hemoglobin": "MCH",
    "mean corpusc. haemoglobin(mch)": "MCH",
    "mean cell hemoglobin concentration": "MCHC",
    "mean corpusc. hb. conc. (mchc)": "MCHC",
    "red cell distribution width": "RDW",
    "red blood cell distribut width": "RDW",
    "platelet": "Platelets",
    "platelet count": "Platelets",
    "neutrophil automated": "Neutrophils %",
    "neutrophil count": "Neutrophils",
    "lymphocyte automated": "Lymphocytes %",
    "lymphocyte count": "Lymphocytes",
    "monocyte automated": "Monocytes %",
    "monocyte count": "Monocytes",
    "eosinophil automated": "Eosinophils %",
    "eosinophil count": "Eosinophils",
    "basophil automated": "Basophils %",
    "basophil count": "Basophils",
    "serum creatinine": "Creatinine",
    "creatinine": "Creatinine",
    "serum potassium": "Potassium",
    "potassium level": "Potassium",
    "serum chloride": "Chloride",
    "chloride level": "Chloride",
    "sodium level": "Sodium",
    "serum albumin": "Albumin",
    "albumin": "Albumin",
    "serum alt level": "ALT",
    "serum alkaline phosphatase": "ALP",
    "alkaline phosphatase": "ALP",
    "serum total bilirubin level": "Total Bilirubin",
    "total bilirubin": "Total Bilirubin",
    "serum ferritin": "Ferritin",
    "serum free t4 level": "Free T4",
    "serum tsh level": "TSH",
    "tsh": "TSH",
    "hba1c levl - ifcc standardised": "HbA1c",
    "hemoglobin a1c": "HbA1c",
    "testosterone, total, males (adult), ia": "Testosterone",
    "testosterone,total, males (adult), ia": "Testosterone",
    "fsh": "FSH",
    "lh": "LH",
    "homocysteine": "Homocysteine",
    "vitamin b12": "Vitamin B12",
    "25-hydroxyvitamin d": "Vitamin D",
    "vitamin d, 25-hydroxy": "Vitamin D",
    "prothrombin time": "PT",
    "international normalization ratio": "INR",
    "activated partial thromboplastin time": "aPTT",
    "carbon dioxide": "CO2",
    "blood urea nitrogen": "BUN",
    "anion gap": "Anion Gap",
    "total protein": "Total Protein",
    "ast (sgot)": "AST",
    "glucose": "Glucose",
    "calcium": "Calcium",
    "mean platelet volume": "MPV",
    "sodium": "Sodium",
    "potassium": "Potassium",
    "chloride": "Chloride",
    "co2": "CO2",
    "urea nitrogen (bun)": "BUN",
    "protein, total": "Total Protein",
    "protein total": "Total Protein",
    "globulin": "Globulin",
    "bilirubin, total": "Total Bilirubin",
    "bilirubin total": "Total Bilirubin",
    "aspartate aminotransferase": "AST",
    "alanine aminotransferase": "ALT",
    "glucose level": "Glucose",
    "calcium level total": "Calcium",
    "albumin level": "Albumin",
    "vitamin d,25-oh,total,ia": "Vitamin D",
    "non hdl cholesterol": "Non-HDL Cholesterol",
    "absolute neutrophils": "Neutrophils (abs)",
    "absolute neutrophil count": "Neutrophils (abs)",
    "absolute lymphocytes": "Lymphocytes (abs)",
    "absolute lymphocyte count": "Lymphocytes (abs)",
    "absolute monocytes": "Monocytes (abs)",
    "absolute monocyte count": "Monocytes (abs)",
    "absolute eosinophils": "Eosinophils (abs)",
    "absolute eosinophil count": "Eosinophils (abs)",
    "absolute basophils": "Basophils (abs)",
    "absolute basophil count": "Basophils (abs)",
    "white blood cell count": "WBC",
    "egfr": "eGFR",
    "gfr estimate": "eGFR",
    "bun/creatinine ratio serum": "BUN/Creatinine Ratio",
}


def _normalize_name(name):
    """Normalize test name to canonical form."""
    # Strip leading punctuation/flags like "!" and whitespace
    cleaned = re.sub(r"^[!\s*]+", "", name).strip()
    key = cleaned.lower().strip()
    return _NAME_MAP.get(key, cleaned)


def _extract_text(pdf_path):
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(str(pdf_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


# NHS → US unit conversions: (from_unit, to_unit, factor)
# Multiply the NHS value by `factor` to get the US value.
_UNIT_CONVERSIONS = {
    # Cholesterol: mmol/L → mg/dL (×38.67)
    ("Total Cholesterol", "mmol/L"): ("mg/dL", 38.67),
    ("HDL Cholesterol", "mmol/L"): ("mg/dL", 38.67),
    ("LDL Cholesterol", "mmol/L"): ("mg/dL", 38.67),
    # Triglycerides: mmol/L → mg/dL (×88.57)
    ("Triglycerides", "mmol/L"): ("mg/dL", 88.57),
    # Hemoglobin: g/L → g/dL (÷10)
    ("Hemoglobin", "g/L"): ("g/dL", 0.1),
    # Hematocrit: L/L → % (×100)
    ("Hematocrit", "L/L"): ("%", 100),
    # MCHC: g/L → g/dL (÷10)
    ("MCHC", "g/L"): ("g/dL", 0.1),
    # Albumin: g/L → g/dL (÷10)
    ("Albumin", "g/L"): ("g/dL", 0.1),
    # Bilirubin: umol/L → mg/dL (÷17.1)
    ("Total Bilirubin", "umol/L"): ("mg/dL", 1 / 17.1),
    # Creatinine: umol/L → mg/dL (÷88.4)
    ("Creatinine", "umol/L"): ("mg/dL", 1 / 88.4),
    # Ferritin: ug/L ≈ ng/mL (1:1)
    ("Ferritin", "ug/L"): ("ng/mL", 1.0),
    # RBC: 10*12/L → 10^6/uL (1:1, same thing different notation)
    ("RBC", "10*12/L"): ("10^6/uL", 1.0),
    # WBC/Platelets: 10*9/L → 10^3/uL (1:1, same thing)
    ("WBC", "10*9/L"): ("10^3/uL", 1.0),
    ("Platelets", "10*9/L"): ("10^3/uL", 1.0),
    ("Neutrophils", "10*9/L"): ("10^3/uL", 1.0),
    ("Lymphocytes", "10*9/L"): ("10^3/uL", 1.0),
    ("Monocytes", "10*9/L"): ("10^3/uL", 1.0),
    ("Eosinophils", "10*9/L"): ("10^3/uL", 1.0),
    ("Basophils", "10*9/L"): ("10^3/uL", 1.0),
    # HbA1c: mmol/mol → % DCCT (formula: % = mmol/mol / 10.929 + 2.15)
    # Handled specially below since it's not a simple multiply
    # TSH: mU/L ≈ uIU/mL (1:1)
    ("TSH", "mU/L"): ("uIU/mL", 1.0),
    # Free T4: pmol/L → ng/dL (÷12.87)
    ("Free T4", "pmol/L"): ("ng/dL", 1 / 12.87),
}


def _convert_to_us_units(name, value, unit, ref_low=None, ref_high=None):
    """Convert NHS/UK units to US equivalents for longitudinal consistency."""
    key = (name, unit)
    if key in _UNIT_CONVERSIONS:
        new_unit, factor = _UNIT_CONVERSIONS[key]
        value = round(value * factor, 2)
        if ref_low is not None:
            ref_low = round(ref_low * factor, 2)
        if ref_high is not None:
            ref_high = round(ref_high * factor, 2)
        unit = new_unit
    # HbA1c special case: IFCC mmol/mol → DCCT %
    elif name == "HbA1c" and unit == "mmol/mol":
        value = round(value / 10.929 + 2.15, 1)
        if ref_low is not None:
            ref_low = round(ref_low / 10.929 + 2.15, 1)
        if ref_high is not None:
            ref_high = round(ref_high / 10.929 + 2.15, 1)
        unit = "%"
    return value, unit, ref_low, ref_high


def _make_result(name, value, unit, ref_low=None, ref_high=None):
    """Build a result dict with unit conversion and flag computation."""
    normalized_name = _normalize_name(name)
    value, unit, ref_low, ref_high = _convert_to_us_units(
        normalized_name, value, unit, ref_low, ref_high
    )
    flag = "normal"
    if ref_low is not None and value < ref_low:
        flag = "low"
    elif ref_high is not None and value > ref_high:
        flag = "high"
    result = {
        "test": normalized_name,
        "value": value,
        "unit": unit,
        "flag": flag,
    }
    if ref_low is not None:
        result["ref_low"] = ref_low
    if ref_high is not None:
        result["ref_high"] = ref_high
    return result


# ---------------------------------------------------------------------------
# Format 1: NHS UK — single-line tabular results
# ---------------------------------------------------------------------------

def _parse_nhs_line(line):
    """Parse NHS-style line: 'Test Name  12.5  unit  low - high'"""
    patterns = [
        # Name  Value  Unit  Low-High
        r"^(.+?)\s+([\d.]+)\s+(\S+)\s+([\d.]+)\s*[-–]\s*([\d.]+)",
        # Name: Value Unit (Low - High)
        r"^(.+?):\s*([\d.]+)\s*(\S*)\s*\(([\d.]+)\s*[-–]\s*([\d.]+)\)",
        # Name  Value  Unit  Ref: Low-High
        r"^(.+?)\s+([\d.]+)\s+(\S+)\s+(?:Ref|Reference)?:?\s*([\d.]+)\s*[-–]\s*([\d.]+)",
    ]
    for pat in patterns:
        m = re.match(pat, line.strip())
        if m:
            name = m.group(1).strip()
            value = float(m.group(2))
            unit = m.group(3)
            low, high = float(m.group(4)), float(m.group(5))
            return _make_result(name, value, unit, low, high)
    return None


def _parse_nhs(text):
    """Parse NHS UK format — one result per line."""
    results = []
    for line in text.split("\n"):
        parsed = _parse_nhs_line(line)
        if parsed:
            results.append(parsed)
    return results


# ---------------------------------------------------------------------------
# Format 2: Quest Diagnostics — multi-line blocks
# ---------------------------------------------------------------------------

def _parse_quest(text):
    """Parse Quest Diagnostics format.

    Pattern (multi-line):
        TEST NAME
        Reference Range:
         LOW-HIGH  (or <VALUE or > OR = VALUE)
         unit
        result_value
    """
    results = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for "Reference Range:" marker
        if line.lower().startswith("reference range:") or line.lower() == "reference range:":
            # Walk backwards to find the test name (first non-empty, non-metadata line above)
            test_name = None
            j = i - 1
            while j >= 0:
                candidate = lines[j].strip()
                # Skip empty lines and lines that are just units or "No Historical Data"
                if candidate and not re.match(r"^(No Historical Data|Report Insights|Key|Priority Out of Range|Out of Range|\s)$", candidate, re.IGNORECASE):
                    test_name = candidate
                    break
                j -= 1

            if not test_name:
                i += 1
                continue

            # Collect lines until next "Reference Range:" or end of block
            block_lines = []
            k = i + 1
            while k < len(lines) and len(block_lines) < 80:
                stripped = lines[k].strip()
                if stripped:
                    # Stop if we hit the next test's Reference Range
                    if stripped.lower().startswith("reference range:") and len(block_lines) > 0:
                        break
                    block_lines.append(stripped)
                    # Stop after "No Historical Data" — marks end of Quest test block
                    if "no historical data" in stripped.lower():
                        break
                k += 1

            ref_low, ref_high, unit, value = None, None, None, None

            # Parse reference range and value from first few lines of block
            # (don't include chart data in the range/unit search)
            early_lines = block_lines[:6]
            block_text = " ".join(early_lines)

            # Range pattern: LOW-HIGH or LOW - HIGH
            range_match = re.search(r"([\d.]+)\s*[-–]\s*([\d.]+)", block_text)
            if range_match:
                ref_low = float(range_match.group(1))
                ref_high = float(range_match.group(2))

            # One-sided range: < VALUE or <VALUE or <= VALUE
            if ref_low is None:
                one_sided = re.search(r"<\s*(?:or\s*=\s*)?([\d.]+)", block_text, re.IGNORECASE)
                if one_sided:
                    ref_high = float(one_sided.group(1))
                    ref_low = None

            # One-sided range: > VALUE or >= VALUE or > OR = VALUE
            if ref_high is None and ref_low is None:
                one_sided = re.search(r">\s*(?:or\s*=\s*)?([\d.]+)", block_text, re.IGNORECASE)
                if one_sided:
                    ref_low = float(one_sided.group(1))
                    ref_high = None

            # Extract unit — look for common unit patterns
            unit_match = re.search(
                r"(mg/dL|g/dL|ng/dL|umol/L|mmol/L|mIU/mL|IU/L|U/L|pg/mL|ng/mL|"
                r"pmol/L|mU/L|ug/L|fL|pg|%|10\*\d+/L|10\^?\d+/[uU]L|"
                r"mL/min/1\.73m\^?2|seconds|ratio|/100 WBC'?s|cells/uL|"
                r"mg/dL \(calc\)|nmol/L|mcg/mL|µg/L|uIU/mL)",
                block_text, re.IGNORECASE
            )
            if unit_match:
                unit = unit_match.group(1)

            # Extract the result value.
            # Quest format structure:
            #   range_spec / unit / [explanatory text...] / VALUE /
            #   ref_low_repeated / ref_high_repeated /
            #   [From / chart data...] / No Historical Data
            #
            # Strategy: find all standalone numbers, then pick the one
            # that appears just before the last ref_low/ref_high pair.
            # This skips both explanatory text numbers (which appear
            # before the value) and chart ticks (which appear after).
            # The value and its repeated reference range always precede the
            # per-marker trend graph ("From <date> To <date>" + month labels +
            # axis ticks). Truncate the search there so we never pick up graph
            # ticks or bleed into the next marker — which happens when a
            # marker's "Reference range:" header is split across lines and the
            # block collector runs past it.
            trend_idx = len(block_lines)
            for idx_bl, bl in enumerate(block_lines):
                if bl.lower() == "from" or re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", bl):
                    trend_idx = idx_bl
                    break
            search_lines = block_lines[:trend_idx]

            number_entries = []  # (block_index, value, flag)
            for idx_bl, bl in enumerate(search_lines):
                val_match = re.match(r"^([\d.]+)\s*([HL]?)$", bl)
                if val_match:
                    number_entries.append((idx_bl, float(val_match.group(1)), val_match.group(2)))

            # Also find ref marker lines: "<130", "> OR = 60", "< or = 12.9"
            # These mark the repeated reference range for one-sided ranges
            ref_marker_indices = set()
            for idx_bl, bl in enumerate(search_lines):
                if re.match(r"^[<>]\s*(?:or\s*=\s*)?\s*[\d.]+", bl, re.IGNORECASE):
                    ref_marker_indices.add(idx_bl)

            # Find the last position where ref values appear as a pair
            # (the repeated reference range near end of block)
            last_ref_idx = -1
            for pos in range(len(number_entries) - 1):
                n1 = number_entries[pos][1]
                n2 = number_entries[pos + 1][1] if pos + 1 < len(number_entries) else None
                is_ref_1 = (n1 == ref_low or n1 == ref_high)
                is_ref_2 = (n2 == ref_low or n2 == ref_high) if n2 is not None else False
                if is_ref_1 and is_ref_2:
                    last_ref_idx = pos

            if last_ref_idx > 0:
                # Value is the number just before the last ref pair. Accept it
                # even when it coincides with a reference boundary (e.g. a value
                # of 50 against a 10-50 range) — its position before the
                # trailing ref pair is what identifies it as the value.
                value = number_entries[last_ref_idx - 1][1]
            else:
                # No ref pair found — for one-sided ranges, find the
                # number just before a ref marker line ("<130", "> OR = 60")
                # or a bare ref value repetition
                value_found = False

                # Check for ref marker lines (e.g. "<130" repeated)
                if ref_marker_indices:
                    last_marker = max(ref_marker_indices)
                    # Find the last number entry before this marker
                    for idx_bl, num, _ in reversed(number_entries):
                        if idx_bl < last_marker and num != ref_low and num != ref_high:
                            value = num
                            value_found = True
                            break

                # Check for bare ref value repetition
                if not value_found:
                    last_single_ref = -1
                    for pos, (idx_bl, num, _) in enumerate(number_entries):
                        if num == ref_low or num == ref_high:
                            last_single_ref = pos
                    if last_single_ref > 0:
                        candidate = number_entries[last_single_ref - 1]
                        if candidate[1] != ref_low and candidate[1] != ref_high:
                            value = candidate[1]
                            value_found = True

                # Fallback: first non-ref number after the unit
                if not value_found and number_entries:
                    unit_idx = -1
                    if unit:
                        for idx_bl, bl in enumerate(search_lines):
                            if unit.lower() in bl.lower():
                                unit_idx = idx_bl
                                break
                    for idx_bl, num, _ in number_entries:
                        if idx_bl <= unit_idx:
                            continue
                        if num != ref_low and num != ref_high:
                            value = num
                            break

            # Calculated ratios (CHOL/HDL, Albumin/Globulin) print "(calc)"
            # in place of a unit, so they'd otherwise be dropped below for
            # lack of one. Give them a "ratio" unit so the value is kept.
            if unit is None and value is not None and "ratio" in test_name.lower():
                unit = "ratio"

            if value is not None and unit:
                results.append(_make_result(test_name, value, unit, ref_low, ref_high))

            i = k
            continue

        i += 1

    # LDL-Cholesterol is rendered in an inverted callout layout
    # ("LDL-CHOLESTEROL\nmg/dL (calc)\n<value> H\nReference range:\n<100")
    # whose header is split across lines, so the Reference-Range-anchored loop
    # above neither detects it nor (for the marker before it) stops in time.
    # Pull it out directly if it wasn't already captured.
    if not any("ldl" in r["test"].lower() for r in results):
        m = re.search(
            r"LDL[- ]CHOLESTEROL\s*\n+\s*mg/dL\s*\(calc\)\s*\n+\s*([\d.]+)\s*([HL]?)",
            text, re.IGNORECASE,
        )
        if m:
            results.append(
                _make_result("LDL Cholesterol", float(m.group(1)), "mg/dL (calc)", None, 100.0)
            )

    return results


# ---------------------------------------------------------------------------
# Format 3: Epic MyChart — visual range bar format
# ---------------------------------------------------------------------------

def _number_display_variants(n):
    """Return possible display strings for a number (as printed on range bars)."""
    variants = []
    if n == int(n):
        variants.append(str(int(n)))
        if n != 0:
            variants.append(f"{n:.1f}")
    else:
        # Try various precisions
        s = f"{n:g}"
        variants.append(s)
        variants.append(f"{n:.1f}")
        variants.append(f"{n:.2f}")
    return list(dict.fromkeys(variants))  # deduplicate, preserve order


def _extract_value_from_bar(line, ref_low, ref_high):
    """Extract the result value from a MyChart range bar line.

    The bar line format is: "{low_display} {high_display}{value}" or
    "{low_display} {high_display}{value} High/Low" where numbers may be
    concatenated without spaces.

    Returns (value, flag_text) or None.
    """
    low_variants = _number_display_variants(ref_low)
    high_variants = _number_display_variants(ref_high)

    for low_s in low_variants:
        for high_s in high_variants:
            # Build pattern: low then high then value (possibly concatenated)
            # Value ends at a non-numeric character boundary
            pattern = re.escape(low_s) + r"\s*" + re.escape(high_s) + r"(\d+\.?\d*)\s*(High|Low|H|L)?(?=[^\d.]|$)"
            m = re.search(pattern, line)
            if m:
                value = float(m.group(1))
                flag_text = m.group(2)
                # Sanity check: value shouldn't be wildly out of range
                # (catches cases where date/URL digits leak into the value)
                range_span = ref_high - ref_low if ref_high > ref_low else ref_high
                if range_span > 0 and value > ref_high * 10:
                    continue
                return value, flag_text

    return None


def _parse_mychart(text):
    """Parse Epic MyChart format.

    Pattern:
        Test Name
        Normal range: LOW - HIGH unit
        LOW  HIGH  VALUE    (the visual range bar numbers)

    Or for qualitative ranges:
        Test Name
        Normal range: below <=VALUE unit  /  above >=VALUE unit
        Value
        ACTUAL_VALUE
    """
    # Strip URL timestamp artifacts that PyPDF2 concatenates with values
    # e.g. "14.201/02/24, 10:15 Connect - Test Details" → "14.2"
    # Pattern: date/time + URL that gets appended to the last value on a page
    text = re.sub(r"(\d)(\d{2}/\d{2}/\d{2},?\s*\d{2}:\d{2}\s*Connect\s*-\s*Test Details.*?)(?=\n|$)", r"\1", text)
    # Also strip standalone URL lines
    text = re.sub(r"https?://\S+", "", text)

    results = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for "Normal range:" marker
        normal_match = re.match(
            r"Normal range:\s*(.+)",
            line, re.IGNORECASE
        )
        if normal_match:
            range_text = normal_match.group(1)

            # Find the test name — look backwards for it
            test_name = None
            j = i - 1
            while j >= 0:
                candidate = lines[j].strip()
                if candidate and not re.match(
                    r"^(Results|Important Information|Ordering provider|Collection date|"
                    r"Specimens|Result date|Result status|Resulting lab|"
                    r"MyChart|Name:|DOB:|MRN:|PCP:|Legal Name:)",
                    candidate, re.IGNORECASE
                ):
                    # Skip lines that are just numbers, lab info, or URLs
                    if not re.match(r"^[\d.\s]+$", candidate) and len(candidate) > 2:
                        # Strip leading bar-line garbage: numbers/dots that precede the name
                        # e.g. "1.5 9.94.21Example Marker" → "Example Marker"
                        # e.g. "00D0000000 (CLIA #)Example Marker" → "Example Marker"
                        cleaned = re.sub(r"^[\d.\s]+(?=[A-Z])", "", candidate)
                        cleaned = re.sub(r"^.*?\(CLIA\s*#\)\s*", "", cleaned).strip()
                        # Skip if nothing meaningful remains
                        if cleaned and len(cleaned) > 2 and not re.match(r"^[\d.\s/]+$", cleaned):
                            test_name = cleaned
                            break
                j -= 1

            if not test_name:
                i += 1
                continue

            ref_low, ref_high, unit = None, None, None

            # Parse "LOW - HIGH unit"
            range_match = re.match(
                r"([\d.]+)\s*[-–]\s*([\d.]+)\s+(.*)",
                range_text
            )
            if range_match:
                ref_low = float(range_match.group(1))
                ref_high = float(range_match.group(2))
                unit = range_match.group(3).strip()

            # Parse "below <=VALUE unit" or "above >=VALUE unit"
            if ref_low is None and ref_high is None:
                below_match = re.match(r"below\s*<=?\s*([\d.]+)\s+(.*)", range_text, re.IGNORECASE)
                above_match = re.match(r"above\s*>=?\s*([\d.]+)\s+(.*)", range_text, re.IGNORECASE)
                if below_match:
                    ref_high = float(below_match.group(1))
                    unit = below_match.group(2).strip()
                elif above_match:
                    ref_low = float(above_match.group(1))
                    unit = above_match.group(2).strip()

            # Now find the value from subsequent lines.
            # MyChart uses two patterns:
            #   a) Range bar line: "{low_display}{high_display}{value}" (often concatenated)
            #      e.g. "1.5 9.94.21" = low=1.5, high=9.9, value=4.21
            #   b) "Value\n{number}" for one-sided ranges
            value = None
            flag_from_text = None
            k = i + 1
            attempts = 0
            while k < len(lines) and attempts < 8:
                next_line = lines[k].strip()
                if not next_line:
                    k += 1
                    attempts += 1
                    continue

                # Skip informational text lines (like aPTT clinical notes)
                # But still check them for bar-line data at the end
                if len(next_line) > 60 and not re.match(r"^[\d.\s]+", next_line):
                    # Check if the line ends with a bar pattern
                    if ref_low is not None and ref_high is not None:
                        extracted = _extract_value_from_bar(next_line, ref_low, ref_high)
                        if extracted is not None:
                            value, flag_from_text = extracted
                            break
                    k += 1
                    attempts += 1
                    continue

                # Stop if we hit the next test name or section
                if re.match(r"Normal range:", next_line, re.IGNORECASE):
                    break
                if re.match(r"^(Ordering provider|Collection date|Specimens|Result date|Result status|Resulting lab)", next_line, re.IGNORECASE):
                    break

                # Pattern b: "Value\n{number}" — value on its own line
                if next_line.lower() == "value":
                    k += 1
                    while k < len(lines):
                        val_line = lines[k].strip()
                        if val_line:
                            # Extract number, stopping before non-numeric suffixes like "01/02/24"
                            val_m = re.match(r"^[<>]?\s*(\d+\.?\d*)", val_line)
                            if val_m:
                                value = float(val_m.group(1))
                            break
                        k += 1
                    break

                # Pattern a: Range bar line with known ref values
                if ref_low is not None and ref_high is not None:
                    extracted = _extract_value_from_bar(next_line, ref_low, ref_high)
                    if extracted is not None:
                        value, flag_from_text = extracted
                        break

                attempts += 1
                k += 1

            if value is not None and unit:
                results.append(_make_result(test_name, value, unit, ref_low, ref_high))

            i = k + 1 if k > i else i + 1
            continue

        i += 1
    return results


# ---------------------------------------------------------------------------
# Date inference
# ---------------------------------------------------------------------------

def _infer_date(pdf_path, text=""):
    """Extract date from filename, folder structure, or PDF text content."""
    path = Path(pdf_path) if not isinstance(pdf_path, Path) else pdf_path
    full_path = str(path)

    # 1) Try filename patterns: "January 5 2024", "June 18, 2022", "2024-01-05"
    filename = path.stem  # without extension
    date_patterns = [
        (r"(\w+ \d{1,2},? \d{4})", ["%B %d, %Y", "%B %d %Y"]),
        (r"(\d{4}-\d{2}-\d{2})", ["%Y-%m-%d"]),
    ]
    for pat, fmts in date_patterns:
        m = re.search(pat, filename)
        if m:
            for fmt in fmts:
                try:
                    return datetime.strptime(m.group(1), fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue

    # 2) Try folder path: "2024/February 3/" or "2024/July 21/"
    #    Also handles "Month Day" in filename + year from parent folder
    parts = full_path.replace("\\", "/").split("/")
    year_from_folder = None
    month_day_from_folder = None

    for idx, part in enumerate(parts):
        if re.match(r"^\d{4}$", part):
            year_from_folder = part
        # Check if folder name is "Month Day" pattern
        md_match = re.match(r"^(\w+)\s+(\d{1,2})$", part)
        if md_match:
            month_day_from_folder = (md_match.group(1), md_match.group(2))

    # "Month Day" in filename without year + year from folder
    if year_from_folder:
        md_match = re.search(r"(\w+)\s+(\d{1,2})(?:\.\w+)?$", filename)
        if md_match:
            month_str, day_str = md_match.group(1), md_match.group(2)
            try:
                dt = datetime.strptime(f"{month_str} {day_str} {year_from_folder}", "%B %d %Y")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

        # Folder name is "Month Day" (e.g., "February 3")
        if month_day_from_folder:
            month_str, day_str = month_day_from_folder
            try:
                dt = datetime.strptime(f"{month_str} {day_str} {year_from_folder}", "%B %d %Y")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

    # 3) Try extracting from PDF text content
    text_date_patterns = [
        # "Collected on Feb 3, 2024 9:30 AM"
        (r"Collected\s+on\s+(\w+\s+\d{1,2},?\s+\d{4})", ["%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%B %d %Y"]),
        # "Collected: 01/05/2024" or "Collected:\n01/05/2024"
        (r"Collected:\s*\n?\s*(\d{2}/\d{2}/\d{4})", ["%m/%d/%Y"]),
        # "Collection date:Feb 3, 2024"
        (r"Collection date:\s*(\w+\s+\d{1,2},?\s+\d{4})", ["%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%B %d %Y"]),
    ]
    for pat, fmts in text_date_patterns:
        m = re.search(pat, text)
        if m:
            for fmt in fmts:
                try:
                    return datetime.strptime(m.group(1).strip(), fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue

    # 4) Year-only fallback from folder
    if year_from_folder:
        return year_from_folder

    return "unknown"


# ---------------------------------------------------------------------------
# Format detection + unified parser
# ---------------------------------------------------------------------------

def _detect_and_parse(text):
    """Run all format parsers and keep the one that extracts the most results."""
    return max(
        (_parse_nhs(text), _parse_quest(text), _parse_mychart(text)),
        key=len,
    )


def parse_blood_test_pdf(pdf_path):
    """Parse a single blood test PDF. Returns dict with date + results."""
    text = _extract_text(pdf_path)
    date = _infer_date(pdf_path, text)
    results = _detect_and_parse(text)

    return {
        "file": str(pdf_path),
        "date": date,
        "results": results,
        "raw_text_preview": text[:1000],
    }


def parse_all_blood_tests():
    """Scan the Blood Tests folder and parse all PDFs."""
    blood_dir = Path(HEALTH_FOLDER) / "Test Results" / "Blood Tests"
    if not blood_dir.exists():
        return []

    all_tests = []
    for pdf in sorted(blood_dir.rglob("*.pdf")):
        parsed = parse_blood_test_pdf(pdf)
        all_tests.append(parsed)

    # Save to JSON
    BLOOD_TESTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    BLOOD_TESTS_JSON.write_text(json.dumps(all_tests, indent=2, default=str))

    # Mirror the latest test date to Firestore so Cloud Run (which can't see
    # the local Drive mount) can still evaluate the 6-month reminder.
    _publish_latest_date(all_tests)

    return all_tests


def _publish_latest_date(all_tests):
    """Mirror parsed blood test data to Firestore. Never raises — local parse must not depend on it.

    Publishes the latest test date (for the 6-month reminder) plus the full
    longitudinal view and parsed results so Cloud Run, which can't see the
    local Drive mount, can render blood tests in the weekly report. Does
    nothing when there's no local data, so an empty Cloud Run parse never
    clobbers the good data already in Firestore.
    """
    try:
        if not all_tests:
            return
        latest = None
        for t in all_tests:
            raw = t.get("date")
            if not raw:
                continue
            try:
                d = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            if latest is None or d > latest:
                latest = d
        from firestore_client import set_latest_blood_test_date, set_blood_tests_data
        if latest is not None:
            set_latest_blood_test_date(latest)
        set_blood_tests_data(get_longitudinal_view(), all_tests)
    except Exception as e:
        print(f"[blood_tests] Could not publish blood test data to Firestore: {e}")


def get_longitudinal_view():
    """Load parsed blood tests and show how markers changed over time."""
    if not BLOOD_TESTS_JSON.exists():
        parse_all_blood_tests()

    if not BLOOD_TESTS_JSON.exists():
        return {}

    tests = json.loads(BLOOD_TESTS_JSON.read_text())

    # Group by test name across dates
    by_marker = {}
    for test_session in tests:
        date = test_session["date"]
        for result in test_session.get("results", []):
            name = result["test"]
            if name not in by_marker:
                by_marker[name] = []
            by_marker[name].append({
                "date": date,
                "value": result["value"],
                "unit": result["unit"],
                "flag": result["flag"],
            })

    # Sort each marker's history by date
    for name in by_marker:
        by_marker[name].sort(key=lambda x: x["date"])

    return by_marker


# ---------------------------------------------------------------------------
# Plain-language explanation + history comparison
# ---------------------------------------------------------------------------

def _render_system_section(lines, system, results, needs_attention, worth_watching):
    """Render one system group for explain_results."""
    lines.append(f"\n## {system}\n")
    lines.append("| Marker | Value | Lab Flag | Optimal | Explanation |")
    lines.append("|--------|-------|----------|---------|-------------|")

    for r in results:
        name = r["test"]
        value = r["value"]
        unit = r["unit"]
        lab_flag = r["flag"]
        info = get_marker_info(name)

        lab_icon = "✅" if lab_flag == "normal" else "⚠️"

        opt_flag = get_optimal_flag(name, value)
        if opt_flag == "optimal":
            opt_icon = "✅"
        elif opt_flag in ("above_optimal", "below_optimal"):
            opt_icon = "👀"
        else:
            opt_icon = "—"

        if info:
            if lab_flag == "high":
                explanation = info["high"]
                needs_attention.append((name, value, unit, lab_flag, explanation))
            elif lab_flag == "low":
                explanation = info["low"]
                needs_attention.append((name, value, unit, lab_flag, explanation))
            elif opt_flag in ("above_optimal", "below_optimal"):
                explanation = info["optimal_note"]
                worth_watching.append((name, value, unit, opt_flag, explanation))
            else:
                explanation = info["what"]
        else:
            explanation = ""
            if lab_flag != "normal":
                needs_attention.append((name, value, unit, lab_flag, ""))

        lines.append(
            f"| {name} | {value} {unit} | {lab_icon} {lab_flag} | {opt_icon} | {explanation} |"
        )


def explain_results(parsed):
    """Generate plain-language explanation of parsed blood test results.

    Args:
        parsed: output of parse_blood_test_pdf() — dict with 'date', 'results', 'file'

    Returns:
        Markdown string with grouped, explained results.
    """
    if not parsed.get("results"):
        return ""

    if not _HAS_LAB_REF:
        lines = [f"# Blood Test Results — {parsed['date']}\n"]
        for r in parsed["results"]:
            flag_icon = "✅" if r["flag"] == "normal" else "⚠️"
            lines.append(f"- {r['test']}: {r['value']} {r['unit']} {flag_icon} {r['flag']}")
        return "\n".join(lines)

    lines = [f"# Blood Test Results — {parsed['date']}\n"]

    results_by_system = {}
    for r in parsed["results"]:
        system = get_system_for_marker(r["test"])
        results_by_system.setdefault(system, []).append(r)

    needs_attention = []
    worth_watching = []

    system_order = list(SYSTEMS.keys())
    rendered_systems = set()

    for system in system_order:
        if system not in results_by_system:
            continue
        rendered_systems.add(system)
        _render_system_section(lines, system, results_by_system[system],
                               needs_attention, worth_watching)

    for system, results in results_by_system.items():
        if system not in rendered_systems:
            _render_system_section(lines, system, results,
                                   needs_attention, worth_watching)

    if needs_attention or worth_watching:
        lines.append("\n---")
        lines.append("\n## Summary\n")
        if needs_attention:
            lines.append("**Needs attention** (outside lab reference range):")
            for name, value, unit, flag, explanation in needs_attention:
                lines.append(f"- ⚠️ **{name}**: {value} {unit} ({flag}) — {explanation}")
        if worth_watching:
            lines.append("\n**Worth watching** (normal per lab, but outside optimal range):")
            for name, value, unit, opt_flag, note in worth_watching:
                label = "above optimal" if opt_flag == "above_optimal" else "below optimal"
                lines.append(f"- 👀 **{name}**: {value} {unit} ({label}) — {note}")
    else:
        lines.append("\n---")
        lines.append("\n✅ All markers are within optimal ranges.")

    return "\n".join(lines)


def compare_to_history(parsed, longitudinal=None):
    """Compare current results to historical data and highlight trends.

    Args:
        parsed: output of parse_blood_test_pdf()
        longitudinal: output of get_longitudinal_view(), or None to auto-load

    Returns:
        Markdown string with trend analysis per marker. Empty string if no prior data.
    """
    if not parsed.get("results"):
        return ""

    if longitudinal is None:
        longitudinal = get_longitudinal_view()

    if not longitudinal:
        return ""

    current_date = parsed["date"]
    changes = []

    for r in parsed["results"]:
        name = r["test"]
        value = r["value"]
        unit = r["unit"]
        lab_flag = r["flag"]

        history = longitudinal.get(name, [])
        prior = [h for h in history if h["date"] < current_date]
        if not prior:
            continue

        prev = prior[-1]
        prev_value = prev["value"]
        prev_flag = prev["flag"]
        prev_date = prev["date"]

        if prev_value == 0:
            pct_change = None
        else:
            pct_change = round((value - prev_value) / abs(prev_value) * 100, 1)

        flag_changed = lab_flag != prev_flag
        meaningful = flag_changed or (pct_change is not None and abs(pct_change) > 5)

        if not meaningful:
            continue

        if pct_change is not None:
            arrow = "↑" if pct_change > 0 else ("↓" if pct_change < 0 else "→")
        else:
            arrow = "—"

        changes.append({
            "name": name,
            "value": value,
            "unit": unit,
            "prev_value": prev_value,
            "prev_date": prev_date,
            "pct_change": pct_change,
            "arrow": arrow,
            "flag": lab_flag,
            "prev_flag": prev_flag,
            "flag_changed": flag_changed,
            "system": get_system_for_marker(name) if _HAS_LAB_REF else "Other",
        })

    if not changes:
        return ""

    lines = ["# Changes Since Last Test\n"]

    by_system = {}
    for c in changes:
        by_system.setdefault(c["system"], []).append(c)

    for system, items in by_system.items():
        lines.append(f"\n## {system}\n")
        lines.append("| Marker | Previous | Current | Change | Flag |")
        lines.append("|--------|----------|---------|--------|------|")

        for c in items:
            pct_str = f"{c['arrow']} {abs(c['pct_change'])}%" if c['pct_change'] is not None else "—"
            flag_str = f"{c['prev_flag']} → {c['flag']}" if c['flag_changed'] else c['flag']
            flag_icon = "🔄" if c['flag_changed'] else ("⚠️" if c['flag'] != "normal" else "")
            lines.append(
                f"| {c['name']} | {c['prev_value']} {c['unit']} ({c['prev_date']}) "
                f"| {c['value']} {c['unit']} | {pct_str} | {flag_icon} {flag_str} |"
            )

    flag_changes = [c for c in changes if c["flag_changed"]]
    if flag_changes:
        lines.append("\n### Flag Changes\n")
        for c in flag_changes:
            if c["flag"] == "normal" and c["prev_flag"] != "normal":
                lines.append(f"- ✅ **{c['name']}** returned to normal (was {c['prev_flag']})")
            else:
                lines.append(f"- ⚠️ **{c['name']}** changed from {c['prev_flag']} to {c['flag']}")

    return "\n".join(lines)
