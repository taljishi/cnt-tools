# Vendor-specific parsers for Invoice Run (enhanced, line-wise heuristics)
from __future__ import annotations

import re
from typing import Callable, Dict, Optional, List, Tuple

try:
    import dateparser  # type: ignore
except Exception:
    dateparser = None

__all__ = [
    "get_vendor_parser",
    "parse_beyon_text",
    "parse_ewa_text",
]

# -----------------------------
# Small helpers
# -----------------------------
_NUM_TOKEN = r"[A-Z0-9][A-Z0-9,.\-/]*"
_AMT = r"[0-9]+(?:[0-9,]{0,12})?(?:\.\d{1,3})?"
_DATE = r"[0-3]?\d[\s/\-](?:[A-Za-z]{3,}|0?\d)[\s/\-]\d{2,4}"

def _norm_amount(s) -> Optional[float]:
    if s is None:
        return None
    t = str(s)
    t = t.replace("\u00A0", " ").strip()
    t = t.replace(",", "")
    m = re.search(r"([0-9]+(?:\.[0-9]{1,3})?)", t)
    try:
        return float(m.group(1)) if m else None
    except Exception:
        return None

def _norm_date(s) -> Optional[str]:
    if not s:
        return None
    if isinstance(s, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    if dateparser:
        try:
            dt = dateparser.parse(str(s))
            return dt.date().isoformat() if dt else None
        except Exception:
            return None
    return None

def _lines(text: str) -> List[str]:
    # Normalize whitespace; keep simple newlines
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]

def _search_across(lines: List[str], pattern: str, flags=re.I) -> Optional[re.Match]:
    rx = re.compile(pattern, flags)
    for ln in lines:
        m = rx.search(ln)
        if m:
            return m
    return None

def _first_after(lines: List[str], labels: List[str], token_rx: str, look_ahead: int = 2) -> Optional[str]:
    """
    Try multiple label patterns; return the first token matched on the same or next lines.
    (Safer: only uses _find_after; avoids composing mixed regex strings.)
    """
    for lab in labels:
        try:
            val = _find_after(lines, lab, token_rx, look_ahead=look_ahead)
        except re.error:
            # skip malformed patterns
            continue
        if val:
            return val
    return None

def _find_after(lines: List[str], label_rx: str, token_rx: str, look_ahead: int = 2) -> Optional[str]:
    """Find token after a label on same or next lines."""
    lab = re.compile(label_rx, re.I)
    tok = re.compile(token_rx, re.I)
    for i, ln in enumerate(lines):
        if lab.search(ln):
            # same line
            m = tok.search(ln)
            if m:
                return m.group(1)
            # next few lines
            for j in range(1, look_ahead + 1):
                if i + j < len(lines):
                    m2 = tok.search(lines[i + j])
                    if m2:
                        return m2.group(1)
    return None

# -----------------------------
# Beyon / Batelco
# -----------------------------
def parse_beyon_text(full_text: str) -> Dict[str, object]:
    """
    Parse Beyon/Batelco bills from OCR'd text.
    Returns dict with: bill_no, bill_date, due_date, amount, bill_profile, vat_amount (optional).
    """
    out: Dict[str, object] = {}
    lines = _lines(full_text)

    # Bill Profile (tolerant to OCR breaks; multiple label fallbacks)
    val = _first_after(
        lines,
        [r"bill\W*pro\W*file", r"bill\s*profile\s*(?:no\.?|number)?", r"profile\s*(?:id|no\.?|number)?"],
        fr"({_NUM_TOKEN})",
        look_ahead=2,
    )
    if val:
        out["bill_profile"] = val

    # Bill No / Invoice No / Reference No
    val = _first_after(
        lines,
        [r"B[i1]ll?\s*No\.?", r"Invoice\s*(?:No\.?|Number)", r"Reference\s*(?:No\.?|Number)"],
        fr"({_NUM_TOKEN})",
        look_ahead=2,
    )
    if val:
        out["bill_no"] = val

    # Bill Date variants
    val = _first_after(
        lines,
        [r"Bill\s*Issue\s*Date", r"Bill\s*Date", r"Invoice\s*Date"],
        fr"({_DATE})",
        look_ahead=2,
    )
    if val:
        norm = _norm_date(val)
        if norm:
            out["bill_date"] = norm

    # Due Date variants
    val = _first_after(
        lines,
        [r"Due\s*Date", r"Payment\s*Due\s*Date", r"Due\s*by"],
        fr"({_DATE})",
        look_ahead=2,
    )
    if val:
        norm = _norm_date(val)
        if norm:
            out["due_date"] = norm

    # Amount payable variants; accept currency before/after
    val = _first_after(
        lines,
        [
            r"Total\s*Due(?:\s*\((?:BD|BHD)\)|\s+(?:BD|BHD))?",
            r"Total\s*Amount\s*Due",
            r"Amount\s*Payable",
            r"Total\s*Payable",
            r"Total\s*Amount\s*Payable",
        ],
        fr"(?:(?:BD|BHD)\s*)?({_AMT})",
        look_ahead=1,
    )
    if val is not None:
        amt = _norm_amount(val)
        if amt is not None:
            out['amount'] = amt

    # VAT on Current Charges (optional)
    val = _first_after(
        lines,
        [r"VAT\s*on\s*Current\s*Charges", r"VAT\s*(?:Amount|Total)?"],
        fr"({_AMT})",
        look_ahead=1,
    )
    if val is not None:
        vat = _norm_amount(val)
        if vat is not None:
            out["vat_amount"] = vat

    return out

