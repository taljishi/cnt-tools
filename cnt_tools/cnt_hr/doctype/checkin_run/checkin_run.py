# Copyright (c) 2025, Cloud Nine Technologies (CNT) and contributors
# For license information, please see license.txt

import csv, io, codecs, re, pytz, hashlib, json
from datetime import timezone
from datetime import timedelta
import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, cstr, now_datetime, cint
from dateutil import parser as duparser

# Ensure Frappe can properly import the Checkin Run DocType
class CheckinRun(Document):
    pass


ISO_TS_PREFIX = re.compile(r'^\d{4}-\d{2}-\d{2}T')

# ---- Import/Result status constants ----

CREATED = "CREATED"
ALREADY_EXISTS = "ALREADY_EXISTS"
FAILED = "FAILED"
SKIPPED = "SKIPPED"

# Human-friendly labels for result_json
HUMAN_STATUSES = {
    "CREATED": "Created",
    "ALREADY_EXISTS": "Already Exists",
    "FAILED": "Failed",
    "SKIPPED": "Skipped",
}

def _site_tz():
    """Return the site timezone name (v15/v14 compatible), fallback to 'UTC'."""
    # v15
    try:
        from frappe.utils import get_system_timezone
        tz = get_system_timezone()
        if tz:
            return tz
    except Exception:
        pass
    # v14
    try:
        return frappe.utils.get_time_zone() or "UTC"
    except Exception:
        return "UTC"

def _result_row(row, status, detail="", name=""):
    """Compact result object for result_json."""
    return {
        "time": cstr(row.get("event_time") or row.get("time") or ""),
        "uid": cstr(row.get("attendance_device_id") or row.get("uid") or ""),
        "employee": cstr(row.get("matched_employee") or row.get("employee") or ""),
        "status": HUMAN_STATUSES.get(status, status),
        "detail": cstr(detail or "")[:2000],
        "name": cstr(name or ""),
    }


# -------- helpers --------

def _content_to_text(raw):
    """Decode raw file content (bytes or str) to text, stripping BOM.
    Tries utf-8, then UTF-16 (LE/BE), then cp1252 as a last resort.
    """
    if isinstance(raw, (bytes, bytearray)):
        b = bytes(raw)
        # Handle BOMs explicitly
        if b.startswith(codecs.BOM_UTF8):
            b = b[len(codecs.BOM_UTF8):]
            try:
                return b.decode("utf-8")
            except Exception:
                pass
        if b.startswith(codecs.BOM_UTF16_LE):
            try:
                return b.decode("utf-16-le")
            except Exception:
                pass
        if b.startswith(codecs.BOM_UTF16_BE):
            try:
                return b.decode("utf-16-be")
            except Exception:
                pass
        if b.startswith(codecs.BOM_UTF32_LE):
            try:
                return b.decode("utf-32-le")
            except Exception:
                pass
        if b.startswith(codecs.BOM_UTF32_BE):
            try:
                return b.decode("utf-32-be")
            except Exception:
                pass
        # Try common encodings
        for enc in ("utf-8", "utf-16", "utf-16-le", "utf-16-be", "cp1252"):
            try:
                return b.decode(enc)
            except Exception:
                continue
        # Last resort: replace errors
        return b.decode("utf-8", errors="replace")
    # Already a str: strip BOM if present
    s = (raw or "")
    return s.lstrip("\ufeff")

def _parse_csv_bytes(raw):
    """Return a DictReader from raw file content, preserving old behavior when headers exist."""
    text = _content_to_text(raw)
    # Auto-detect delimiter
    try:
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=[",",";","|","\t"])
    except Exception:
        dialect = csv.excel
    return csv.DictReader(io.StringIO(text), dialect=dialect)

# --- New: dialect detection helper
def _detect_dialect(text):
    """Return (dialect, delim_char) for CSV-like text; default to csv.excel and ','"""
    try:
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=[",",";","|","\t"])
        delim = getattr(dialect, 'delimiter', ',') or ','
    except Exception:
        dialect = csv.excel
        delim = ','
    return dialect, delim

def _iter_rows_headerless(text, dialect):
    """Yield (timestamp_str, last_col_value, raw_row) from headerless CSV rows.
    Uses first column as timestamp and last column as UID-like field (e.g., 'uid=3E1858DE')."""
    reader = csv.reader(io.StringIO(text), dialect=dialect)
    for row in reader:
        if not row:
            continue
        row = [ (c or "").strip() for c in row ]
        ts_raw = row[0] if len(row) >= 1 else ""
        last_raw = row[-1] if len(row) >= 1 else ""
        if not ts_raw:
            continue
        yield ts_raw, last_raw, row

