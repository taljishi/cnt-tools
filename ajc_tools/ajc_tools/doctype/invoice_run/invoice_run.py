# Copyright (c) 2025, Cloud Nine Technologies (CNT) and contributors
# For license information, please see license.txt

from __future__ import annotations

import hashlib
import io
import json
import re
import os
import subprocess
import tempfile
import shutil
from typing import Dict, List, Optional, Tuple

import frappe
from frappe.model.document import Document
from frappe.utils import now, today, add_days, format_date

# Optional deps (text-first; OCR not included in v1)
try:
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover
    pdfplumber = None
try:
    import dateparser  # type: ignore
except Exception:  # pragma: no cover
    dateparser = None

# -----------------------------
# Parent DocType: Invoice Run
# -----------------------------
class InvoiceRun(Document):
    """Parent document controlling the Purchase Invoice PDF import flow."""
    pass


# -----------------------------
# Helpers
# -----------------------------
def _get_file_doc_by_url(file_url: str):
    if not file_url:
        return None
    return frappe.get_all(
        "File",
        filters={"file_url": file_url},
        fields=["name"],
        limit_page_length=1,
    )

def _sha1_file(file_url: str) -> str:
    """Compute SHA1 for attached File content."""
    recs = _get_file_doc_by_url(file_url)
    if not recs:
        return ""
    file_doc = frappe.get_doc("File", recs[0].name)
    content = file_doc.get_content()  # bytes
    return hashlib.sha1(content).hexdigest()

def _read_file_bytes(file_url: str) -> bytes:
    recs = _get_file_doc_by_url(file_url)
    if not recs:
        return b""
    file_doc = frappe.get_doc("File", recs[0].name)
    return file_doc.get_content() or b""


def _ocr_pdf_bytes(pdf_bytes: bytes) -> Tuple[bytes, str]:
    """
    Try OCR with ocrmypdf (Python API first, then CLI).
    Returns (ocr_bytes, info_message). info_message is a short string you can log (may be empty).
    If OCR is unavailable or fails, returns (original_bytes, reason).
    """
    # Try Python API
    try:
        import ocrmypdf  # type: ignore
        with tempfile.TemporaryDirectory() as td:
            in_path = os.path.join(td, "in.pdf")
            out_path = os.path.join(td, "out.pdf")
            with open(in_path, "wb") as f:
                f.write(pdf_bytes)
            try:
                # Use API to avoid PATH issues
                ocrmypdf.ocr(in_path, out_path, force_ocr=True, progress_bar=False)
                with open(out_path, "rb") as f:
                    return f.read(), "OCR via Python API succeeded."
            except Exception as e:
                # fall through to CLI
                api_err = str(e)[:200]
        # If import worked but API failed, note it in info later
        api_note = f" (API error: {api_err})" if 'api_err' in locals() else ""
    except Exception as e:
        api_note = f" (API unavailable: {str(e)[:100]})"

    # Try CLI
    try:
        ocrmypdf_path = shutil.which("ocrmypdf")
        if not ocrmypdf_path:
            return pdf_bytes, f"OCR CLI unavailable{api_note}."

        with tempfile.TemporaryDirectory() as td:
            in_path = os.path.join(td, "in.pdf")
            out_path = os.path.join(td, "out.pdf")
            with open(in_path, "wb") as f:
                f.write(pdf_bytes)

            cmd = [ocrmypdf_path, "--force-ocr", "--quiet", in_path, out_path]
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode != 0:
                stderr = (res.stderr or b"").decode("utf-8", errors="ignore")[:200]
                return pdf_bytes, f"OCR CLI failed rc={res.returncode}{api_note}. Stderr: {stderr}"

            with open(out_path, "rb") as f:
                return f.read(), f"OCR via CLI succeeded (path={ocrmypdf_path})."
    except Exception as e:
        return pdf_bytes, f"OCR CLI exception{api_note}: {str(e)[:200]}"

    # Fallback: nothing worked
    return pdf_bytes, f"OCR not performed{api_note}."