# -----------------------------
# EWA (Electricity & Water Authority)
# -----------------------------
def parse_ewa_text(full_text: str) -> Dict[str, object]:
    """
    First-cut EWA parser. Adjust with a sample bill as needed.
    Returns: account_no (item key), bill_no, bill_date, due_date, amount, vat_amount (optional).
    """
    out: Dict[str, object] = {}
    lines = _lines(full_text)

    # Account number
    val = _find_after(lines, r"(?:Account|A/c)\s*(?:No\.?|Number)?", fr"({_NUM_TOKEN})")
    if not val:
        m = _search_across(lines, rf"\b(?:Account|A/c)\s*(?:No\.?|Number)?\b\W*({_NUM_TOKEN})")
        if m:
            val = m.group(1)
    if val:
        out["account_no"] = val

    # Bill No
    val = _find_after(lines, r"Bill\s*No\.?", fr"({_NUM_TOKEN})")
    if not val:
        m = _search_across(lines, rf"\bBill\s*No\.?\b\W*({_NUM_TOKEN})")
        if m:
            val = m.group(1)
    if val:
        out["bill_no"] = val

    # Dates
    val = _find_after(lines, r"Bill\s*Date", fr"({_DATE})")
    if not val:
        m = _search_across(lines, rf"\bBill\s*Date\b\W*({_DATE})")
        if m:
            val = m.group(1)
    if val:
        norm = _norm_date(val)
        if norm:
            out["bill_date"] = norm

    val = _find_after(lines, r"Due\s*Date", fr"({_DATE})")
    if not val:
        m = _search_across(lines, rf"\bDue\s*Date\b\W*({_DATE})")
        if m:
            val = m.group(1)
    if val:
        norm = _norm_date(val)
        if norm:
            out["due_date"] = norm

    # Amount
    val = _find_after(lines, r"(?:Total\s*Due|Amount\s*Payable)", fr"({_AMT})")
    if not val:
        m = _search_across(lines, rf"\b(?:Total\s*Due|Amount\s*Payable)\b\W*({_AMT})")
        if m:
            val = m.group(1)
    if val is not None:
        amt = _norm_amount(val)
        if amt is not None:
            out["amount"] = amt

    # VAT total (optional)
    val = _find_after(lines, r"(?:VAT|Tax)\s*(?:Amount|Total)?", fr"({_AMT})")
    if not val:
        m = _search_across(lines, rf"\b(?:VAT|Tax)\s*(?:Amount|Total)?\b\W*({_AMT})")
        if m:
            val = m.group(1)
    if val is not None:
        vat = _norm_amount(val)
        if vat is not None:
            out["vat_amount"] = vat

    return out

# -----------------------------
# Registry / Resolver
# -----------------------------
def _resolve_vendor_key(supplier_hint: str, full_text: str) -> Optional[str]:
    s = (supplier_hint or "").strip().lower()
    t = (full_text or "").lower()

    # Beyon / Batelco
    if any(k in s for k in ("beyon", "batelco", "s0032")) or re.search(r"\bbeyon\b|\bbatelco\b", t, re.I):
        return "beyon"

    # EWA
    if any(k in s for k in ("ewa", "electricity", "water")) or re.search(r"\bewa\b|\belectricity\b", t, re.I):
        return "ewa"

    return None

def get_vendor_parser(supplier_hint: str, full_text: str) -> Optional[Callable[[str], Dict[str, object]]]:
    """
    Returns a callable parser(text)->dict for known vendors or None.
    """
    key = _resolve_vendor_key(supplier_hint, full_text)
    if key == "beyon":
        return parse_beyon_text
    if key == "ewa":
        return parse_ewa_text
    return None