def _normalize_time(s):
    """Parse incoming timestamp to an **aware UTC** datetime.
    - If string is ISO8601 with offset (e.g. 2025-10-13T09:26:01+03:00), preserve offset and convert to UTC.
    - If naive, assume site timezone and convert to UTC.
    """
    if not s:
        return get_datetime(s)
    # Prefer dateutil to preserve offsets
    try:
        dt = duparser.isoparse(cstr(s))
    except Exception:
        dt = get_datetime(s)
    # Localize naive to site tz, then convert to UTC
    if not getattr(dt, "tzinfo", None):
        try:
            site_tz = pytz.timezone(_site_tz())
            dt = site_tz.localize(dt)
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(pytz.UTC)

def _after_cutoff(ts, cutoff):
    # strict >
    return _to_utc(ts) > _to_utc(cutoff)

def _to_utc(dt_like):
    """Convert any datetime-like (string/naive/aware) to an **aware UTC** datetime."""
    if isinstance(dt_like, str):
        try:
            dt = duparser.isoparse(dt_like)
        except Exception:
            dt = get_datetime(dt_like)
    else:
        dt = get_datetime(dt_like)
    if not getattr(dt, "tzinfo", None):
        try:
            dt = pytz.timezone(_site_tz()).localize(dt)
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(pytz.UTC)


def _to_site_naive(dt_like):
    """Return site-local time with tzinfo stripped (naive) for DB/storage & preview."""
    if isinstance(dt_like, str):
        try:
            dt = duparser.isoparse(dt_like)
        except Exception:
            dt = get_datetime(dt_like)
    else:
        dt = get_datetime(dt_like)
    try:
        site_tz = pytz.timezone(_site_tz())
    except Exception:
        site_tz = timezone.utc
    if not getattr(dt, "tzinfo", None):
        dt_site = site_tz.localize(dt)
    else:
        dt_site = dt.astimezone(site_tz)
    return dt_site.replace(tzinfo=None)

def _extract_attendance_id(raw):
    """Return a clean attendance_device_id from strings like 'uid=3E1858DE' or plain '3E1858DE'."""
    s = cstr(raw or "").strip()
    if not s:
        return None
    # handle patterns like 'uid=3E1858DE' or 'uid==3E1858DE' (any spacing/case)
    m = re.search(r'uid\s*={1,2}\s*([0-9A-Fa-f]+)', s, flags=re.I)
    if m:
        s = m.group(1)
    # keep only hex/alnum just in case there are separators
    s = re.sub(r'[^0-9A-Za-z]+', '', s)
    s = s.upper()  # normalize to uppercase for consistent matching
    return s or None

def _find_token(row_cells, key):
    """Search a list of cells for 'key=value' (or 'key==value') and return the value (first match)."""
    key = key.strip()
    if not key:
        return None
    pattern = re.compile(rf'\b{re.escape(key)}\s*={1,2}\s*([^\s]+)', flags=re.IGNORECASE)
    for cell in row_cells:
        if not cell:
            continue
        m = pattern.search(cell)
        if m:
            return m.group(1)
    return None

def _resolve_attendance_id(row):
    # Header variants seen in 2N exports and common CSVs
    candidates = [
        "Attendance Device ID", "attendance_device_id",
        "UID", "Card UID",
        "Card Number", "Card ID", "Card code", "Card"
    ]
    for key in candidates:
        if key in row:
            val = row.get(key)
            if val:
                cleaned = _extract_attendance_id(val)
                if cleaned:
                    return cleaned
    return None

def _build_emp_map():
    """Return dict: CLEANED(attendance_device_id) -> Employee.name for Active employees."""
    emp_map = {}
    emps = frappe.get_all("Employee", fields=["name", "status", "attendance_device_id"])
    for e in emps:
        if (e.status or "").lower() != "active":
            continue
        raw = (e.attendance_device_id or "").strip()
        if not raw:
            continue
        cleaned = re.sub(r'[^0-9A-Za-z]+', '', raw).upper()
        if cleaned:
            emp_map[cleaned] = e.name
    return emp_map