# PDF extraction helpers
def _try_all_extractors(pdf_bytes: bytes) -> Tuple[str, List[str]]:
    # 1) pdfplumber
    if pdfplumber:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages = []
                for p in pdf.pages:
                    txt = p.extract_text() or ""
                    pages.append(txt)
                full = "\n".join(pages)
                if full.strip():
                    return full, pages
        except Exception:
            pass  # try next extractor

    # 2) pypdf (PyPDF2)
    try:
        try:
            from pypdf import PdfReader  # modern package name
        except Exception:
            from PyPDF2 import PdfReader  # fallback old name
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for pg in getattr(reader, "pages", []):
            try:
                txt = pg.extract_text() or ""
            except Exception:
                txt = ""
            pages.append(txt)
        full = "\n".join(pages)
        if full.strip():
            return full, pages
    except Exception:
        pass

    # 3) pdfminer.six
    try:
        from pdfminer.high_level import extract_text  # type: ignore
        text = extract_text(io.BytesIO(pdf_bytes)) or ""
        if text.strip():
            return text, [text]
    except Exception:
        pass

    # 4) raw decode
    try:
        text = pdf_bytes.decode("utf-8", errors="ignore")
        return text, [text]
    except Exception:
        return "", []

def _extract_pdf_text(file_url: str) -> Tuple[str, List[str]]:
    """
    Return (full_text, pages_text). Tries multiple extractors and, if text looks non-textual,
    attempts OCR via 'ocrmypdf' and retries extraction once.
    """
    content = _read_file_bytes(file_url)
    if not content:
        return "", []

    full, pages = _try_all_extractors(content)
    head = (full[:8] or "")
    looks_binary = head.startswith("%PDF") or head.startswith("\x00\x01")
    if (not full.strip()) or looks_binary:
        # Attempt OCR and retry extraction
        ocr_bytes, _ = _ocr_pdf_bytes(content)
        if ocr_bytes != content:
            full2, pages2 = _try_all_extractors(ocr_bytes)
            if full2.strip():
                return full2, pages2
    return full, pages

def _append_log(doc, line: str):
    doc.import_log = (doc.import_log or "") + f"\n[{now()}] {line}"

def _soft_duplicate_check(parsed: dict, rule: str) -> bool:
    supplier = parsed.get("supplier")
    bill_no = parsed.get("bill_no")
    bill_date = parsed.get("bill_date")

    if rule == "File Fingerprint (SHA1)":
        return False

    if not supplier or not bill_no:
        return False

    filters = {"supplier": supplier, "bill_no": bill_no}
    if rule == "Supplier + Bill No + Bill Date" and bill_date:
        filters["bill_date"] = bill_date
    return bool(frappe.db.exists("Purchase Invoice", filters))

def _exists_duplicate(supplier, bill_no, bill_date, sha1, rule) -> bool:
    if rule == "File Fingerprint (SHA1)":
        # Implement if you maintain a global SHA1 map.
        return False

    if not supplier or not bill_no:
        return False

    filters = {"supplier": supplier, "bill_no": bill_no}
    if rule == "Supplier + Bill No + Bill Date" and bill_date:
        filters["bill_date"] = bill_date
    return bool(frappe.db.exists("Purchase Invoice", filters))

def _attach_to_doc(file_url, doctype, name):
    if not file_url:
        return
    recs = _get_file_doc_by_url(file_url)
    if not recs:
        return
    src = frappe.get_doc("File", recs[0].name)
    if src.attached_to_doctype == doctype and src.attached_to_name == name:
        return
    dst = frappe.copy_doc(src)
    dst.attached_to_doctype = doctype
    dst.attached_to_name = name
    dst.save(ignore_permissions=True)

# -----------------------------
# Mapping selection & rule runner
# -----------------------------
def _select_mapping(supplier_hint: Optional[str], full_text: str):
    from ajc_tools.ajc_tools.doctype.invoice_mapping.invoice_mapping import select_invoice_mapping
    return select_invoice_mapping(supplier_hint=supplier_hint, full_text=full_text)