def _match_employee(attendance_device_id: str):
    if not attendance_device_id:
        return None
    # Fast path via preloaded map on frappe.local for this request
    cache_key = "_checkin_emp_map"
    emp_map = getattr(frappe.local, cache_key, None)
    if emp_map is None:
        emp_map = _build_emp_map()
        setattr(frappe.local, cache_key, emp_map)
    emp = emp_map.get(attendance_device_id)
    if emp:
        return emp
    # Fallback: direct DB (in case of very recent change mid-request)
    return frappe.db.get_value(
        "Employee",
        {"attendance_device_id": attendance_device_id, "status": "Active"},
        "name",
    )


# ---- Gather inputs from child table and parent attachments ----
def _gather_inputs(doc):
    """Collect inputs from the child table `source_files` (Checkin Source File).
    Each child row should have:
      - file (Attach) -> file_url
      - device_name (Link: Checkin Access Device)
    We resolve the File by url/name, load bytes, and return a list of inputs.
    If a child has issues (missing file / unreadable), we set its `status` and `last_error` and skip it.
    """
    inputs = []

    def _fetch_file_by_url_or_name(url_or_name: str):
        u = cstr(url_or_name or '').strip()
        if not u:
            return None
        # Prefer exact file_url
        hit = frappe.get_all(
            'File',
            filters={'file_url': u},
            fields=['name', 'file_url', 'file_name', 'creation'],
            limit=1,
        )
        if hit:
            return frappe.get_doc('File', hit[0]['name'])
        # Fallback by basename (file_name)
        base = u.rsplit('/', 1)[-1]
        hit = frappe.get_all(
            'File',
            filters={'file_name': base},
            fields=['name', 'file_url', 'file_name', 'creation'],
            limit=1,
        )
        if hit:
            return frappe.get_doc('File', hit[0]['name'])
        return None

    for ch in (getattr(doc, 'source_files', None) or []):
        childname = ch.name
        file_url = cstr(ch.file or '').strip()
        device_name = cstr(getattr(ch, 'device_name', '') or '')

        if not file_url:
            try:
                frappe.db.set_value('Checkin Source File', childname, {
                    'status': 'Error',
                    'last_error': 'No file attached',
                })
            except Exception:
                pass
            continue

        fdoc = _fetch_file_by_url_or_name(file_url)
        if not fdoc:
            try:
                frappe.db.set_value('Checkin Source File', childname, {
                    'status': 'Error',
                    'last_error': f'File not found for {file_url}',
                })
            except Exception:
                pass
            continue

        raw = None
        err = None
        try:
            raw = fdoc.get_content()
            if not raw:
                err = 'Empty file content'
        except Exception as ex:
            err = f'Failed to read file: {ex}'

        # Compute SHA1 when possible (bytes only)
        sha1_hex = None
        try:
            if isinstance(raw, (bytes, bytearray)):
                sha1_hex = hashlib.sha1(bytes(raw)).hexdigest()
        except Exception:
            sha1_hex = None

        # Persist immediate diagnostics on the child row
        try:
            frappe.db.set_value('Checkin Source File', childname, {
                'sha1': sha1_hex,
                # Do not set parsed/ready here; those are set after parsing in _parse_all_inputs
            })
        except Exception:
            pass

        if err:
            try:
                frappe.db.set_value('Checkin Source File', childname, {
                    'status': 'Error',
                    'last_error': err,
                })
            except Exception:
                pass
            continue

        display_name = fdoc.file_name or fdoc.file_url or 'source.csv'
        inputs.append({
            'content': raw,
            'src_label': fdoc.file_url or display_name,
            'device_name': device_name,
            'file_url': fdoc.file_url or '',
            'display_name': display_name,
            'creation': fdoc.creation,
            'childname': childname,
        })

    # Return inputs sorted by newest file first (consistent with prior behavior)
    inputs.sort(key=lambda x: x['creation'], reverse=True)
    return inputs

def _exists_checkin(emp, ts, window_secs):
    from datetime import timedelta
    start = ts - timedelta(seconds=int(window_secs))
    end = ts + timedelta(seconds=int(window_secs))
    # De-dupe by employee+time only (ignore log_type)
    return frappe.db.exists(
        "Employee Checkin",
        {"employee": emp, "time": ["between", [start, end]]}
    )


# Parse everything on-demand (no staging child table)
# Returns (rows, summary) where rows is a list of dicts and summary is a dict of counts
def _parse_all_inputs(doc):
    inputs = _gather_inputs(doc)
    # Track chosen files (all processed children)
    chosen_files = []
    for _i in inputs:
        lab = _i.get('file_url') or _i.get('display_name')
        if lab:
            chosen_files.append(lab)
    if not inputs:
        frappe.throw("Attach one CSV on this Checkin Run (Attach field or paperclip) before parsing.")

    # Warm employee map cache
    setattr(frappe.local, "_checkin_emp_map", _build_emp_map())

    window_secs = int(doc.gap_between_events or 60)
    seen_last_ts = {}

    rows = []
    parsed = 0
    matched_ready = 0
    skip_before_cutoff = 0
    skipped_duplicates = 0
    skip_no_employee = 0
    unmatched_ids = set()
    empty_files = []

    for _inp in inputs:
        child_rowname = _inp.get('childname')
        start_parsed = parsed
        start_ready = matched_ready
        raw = _inp["content"]
        text = _content_to_text(raw)
        src_label = _inp["src_label"]
        device_name = cstr(_inp.get("device_name", ""))

        first_line = text.splitlines()[0].lstrip("\ufeff\ufeff\u200b\uFEFF").strip() if text else ""
        dialect, delim = _detect_dialect(text)
        # Check headerless using detected delimiter
        first_cell = first_line.split(delim)[0] if first_line else ""
        use_headerless = bool(first_cell and ISO_TS_PREFIX.match(first_cell))

        if use_headerless:
            for ts_raw, last_raw, row in _iter_rows_headerless(text, dialect):
                try:
                    ts = _normalize_time(ts_raw)
                except Exception:
                    continue
                if not _after_cutoff(ts, doc.cutoff_time):
                    skip_before_cutoff += 1
                    continue
                ts_db = _to_site_naive(ts)

                uid_cell = row[6] if len(row) > 6 else None
                uid_token = uid_cell or _find_token(row, "uid")
                attendance_id = _extract_attendance_id(uid_token)
                emp = _match_employee(attendance_id)

                # in-memory de-dupe across this run
                dedupe_key = ("EMP", emp) if emp else (("UID", attendance_id) if attendance_id else None)
                if dedupe_key is not None:
                    last = seen_last_ts.get(dedupe_key)
                    if last and abs(ts_db - last) <= timedelta(seconds=window_secs):
                        skipped_duplicates += 1
                        continue
                    seen_last_ts[dedupe_key] = ts_db

                ready = 1 if emp else 0
                if ready:
                    matched_ready += 1
                else:
                    skip_no_employee += 1
                    if attendance_id:
                        unmatched_ids.add(attendance_id)

                rows.append({
                    "event_time": ts_db,
                    "device_name": device_name,
                    "attendance_device_id": attendance_id or "",
                    "matched_employee": emp or "",
                    "source_file": (_inp.get("display_name") or src_label),
                    "ready": ready,
                })
                parsed += 1
        else:
            reader = _parse_csv_bytes(raw)
            for r in reader:
                ts = _normalize_time(r.get("Time") or r.get("Timestamp") or r.get("Date Time"))
                if not _after_cutoff(ts, doc.cutoff_time):
                    skip_before_cutoff += 1
                    continue
                ts_db = _to_site_naive(ts)

                attendance_id = _resolve_attendance_id(r)
                emp = _match_employee(attendance_id)

                dedupe_key = ("EMP", emp) if emp else (("UID", attendance_id) if attendance_id else None)
                if dedupe_key is not None:
                    last = seen_last_ts.get(dedupe_key)
                    if last and abs(ts_db - last) <= timedelta(seconds=window_secs):
                        skipped_duplicates += 1
                        continue
                    seen_last_ts[dedupe_key] = ts_db

                ready = 1 if emp else 0
                if ready:
                    matched_ready += 1
                else:
                    skip_no_employee += 1
                    if attendance_id:
                        unmatched_ids.add(attendance_id)

                rows.append({
                    "event_time": ts_db,
                    "device_name": device_name,
                    "attendance_device_id": attendance_id or "",
                    "matched_employee": emp or "",
                    "source_file": (_inp.get("display_name") or src_label),
                    "ready": ready,
                })
                parsed += 1

        # Per-child accounting and status update
        parsed_delta = parsed - start_parsed
        ready_delta = matched_ready - start_ready
        try:
            frappe.db.set_value('Checkin Source File', child_rowname, {
                'parsed_count': parsed_delta,
                'ready_count': ready_delta,
                'status': 'Parsed' if parsed_delta else 'Skipped',
                'last_error': '',
            })
        except Exception:
            pass

        # If this input produced no parsed rows, remember it for diagnostics
        if parsed == start_parsed and (src_label or _inp.get("display_name")):
            empty_files.append(_inp.get("display_name") or src_label)

    # Sort rows by time ascending for stable downstream behavior
    def _row_time_val(x):
        try:
            return get_datetime(x.get("event_time"))
        except Exception:
            return None
    rows.sort(key=lambda x: (_row_time_val(x) is None, _row_time_val(x)))

    summary = {
        'parsed': parsed,
        'ready': matched_ready,
        'skipped_before_cutoff': skip_before_cutoff,
        'skipped_duplicates': skipped_duplicates,
        'skipped_no_employee': skip_no_employee,
        'unmatched_ids': sorted(unmatched_ids),
        'empty_files': empty_files,
        'chosen_file': ", ".join(chosen_files),
    }
    return rows, summary