def _apply_rules_to_text(rules: List[Dict], full_text: str, pages: List[str]) -> Tuple[Dict, List[str], List[str]]:
    """
    Apply exported rules to text and return:
      (result_dict, hit_labels, errors)
    Supports:
      - pattern (regex string)
      - flags (re flags)
      - group_index (int)
      - page_scope: None/'all'/'1'/'last'
      - postprocess: None/'strip'/'date'/'amount'
      - required: 0/1
    """
    result: Dict[str, object] = {}
    hits: List[str] = []
    errs: List[str] = []

    def _choose_text(scope: Optional[str]) -> List[Tuple[int, str]]:
        if not scope or scope == "all":
            # enumerate pages for consistent behavior
            return list(enumerate(pages if pages else [full_text]))
        if scope == "last" and pages:
            return [(len(pages) - 1, pages[-1])]
        try:
            idx = int(scope) - 1
            if 0 <= idx < len(pages):
                return [(idx, pages[idx])]
        except Exception:
            pass
        # fallback
        return list(enumerate(pages if pages else [full_text]))

    for r in rules:
        field = r.get("field")
        pattern = r.get("pattern") or ""
        if not field or not pattern:
            continue
        method = (r.get("method") or "Regex")
        label = (r.get("label") or "")
        flags = r.get("flags") or re.I
        grp = int(r.get("group_index") or 1)
        scope = r.get("page_scope") or "all"
        post = (r.get("postprocess") or "").strip().lower()
        required = int(r.get("required") or 0)

        rx = re.compile(pattern, flags)
        value = None

        for _page_index, text in _choose_text(scope):
            m = rx.search(text or "")
            if not m:
                continue
            try:
                value = m.group(grp)
            except Exception:
                value = None
            if value is not None:
                break

        if value is None:
            short_pat = (pattern[:60] + '…') if len(pattern) > 60 else pattern
            errs.append(f"no_match:{field}:{method}:{(label or '').strip()}::{short_pat}")
            if required:
                errs.append(f"Missing required field: {field}")
            continue

        # postprocess
        if post == "strip":
            value = (value or "").strip()
        elif post == "amount":
            try:
                value = float(str(value).replace(",", "").strip())
            except Exception:
                errs.append(f"Cannot parse amount for field: {field}")
        elif post == "date":
            if dateparser:
                try:
                    dt = dateparser.parse(str(value))
                    value = dt.date().isoformat() if dt else value
                except Exception:
                    errs.append(f"Cannot parse date for field: {field}")
            else:
                # leave as-is if dateparser not installed
                value = value

        result[str(field)] = value
        sample_val = (str(value)[:40] + '…') if value is not None and len(str(value)) > 40 else str(value)
        hits.append(f"hit:{field}:{sample_val}")

    return result, hits, errs

def _supplier_key(supplier: Optional[str]) -> str:
    s = (supplier or "").strip().lower()
    return s

def _choose_item_code_for_supplier(supplier: Optional[str], parsed: Dict[str, object]) -> Optional[str]:
    """
    Supplier-specific item resolution:
      - Batelco/Beyon: prefer bill_profile, then account_no
      - EWA: prefer account_no, then bill_profile
      - Else: None (fallback item handled by PI creation)
    """
    key = _supplier_key(supplier)
    bill_profile = (parsed.get("bill_profile") or parsed.get("Bill Profile") or parsed.get("bill_profile")) if isinstance(parsed, dict) else None
    account_no = (parsed.get("account_no") or parsed.get("Account Number") or parsed.get("account_no")) if isinstance(parsed, dict) else None

    if "batelco" in key or "beyon" in key:
        return (bill_profile or account_no) or None
    if "ewa" in key or "electricity" in key:
        return (account_no or bill_profile) or None
    return None