# -------- actions --------

@frappe.whitelist()
def parse_source(name: str, show_popup: int = 0):
    """Parse attached CSVs after cutoff and compute preview (no staging table)."""
    doc = frappe.get_doc("Checkin Run", name)
    if not doc.cutoff_time:
        frappe.throw("Please set Cutoff Time before parsing.")

    rows, summary = _parse_all_inputs(doc)

    # Update status and counts only; no child rows are stored
    doc.parsed_count = summary["parsed"]
    doc.imported_count = 0
    doc.status = "Parsed" if summary["parsed"] else "Draft"
    doc.save()

    preview = ""
    if summary["unmatched_ids"]:
        preview_list = summary["unmatched_ids"][:10]
        more = "" if len(summary["unmatched_ids"]) <= 10 else f" (and {len(summary['unmatched_ids'])-10} more)"
        preview = "<br>Unmatched Attendance Device ID (up to 10):<br><code>" + ", ".join(preview_list) + "</code>" + more

    if cint(show_popup):
        frappe.msgprint(
            f"Parsed: <b>{summary['parsed']}</b> rows. Ready rows: <b>{summary['ready']}</b>."
            f"<br>Skipped before cutoff: {summary['skipped_before_cutoff']}. Skipped duplicates (within {int(doc.gap_between_events or 60)}s): {summary['skipped_duplicates']}. Skipped no employee: {summary['skipped_no_employee']}."
            f"<br>Source file: <code>{frappe.utils.escape_html(summary.get('chosen_file') or '')}</code>"
            f"{preview}",
            title="Parsed Data",
            indicator="green" if summary['parsed'] else "orange",
        )

    return summary