# -----------------------------
# Whitelisted Methods
# -----------------------------
@frappe.whitelist()
def parse_files(name: str):
    """Parse all child files via Invoice Mapping; fill parsed fields, statuses, counters, and parent status."""
    doc = frappe.get_doc("Invoice Run", name)

    totals = dict(files=0, parsed=0, ready=0, failed=0)
    for row in (doc.source_files or []):
        # Skip rows already parsed unless user reset to Draft
        if row.status == "Parsed":
            continue

        totals["files"] += 1

        try:
            if not row.file:
                row.status = "Error"
                row.last_error = "No file attached."
                totals["failed"] += 1
                continue

            # Fingerprint file
            row.sha1 = _sha1_file(row.file)

            # Extract PDF text
            full_text, pages = _extract_pdf_text(row.file)
            head = (full_text[:8] or "")
            looks_binary = head.startswith("%PDF") or head.startswith("\x00\x01")
            _append_log(doc, f"PDF text length={len(full_text)} (first 120): {full_text[:120].replace(chr(10),' ')}")
            if looks_binary or not full_text.strip():
                _append_log(doc, "Warning: Extracted text looks non-textual. Attempting OCR via ocrmypdf…")
                try:
                    orig_bytes = _read_file_bytes(row.file)
                    ocr_bytes, ocr_info = _ocr_pdf_bytes(orig_bytes)
                    if ocr_info:
                        _append_log(doc, ocr_info)
                    if ocr_bytes != orig_bytes:
                        full_text, pages = _try_all_extractors(ocr_bytes)
                        _append_log(doc, f"OCR text length={len(full_text)} (first 120): {full_text[:120].replace(chr(10),' ')}")
                    else:
                        _append_log(doc, "OCR unavailable or failed; continuing with original bytes.")
                except Exception as _ocr_e:
                    _append_log(doc, f"OCR attempt failed: {_ocr_e}")
            if not full_text.strip():
                row.status = 'Error'
                row.last_error = 'Could not read text from PDF (no text after extract/OCR).'
                totals['failed'] += 1
                continue

            # Select mapping (supplier on row or parent is a strong hint)
            supplier_hint = row.supplier or doc.supplier
            mapping = _select_mapping(supplier_hint=supplier_hint, full_text=full_text)
            if not mapping:
                row.status = "Error"
                row.last_error = "No active Invoice Mapping matched this PDF."
                _append_log(doc, "No mapping matched this PDF (check supplier hint & keywords).")
                totals["failed"] += 1
                continue

            _append_log(doc, f"Using mapping: {mapping.name} (supplier={getattr(mapping, 'supplier', '')}, priority={getattr(mapping, 'priority', '')})")
            try:
                rules = mapping.rules_for_engine()
                _append_log(doc, "Rules: " + ", ".join([f"{r.get('field')}[{r.get('method') or 'Regex'}:{(r.get('label') or '').strip()}]" for r in rules]))
            except Exception as e:
                _append_log(doc, f"Rules export failed: {e}")
                raise

            # Run rules
            result, hits, errs = _apply_rules_to_text(rules, full_text, pages)
            if hits:
                _append_log(doc, "Hits: " + ", ".join(hits))
            if errs:
                _append_log(doc, "No-matches: " + ", ".join([e for e in errs if e.startswith("no_match:")]))

            # If any required fields are missing, fail the row
            required_missing = [e for e in errs if e.startswith("Missing required field:")]
            if required_missing:
                row.status = "Error"
                row.last_error = "; ".join(required_missing)
                _append_log(doc, "Missing: " + "; ".join(required_missing))
                totals["failed"] += 1
                continue

            # Normalize + assign core fields
            supplier_val = row.supplier or doc.supplier or getattr(mapping, "supplier", None)
            row.supplier = supplier_val

            row.bill_no = result.get("bill_no") or row.bill_no or f"AUTO-{(row.sha1 or '')[:8]}"

            # Dates
            def _to_date(val):
                if not val:
                    return None
                if isinstance(val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                    return val
                if dateparser:
                    dt = dateparser.parse(str(val))
                    return dt.date().isoformat() if dt else None
                return None

            row.bill_date = _to_date(result.get("bill_date")) or row.bill_date or today()
            row.due_date = _to_date(result.get("due_date")) or row.due_date or add_days(row.bill_date or today(), 30)

            # Amounts / currency
            try:
                row.amount = float(result.get("amount")) if result.get("amount") is not None else (row.amount or 0.0)
            except Exception:
                row.amount = row.amount or 0.0

            # Optional fields from mapping (vat_amount, bill_profile, account_no)
            if "vat_amount" in result:
                try:
                    row.vat_amount = float(result.get("vat_amount")) if result.get("vat_amount") is not None else None
                except Exception:
                    pass
            if "bill_profile" in result:
                row.bill_profile = result.get("bill_profile")
            if "account_no" in result:
                row.account_no = result.get("account_no")

            row.currency = row.currency or frappe.db.get_single_value("Global Defaults", "default_currency") or "BHD"

            # Confidence: crude weighting by hits count
            total_required = sum(1 for r in rules if int(r.get("required") or 0) == 1)
            base = 0.6
            bump = 0.1 * min(len(hits), max(total_required, 1))
            conf = min(0.95, base + bump)

            # Duplicate cue
            rule_name = doc.duplicate_check_by or "Supplier + Bill No + Bill Date"
            parsed_for_flag = {
                "supplier": row.supplier,
                "bill_no": row.bill_no,
                "bill_date": row.bill_date,
            }
            possible_dup = _soft_duplicate_check(parsed_for_flag, rule_name)

            # Store parsed_json
            parsed_json = {
                "mapping": mapping.name,
                "result": result,
                "hits": hits,
                "file_url": row.file,
                "possible_duplicate": possible_dup,
            }
            row.parsed_json = json.dumps(parsed_json, ensure_ascii=False)

            row.confidence = int(conf * 100)
            row.status = "Parsed"

            totals["parsed"] += 1
            totals["ready"] += 1

        except Exception:
            _append_log(doc, "Exception: " + frappe.get_traceback().splitlines()[-1])
            row.status = "Error"
            row.last_error = frappe.get_traceback()
            totals["failed"] += 1

    # Update parent counters
    doc.files_count = totals["files"]
    doc.parsed_count = totals["parsed"]
    doc.ready_count = totals["ready"]
    doc.failed_count = totals["failed"]

    # Parent status
    if totals["ready"] > 0:
        doc.status = "Parsed"
    elif totals["files"] > 0 and totals["failed"] == totals["files"]:
        doc.status = "Failed"
    else:
        doc.status = "Draft"

    _append_log(doc, f"Parse complete: {totals}")
    _append_log(doc, f"Totals: files={totals['files']}, parsed={totals['parsed']}, ready={totals['ready']}, failed={totals['failed']}")
    doc.save(ignore_permissions=True)
    return {"ok": True, "totals": totals}

@frappe.whitelist()
def get_preview_html(name: str) -> str:
    """Return HTML preview for Parsed rows (displayed in a Dialog on the client)."""
    doc = frappe.get_doc("Invoice Run", name)

    rows = []
    for r in (doc.source_files or []):
        if r.status != "Parsed":
            continue
        parsed = {}
        try:
            parsed = json.loads(r.parsed_json or "{}")
        except Exception:
            parsed = {}
        rows.append({
            "supplier": r.supplier or doc.supplier,
            "bill_no": r.bill_no,
            "bill_date": r.bill_date,
            "due_date": r.due_date,
            "amount": r.amount,
            "currency": r.currency,
            "confidence": r.confidence,
            "possible_duplicate": (parsed or {}).get("possible_duplicate", False),
            "file": r.file,
        })

    if not rows:
        return '<div class="text-muted p-4">' + frappe._("Nothing ready to import.") + '</div>'

    def esc(x):
        return frappe.utils.escape_html(x if x is not None else "")

    header = f"""
    <div class="mb-2 text-muted">{frappe._('Review the parsed invoices before creation.')}</div>
    <div class="table-responsive">
    <table class="table table-bordered table-compact">
      <thead>
        <tr>
          <th>{frappe._('Supplier')}</th>
          <th>{frappe._('Bill No')}</th>
          <th>{frappe._('Bill Date')}</th>
          <th>{frappe._('Due Date')}</th>
          <th>{frappe._('Amount')}</th>
          <th>{frappe._('Currency')}</th>
          <th>{frappe._('Confidence')}</th>
          <th>{frappe._('Duplicate?')}</th>
          <th>{frappe._('File')}</th>
        </tr>
      </thead>
      <tbody>
    """

    body = ""
    for r in rows:
        body += f"""
          <tr>
            <td>{esc(r['supplier'])}</td>
            <td>{esc(r['bill_no'])}</td>
            <td>{esc(format_date(r['bill_date']))}</td>
            <td>{esc(format_date(r['due_date']))}</td>
            <td class="text-right">{esc(frappe.format(r['amount'], {'fieldtype':'Currency'}))}</td>
            <td>{esc(r['currency'])}</td>
            <td>{esc(str(r['confidence']) + '%')}</td>
            <td>{'&#9888;&#65039;' if r['possible_duplicate'] else ''}</td>
            <td>{('<a href="'+esc(r['file'])+'" target="_blank">PDF</a>') if r['file'] else ''}</td>
          </tr>
        """

    footer = "</tbody></table></div>"
    return header + body + footer

@frappe.whitelist()
def create_purchase_invoices(name: str):
    """Create Purchase Invoices from Parsed rows; enforce duplicate rules; update counters/logs."""
    doc = frappe.get_doc("Invoice Run", name)

    created = skipped = failed = 0
    messages = []

    for row in (doc.source_files or []):
        if row.status != "Parsed":
            continue

        try:
            parsed = {}
            try:
                parsed = json.loads(row.parsed_json or "{}")
            except Exception:
                parsed = {}
            result = parsed.get("result") or {}

            supplier = row.supplier or doc.supplier
            bill_no = row.bill_no
            bill_date = row.bill_date
            amount = row.amount or 0.0
            currency = row.currency

            rule = doc.duplicate_check_by or "Supplier + Bill No + Bill Date"
            if _exists_duplicate(supplier, bill_no, bill_date, row.sha1, rule):
                row.status = "Skipped"
                row.last_error = f"Duplicate detected by rule '{rule}'."
                skipped += 1
                continue

            pi = frappe.new_doc("Purchase Invoice")
            pi.supplier = supplier
            pi.posting_date = bill_date or today()
            pi.due_date = row.due_date or pi.posting_date
            pi.bill_no = bill_no
            pi.bill_date = bill_date
            pi.currency = currency

            # Choose item_code by supplier (Batelco/Beyon → bill_profile; EWA → account_no)
            item_code = _choose_item_code_for_supplier(supplier, result) or None

            # Fallback item if nothing resolved
            if not item_code:
                item_code = frappe.db.get_single_value("Buying Settings", "item") or None

            pi.append("items", {
                "item_code": item_code,
                "item_name": "Invoice Total" if not item_code else None,
                "qty": 1,
                "rate": amount
            })

            pi.flags.ignore_permissions = True
            pi.insert()
            pi.submit()

            if row.file:
                _attach_to_doc(row.file, pi.doctype, pi.name)

            row.status = "Parsed"
            row.created_purchase_invoice = pi.name
            created += 1
            messages.append(f"Created {pi.name} for {supplier} / {bill_no}")

        except Exception:
            row.status = "Error"
            row.last_error = frappe.get_traceback()
            failed += 1

    # Update parent counters
    doc.created_count = (doc.created_count or 0) + created
    doc.skipped_count = (doc.skipped_count or 0) + skipped
    doc.failed_count = (doc.failed_count or 0) + failed

    # Parent status
    if created > 0:
        doc.status = "Imported"
    elif any(r.status == "Parsed" for r in doc.source_files or []):
        doc.status = "Parsed"
    elif failed and not created:
        doc.status = "Failed"

    _append_log(doc, f"Create PIs: created={created}, skipped={skipped}, failed={failed}")
    doc.save(ignore_permissions=True)

    return {"created": created, "skipped": skipped, "failed": failed, "messages": messages}