@frappe.whitelist()
def generate_checkins(name: str):
    """Create Employee Checkin docs from on-demand parsed rows (no staging table)."""
    doc = frappe.get_doc("Checkin Run", name)
    run_name = doc.name
    if doc.status not in ("Parsed", "Draft"):
        frappe.throw(f"Checkin Run is not in a state to generate Employee Checkin. Status: {doc.status}")

    rows, summary = _parse_all_inputs(doc)

    created = 0
    existed = 0
    failed = 0
    results = []
    window = int(doc.gap_between_events or 60)
    created_times = []

    for e in rows:
        # Only process rows that are ready and have a matched employee
        if not e.get("ready") or not e.get("matched_employee"):
            results.append(_result_row(e, SKIPPED, detail="Row not ready or no employee"))
            continue

        # Convert site-local stored value back to UTC-naive for reliable compare/insert
        ts = _to_site_naive(e.get("event_time"))
        emp = e.get("matched_employee")

        # Idempotency: skip if a checkin exists within the window
        if _exists_checkin(emp, ts, window):
            # Best-effort: find the existing record and backfill the custom_checkin_run link if missing
            try:
                ec_name = frappe.db.get_value(
                    'Employee Checkin',
                    {
                        'employee': emp,
                        'time': ['between', [ts - timedelta(seconds=int(window)), ts + timedelta(seconds=int(window))]],
                    },
                    'name',
                )
                if ec_name:
                    cur_val = frappe.db.get_value('Employee Checkin', ec_name, 'custom_checkin_run')
                    if not cur_val:
                        frappe.db.set_value('Employee Checkin', ec_name, 'custom_checkin_run', run_name)
            except Exception:
                pass

            existed += 1
            results.append(_result_row(e, ALREADY_EXISTS))
            continue

        try:
            chk = frappe.get_doc({
                "doctype": "Employee Checkin",
                "employee": emp,
                "time": ts,
                "device_id": e.get("device_name") or "2N",
                "skip_auto_attendance": 0,
                "custom_attendance_device_id": e.get("attendance_device_id"),
                "custom_checkin_run": run_name,
            })
            chk.insert(ignore_permissions=True)
            # Add an audit comment on the created Employee Checkin (human-friendly trace)
            try:
                chk.add_comment('Info', f"Generated from Checkin Run {run_name}")
            except Exception:
                pass
            created += 1
            created_times.append(ts)
            results.append(_result_row(e, CREATED, name=chk.name))
        except Exception:
            failed += 1
            # capture full traceback for diagnostics
            results.append(_result_row(e, FAILED, detail=frappe.get_traceback()))

    # Persist summary & detailed outcomes on parent doc
    try:
        doc.imported_count = created
        doc.already_exists_count = existed
        doc.failed_count = failed
        doc.result_json = frappe.as_json(results)
        doc.result_imported_on = now_datetime()
        doc.status = "Imported" if failed == 0 else "Failed"
        doc.save()
    except Exception:
        # In case of any unexpected error while saving summary, raise the original context
        frappe.throw("Failed to update Checkin Run summary; see server logs.")

    # Update Shift Type last_sync_of_checkin if newer data arrived
    shifts_updated = 0
    last_ts = None
    if created_times:
        last_ts = max(created_times)
        active_shifts = frappe.get_all(
            "Shift Type",
            filters={"custom_disabled": 0},
            fields=["name", "last_sync_of_checkin"],
        )
        for sh in active_shifts:
            current = sh.get("last_sync_of_checkin")
            if not current or get_datetime(current) < last_ts:
                frappe.db.set_value("Shift Type", sh["name"], "last_sync_of_checkin", last_ts)
                shifts_updated += 1

    return {
        "created": created,
        "already_exists": existed,
        "failed": failed,
        "last_checkin_time": last_ts,
        "shifts_updated": shifts_updated,
    }


# ---- Preview endpoint for dialog ----
@frappe.whitelist()
def cr_preview(name: str, start: int = 0, page_len: int = 200, order: str = "desc"):
    """Return rows + counts for the preview dialog from on-demand parsing (no staging)."""
    doc = frappe.get_doc("Checkin Run", name)
    rows, summary = _parse_all_inputs(doc)

    start = int(start or 0)
    page_len = min(int(page_len or 200), 2000)
    order = "desc" if (order or "").lower() == "desc" else "asc"

    def _evt_dt(x):
        try:
            return get_datetime(x.get("event_time"))
        except Exception:
            return None

    rows.sort(key=lambda r: (_evt_dt(r) is None, _evt_dt(r)), reverse=(order == "desc"))

    total = len(rows)
    slice_ = rows[start:start + page_len]

    data = []
    for i, r in enumerate(slice_, start=start + 1):
        data.append({
            "idx": i,
            "event_time": cstr(r.get("event_time")),
            "employee": cstr(r.get("matched_employee")),
            "attendance_device_id": cstr(r.get("attendance_device_id")),
            "device_name": cstr(r.get("device_name")),
            "source_file": cstr(r.get("source_file")),
            "ready": int(r.get("ready") or 0),
        })



    return {
        "total": total,
        "ready": int(summary.get("ready") or 0),
        "rows": data,
        "order": order,
        "start": start,
        "page_len": page_len,
    }


# ---- Helper: imported time range from result_json ----
@frappe.whitelist()
def cr_imported_time_range(name: str):
    """Return the [min, max] times of Employee Checkins created by this run using result_json.
    If no created rows are found, both values will be None.
    """
    doc = frappe.get_doc("Checkin Run", name)
    try:
        results = json.loads(doc.result_json or "[]")
    except Exception:
        results = []

    times = []
    for r in results:
        # result rows are built by _result_row(); status label is in r['status']
        st = (r.get("status") or "").upper()
        # Accept both canonical and labeled forms just in case
        if st in ("CREATED", "Created"):
            ts = r.get("time")
            if ts:
                try:
                    times.append(get_datetime(ts))
                except Exception:
                    pass

    if not times:
        return {"min": None, "max": None}

    return {"min": min(times), "max": max(times)}