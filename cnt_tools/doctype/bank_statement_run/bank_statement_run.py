# Copyright (c) 2025, Cloud Nine Technologies (CNT) and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

# Fields we copy from Bank Statement Mapping onto the Formatter
_MAPPING_KEYS = [
    "file_type", "encoding", "delimiter", "decimal_separator",
    "remove_thousand_separators", "skip_header_rows", "date_format",
    "has_credit_debit_columns", "date_column", "description_column",
    "amount_column", "credit_column", "debit_column", "balance_column",
    "reference_column", "credit_is_positive", "negative_parentheses_as_minus",
    "ignore_rows_containing",
]


def _MAP_MAPPING_KEYS():
    return _MAPPING_KEYS


class BankStatementRun(Document):
    def validate(self):
        """Fetch currency and (if empty) auto-apply mapping from Bank Account."""
        if self.bank_account:
            acc = frappe.get_doc("Bank Account", self.bank_account)
            acc_currency = getattr(acc, "account_currency", None) or getattr(acc, "custom_account_currency", None)
            if not acc_currency and getattr(acc, "company", None):
                acc_currency = frappe.get_cached_value("Company", acc.company, "default_currency")
            self.currency = acc_currency

            self._apply_mapping_from_bank_account_if_missing(acc)

    # Instance methods so frm.call('preview_rows')/run_doc_method works
    @frappe.whitelist()
    def preview_rows(self):
        return preview_rows(self.name)

    @frappe.whitelist()
    def create_bank_transactions(self):
        return create_bank_transactions(self.name)

    def before_save(self):
        """If source_file changed compared to DB, reset status to Draft and clear failure_reason."""
        try:
            if not self.name:
                return
            prev = frappe.db.get_value(self.doctype, self.name, "source_file")
            if prev and self.source_file and prev != self.source_file:
                self.status = "Draft"
                self.failure_reason = None
        except Exception:
            # Non-blocking safeguard
            pass

    # -------------------------
    # Helpers (instance)
    # -------------------------
    def _apply_mapping_from_bank_account_if_missing(self, acc_doc):
        """If Bank Account has a linked statement mapping and core fields are blank, copy them in."""
        mapping_name = getattr(acc_doc, "bank_statement_mapping", None) or getattr(acc_doc, "custom_bank_statement_mapping", None)
        if not mapping_name:
            return

        needs_apply = not (
            getattr(self, "date_column", None)
            and getattr(self, "description_column", None)
            and (
                getattr(self, "amount_column", None)
                or (
                    getattr(self, "has_credit_debit_columns", 0)
                    and getattr(self, "credit_column", None)
                    and getattr(self, "debit_column", None)
                )
            )
        )
        if not needs_apply:
            return

        m = frappe.get_doc("Bank Statement Mapping", mapping_name)
        for k in _MAP_MAPPING_KEYS():
            self.set(k, m.get(k))


def _require_mapping(doc):
    """Ensure minimum mapping is present before parsing."""
    missing = []
    if not getattr(doc, "source_file", None):
        frappe.throw("Please upload a statement file first.")
    if not getattr(doc, "date_column", None):
        missing.append("Date Column")
    if not getattr(doc, "description_column", None):
        missing.append("Description Column")
    if getattr(doc, "has_credit_debit_columns", 0):
        if not getattr(doc, "credit_column", None):
            missing.append("Credit Column")
        if not getattr(doc, "debit_column", None):
            missing.append("Debit Column")
    else:
        if not getattr(doc, "amount_column", None):
            missing.append("Amount Column")
    if missing:
        frappe.throw("Please fill the following fields before Preview: " + ", ".join(missing))


# ---------- Detection helpers ----------

def _detect_from_header(header):
    """Heuristically guess mapping keys from a header row (list[str]).
    - Normalizes punctuation/parentheses so headers like "Credit (Deposit)" work.
    - Expands alias matching for credit/debit (deposit/withdrawal) and other common labels.
    """
    import re

    # Keep original header strings for returning exact labels
    h = [(c or "").strip() for c in header]

    def norm(s: str) -> str:
        # lowercase, replace punctuation with spaces, collapse spaces
        s = (s or "").lower()
        s = re.sub(r"[()\[\]{}_/\\.,;:\-]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    hn = [norm(c) for c in h]

    def find_any(*needles):
        for i, col in enumerate(hn):
            for n in needles:
                if n in col:
                    return i
        return None

    guesses = {
        "date_column": None,
        "description_column": None,
        "amount_column": None,
        "credit_column": None,
        "debit_column": None,
        "balance_column": None,
        "reference_column": None,
        "has_credit_debit_columns": 0,
    }

    # Date
    di = find_any("value date", "txn date", "transaction date", "posting date", "date")
    guesses["date_column"] = h[di] if di is not None else None

    # Description
    di2 = find_any("description", "details", "narration", "remarks", "memo", "particulars")
    guesses["description_column"] = h[di2] if di2 is not None else None

    # Amount vs Credit/Debit (with aliases)
    ai = find_any("amount", "transaction amount", "amt")

    # Credit-like
    cri = find_any(
        "credit", "cr", "deposit", "credit deposit", "deposit amount", "amount credited", "credit amount"
    )
    # Debit-like
    dri = find_any(
        "debit", "dr", "withdrawal", "debit withdrawal", "withdrawal amount", "amount debited", "debit amount"
    )

    if ai is not None and (cri is None or dri is None):
        guesses["amount_column"] = h[ai]
        guesses["has_credit_debit_columns"] = 0
    elif cri is not None and dri is not None:
        guesses["credit_column"] = h[cri]
        guesses["debit_column"] = h[dri]
        guesses["has_credit_debit_columns"] = 1

    # Optional
    bi = find_any("running balance", "available balance", "balance", "closing balance", "ledger balance")
    if bi is not None:
        guesses["balance_column"] = h[bi]
    ri = find_any("reference", "ref", "cheque", "chq", "utr", "transaction id", "txn id")
    if ri is not None:
        guesses["reference_column"] = h[ri]

    return guesses


@frappe.whitelist()
def detect_columns(docname: str):
    """Read the uploaded CSV, return header and heuristic mapping guesses. Does NOT modify the doc."""
    import csv, io
    from frappe.utils.file_manager import get_file_path

    doc = frappe.get_doc("Bank Statement Run", docname)
    if not getattr(doc, "source_file", None):
        frappe.throw("Please upload a statement file first.")
    if (doc.file_type or "").upper() != "CSV":
        frappe.throw("Detection supports CSV only right now.")

    file_path = get_file_path(doc.source_file)
    try:
        fh = io.open(file_path, "r", encoding=doc.encoding or "utf-8", newline="")
    except FileNotFoundError:
        frappe.throw(f"File not found: {doc.source_file}")

    with fh as f:
        reader = csv.reader(f, delimiter=(doc.delimiter or ",")[:1])
        rows = list(reader)

    skip = int(doc.skip_header_rows or 0)
    header = rows[skip] if rows and skip < len(rows) else []
    guesses = _detect_from_header(header) if header else {}

    return {"header": header, "guesses": guesses}


@frappe.whitelist()
def preview_rows(docname: str):
    """
    Parse the uploaded statement using the mapping on the doc and store a preview payload.
    - CSV only for now.
    - Respects delimiter, encoding, skip_header_rows, decimal/thousand separators, parentheses negatives.
    - Supports either Amount or Credit/Debit mapping (UI will display Credit/Debit only).
    - Emits beginning_balance/ending_balance when Balance column exists.
    """
    import csv
    import io
    from datetime import datetime
    from frappe.utils.file_manager import get_file_path

    doc = frappe.get_doc("Bank Statement Run", docname)
    try:

        if (doc.file_type or "").upper() != "CSV":
            frappe.throw("Only CSV preview is supported right now. Set File Type to CSV.")

        # --- helpers ---
        def _resolve_index(header, key):
            """Return zero-based index for a column key. Key can be a header label or 1-based position."""
            if key is None:
                return None
            key_str = str(key).strip()
            if key_str.isdigit():
                idx = int(key_str) - 1
                return idx if 0 <= idx < len(header) else None
            header_lc = [h.strip().lower() for h in header]
            try:
                return header_lc.index(key_str.lower())
            except ValueError:
                return None

        def _to_number(s: str) -> float:
            if s is None:
                return 0.0
            txt = str(s).strip()
            if not txt:
                return 0.0
            neg = False
            if getattr(doc, "negative_parentheses_as_minus", 0) and txt.startswith("(") and txt.endswith(")"):
                neg = True
                txt = txt[1:-1]
            if getattr(doc, "remove_thousand_separators", 1):
                txt = txt.replace(",", "").replace(" ", "")
            dec = (doc.decimal_separator or ".").strip()
            if dec == ",":
                txt = txt.replace(".", "").replace(",", ".")
            try:
                val = float(txt)
            except Exception:
                val = 0.0
            return -val if neg else val

        def _parse_date(s: str) -> datetime:
            raw = (s or "").strip()
            if not raw:
                raise ValueError("empty date")
            # 1) Try the doc-specified format first
            fmt = (doc.date_format or "DD/MM/YYYY").upper()
            py = fmt.replace("YYYY", "%Y").replace("YY", "%y").replace("MM", "%m").replace("DD", "%d")
            py = py.replace("HH", "%H").replace("hh", "%H").replace("mm", "%M").replace("SS", "%S")
            from datetime import datetime as _dt
            try:
                return _dt.strptime(raw, py)
            except Exception:
                pass
            # 2) Fallbacks (common bank exports)
            candidates = [
                "%Y-%m-%d",
                "%d-%m-%Y",
                "%m-%d-%Y",
                "%d/%m/%Y",
                "%m/%d/%Y",
                "%d-%b-%Y",
                "%d %b %Y",
                "%d %B %Y",
                "%Y/%m/%d",
                "%d.%m.%Y",
                "%Y-%m-%d %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
                "%m/%d/%Y %H:%M:%S",
            ]
            for cf in candidates:
                try:
                    return _dt.strptime(raw, cf)
                except Exception:
                    continue
            # 3) Give a clear error
            raise ValueError(f"Unparsable date '{raw}' (expected like {fmt})")

        # Load file
        file_path = get_file_path(doc.source_file)
        try:
            raw = io.open(file_path, "r", encoding=doc.encoding or "utf-8", newline="")
        except FileNotFoundError:
            frappe.throw(f"File not found: {doc.source_file}")

        with raw as fh:
            reader = csv.reader(fh, delimiter=(doc.delimiter or ",")[:1])
            rows = list(reader)

        # Skip headers
        skip = int(doc.skip_header_rows or 0)
        header_row = rows[skip] if rows and skip < len(rows) else []
        data_rows = rows[skip + 1:] if skip + 1 <= len(rows) else []

        # Try to auto-detect missing mapping from header
        guesses = _detect_from_header(header_row) if header_row else {}

        # Decide which mode to use locally (do not overwrite doc mapping)
        local_has_cd = bool(doc.has_credit_debit_columns) or bool(guesses.get("has_credit_debit_columns"))

        date_key = doc.date_column or guesses.get("date_column")
        desc_key = doc.description_column or guesses.get("description_column")
        amount_key = None
        credit_key = None
        debit_key = None

        if local_has_cd:
            credit_key = doc.credit_column or guesses.get("credit_column")
            debit_key = doc.debit_column or guesses.get("debit_column")
            # If credit/debit still not found, fall back to Amount if available
            if not (credit_key and debit_key):
                local_has_cd = False
                amount_key = doc.amount_column or guesses.get("amount_column")
        else:
            amount_key = doc.amount_column or guesses.get("amount_column")

        # Resolve indices using local keys
        date_i = _resolve_index(header_row, date_key)
        desc_i = _resolve_index(header_row, desc_key)
        amt_i = _resolve_index(header_row, amount_key) if not local_has_cd else None
        cr_i = _resolve_index(header_row, credit_key) if local_has_cd else None
        dr_i = _resolve_index(header_row, debit_key) if local_has_cd else None
        bal_i = _resolve_index(header_row, doc.balance_column or guesses.get("balance_column"))
        ref_i = _resolve_index(header_row, doc.reference_column or guesses.get("reference_column"))

        missing_idx = []
        if date_i is None:
            missing_idx.append("Date Column")
        if desc_i is None:
            missing_idx.append("Description Column")
        if local_has_cd:
            if cr_i is None:
                missing_idx.append("Credit (Deposit) Column")
            if dr_i is None:
                missing_idx.append("Debit (Withdrawal) Column")
        else:
            if amt_i is None:
                missing_idx.append("Amount Column")
        if missing_idx:
            frappe.throw("Mapping didn't match the header row. Missing/invalid: " + ", ".join(missing_idx))

        # Ignore filters
        ignore_terms = []
        if getattr(doc, "ignore_rows_containing", None):
            ignore_terms = [t.strip() for t in (doc.ignore_rows_containing or "").splitlines() if t.strip()]

        sample = []
        dates = []
        parsed_rows = []  # for beginning/ending balance computation
        debit_count = 0
        credit_count = 0
        debit_sum = 0.0
        credit_sum = 0.0

        # Build normalized preview (no single Amount field)
        for r in data_rows:
            if len(r) < len(header_row):
                r = r + [""] * (len(header_row) - len(r))

            desc = r[desc_i] if desc_i is not None else ""
            if ignore_terms and any(term.lower() in (desc or "").lower() for term in ignore_terms):
                continue

            try:
                dt = _parse_date(r[date_i]) if date_i is not None else None
            except Exception:
                continue

            if local_has_cd:
                credit = _to_number(r[cr_i]) if cr_i is not None else 0.0
                debit = _to_number(r[dr_i]) if dr_i is not None else 0.0
            else:
                amount = _to_number(r[amt_i]) if amt_i is not None else 0.0
                credit = amount if amount > 0 else 0.0
                debit = -amount if amount < 0 else 0.0

            if credit > 0:
                credit_count += 1
                credit_sum += credit
            if debit > 0:
                debit_count += 1
                debit_sum += debit

            balance_str = r[bal_i] if bal_i is not None else ""
            reference = r[ref_i] if ref_i is not None else ""

            if dt:
                dates.append(dt)

            parsed_rows.append({
                "dt": dt,
                "credit": credit,
                "debit": debit,
                "balance_str": balance_str,
                "desc": desc,
                "reference": reference,
            })

            if len(sample) < 100:
                sample.append({
                    "Date": dt.strftime("%Y-%m-%d") if dt else "",
                    "Description": desc,
                    "Deposit": round(credit, 3),
                    "Withdrawal": round(debit, 3),
                    "Balance": balance_str,
                    "Reference Number": reference,
                })

        total_rows = len(parsed_rows)
        if dates:
            doc.statement_start = min(dates).date().isoformat()
            doc.statement_end = max(dates).date().isoformat()

        beginning_balance = None
        ending_balance = None
        if bal_i is not None and parsed_rows:
            first = parsed_rows[0]
            last = parsed_rows[-1]
            try:
                first_bal = _to_number(first["balance_str"]) if first["balance_str"] else None
                last_bal = _to_number(last["balance_str"]) if last["balance_str"] else None
                if first_bal is not None:
                    beginning_balance = round(first_bal - (first["credit"] - first["debit"]), 3)
                if last_bal is not None:
                    ending_balance = round(last_bal, 3)
            except Exception:
                pass

        # Explicit column order for client renderer
        column_order = [
            "Date",
            "Description",
            "Deposit",
            "Withdrawal",
            "Balance",
            "Reference Number",
        ]

        payload = {
            "columns": [{"label": c} for c in column_order],
            "sample": sample,
            "total_rows": total_rows,
            "balances": {
                "beginning_balance": beginning_balance,
                "ending_balance": ending_balance,
            },
            "totals": {
                "debits": {"count": debit_count, "amount": round(debit_sum, 3)},
                "credits": {"count": credit_count, "amount": round(credit_sum, 3)},
                "currency": doc.currency or "",
            },
        }

        # Persist summary fields on the document (requires fields on doctype)
        try:
            doc.beginning_balance = float(beginning_balance) if beginning_balance is not None else None
            doc.ending_balance = float(ending_balance) if ending_balance is not None else None
            doc.debit_count = int(debit_count or 0)
            doc.credit_count = int(credit_count or 0)
            doc.debit_sum = float(round(debit_sum or 0.0, 3))
            doc.credit_sum = float(round(credit_sum or 0.0, 3))
        except Exception:
            pass

        current_status = (doc.status or "").strip()
        doc.preview_json = frappe.as_json(payload)
        doc.rows_detected = total_rows
        if current_status != "Imported":
            doc.status = "Parsed"
        doc.failure_reason = None
        doc.save(ignore_permissions=True)
        return payload

    except Exception as e:
        # Mark as Failed and capture reason
        try:
            import traceback
            reason = f"{e.__class__.__name__}: {e}"
            tb = traceback.format_exc()
            doc.status = "Failed"
            doc.failure_reason = f"{reason}\n\n{tb}"
            doc.save(ignore_permissions=True)
        except Exception:
            pass
        # re-raise so the client gets the error
        raise


@frappe.whitelist()
def create_bank_transactions(docname: str):
    """
    Create ERPNext **Bank Transaction** records from the mapped CSV.
    - Uses Credit/Debit columns if present, otherwise Amount sign to split.
    - Dedupe by (bank_account, date, deposit, withdrawal, description, reference_number).
    """
    import csv, io
    from datetime import datetime
    from frappe.utils.file_manager import get_file_path

    doc = frappe.get_doc("Bank Statement Run", docname)
    # Disallow duplicate generation once already imported; enforce state machine
    current_status = (doc.status or "").strip()
    if current_status == "Imported":
        frappe.throw("This Bank Statement Run has already been imported. Duplicate generation is blocked.")
    if current_status not in ("Parsed", "Failed", "Draft", ""):  # allow retry on Failed, but prefer Parsed
        frappe.throw(f"Cannot generate transactions while status is '{current_status}'. Parse the file first.")
    try:

        if (doc.file_type or "").upper() != "CSV":
            frappe.throw("Only CSV import is supported right now.")

        def _resolve_index(header, key):
            if key is None:
                return None
            key_str = str(key).strip()
            if key_str.isdigit():
                idx = int(key_str) - 1
                return idx if 0 <= idx < len(header) else None
            header_lc = [h.strip().lower() for h in header]
            try:
                return header_lc.index(key_str.lower())
            except ValueError:
                return None

        def _to_number(s: str) -> float:
            if s is None:
                return 0.0
            txt = str(s).strip()
            if not txt:
                return 0.0
            neg = False
            if getattr(doc, "negative_parentheses_as_minus", 0) and txt.startswith("(") and txt.endswith(")"):
                neg = True
                txt = txt[1:-1]
            if getattr(doc, "remove_thousand_separators", 1):
                txt = txt.replace(",", "").replace(" ", "")
            dec = (doc.decimal_separator or ".").strip()
            if dec == ",":
                txt = txt.replace(".", "").replace(",", ".")
            try:
                val = float(txt)
            except Exception:
                val = 0.0
            return -val if neg else val

        def _parse_date(s: str) -> datetime:
            raw = (s or "").strip()
            if not raw:
                raise ValueError("empty date")
            # 1) Try the doc-specified format first
            fmt = (doc.date_format or "DD/MM/YYYY").upper()
            py = fmt.replace("YYYY", "%Y").replace("YY", "%y").replace("MM", "%m").replace("DD", "%d")
            py = py.replace("HH", "%H").replace("hh", "%H").replace("mm", "%M").replace("SS", "%S")
            from datetime import datetime as _dt
            try:
                return _dt.strptime(raw, py)
            except Exception:
                pass
            # 2) Fallbacks (common bank exports)
            candidates = [
                "%Y-%m-%d",
                "%d-%m-%Y",
                "%m-%d-%Y",
                "%d/%m/%Y",
                "%m/%d/%Y",
                "%d-%b-%Y",
                "%d %b %Y",
                "%d %B %Y",
                "%Y/%m/%d",
                "%d.%m.%Y",
                "%Y-%m-%d %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
                "%m/%d/%Y %H:%M:%S",
            ]
            for cf in candidates:
                try:
                    return _dt.strptime(raw, cf)
                except Exception:
                    continue
            # 3) Give a clear error
            raise ValueError(f"Unparsable date '{raw}' (expected like {fmt})")

        file_path = get_file_path(doc.source_file)
        with io.open(file_path, "r", encoding=doc.encoding or "utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter=(doc.delimiter or ",")[:1])
            rows = list(reader)

        skip = int(doc.skip_header_rows or 0)
        header_row = rows[skip] if rows and skip < len(rows) else []
        data_rows = rows[skip + 1:] if skip + 1 <= len(rows) else []

        # Try to auto-detect missing mapping from header
        guesses = _detect_from_header(header_row) if header_row else {}

        local_has_cd = bool(doc.has_credit_debit_columns) or bool(guesses.get("has_credit_debit_columns"))

        date_key = doc.date_column or guesses.get("date_column")
        desc_key = doc.description_column or guesses.get("description_column")
        amount_key = None
        credit_key = None
        debit_key = None

        if local_has_cd:
            credit_key = doc.credit_column or guesses.get("credit_column")
            debit_key = doc.debit_column or guesses.get("debit_column")
            if not (credit_key and debit_key):
                local_has_cd = False
                amount_key = doc.amount_column or guesses.get("amount_column")
        else:
            amount_key = doc.amount_column or guesses.get("amount_column")

        # Resolve indices using local keys
        date_i = _resolve_index(header_row, date_key)
        desc_i = _resolve_index(header_row, desc_key)
        amt_i = _resolve_index(header_row, amount_key) if not local_has_cd else None
        cr_i = _resolve_index(header_row, credit_key) if local_has_cd else None
        dr_i = _resolve_index(header_row, debit_key) if local_has_cd else None
        bal_i = _resolve_index(header_row, doc.balance_column or guesses.get("balance_column"))
        ref_i = _resolve_index(header_row, doc.reference_column or guesses.get("reference_column"))

        # Validate mapping availability before processing
        missing_idx = []
        if date_i is None:
            missing_idx.append("Date Column")
        if desc_i is None:
            missing_idx.append("Description Column")
        if local_has_cd:
            if cr_i is None:
                missing_idx.append("Credit (Deposit) Column")
            if dr_i is None:
                missing_idx.append("Debit (Withdrawal) Column")
        else:
            if amt_i is None:
                missing_idx.append("Amount Column")
        if missing_idx:
            frappe.throw("Mapping didn't match the header row. Missing/invalid: " + ", ".join(missing_idx))

        created = 0
        skipped = 0

        for r in data_rows:
            if len(r) < len(header_row):
                r = r + [""] * (len(header_row) - len(r))

            try:
                dt = _parse_date(r[date_i]) if date_i is not None else None
            except Exception:
                skipped += 1
                continue

            desc = r[desc_i] if desc_i is not None else ""
            reference = r[ref_i] if ref_i is not None else ""

            if local_has_cd:
                credit = _to_number(r[cr_i]) if cr_i is not None else 0.0
                debit = _to_number(r[dr_i]) if dr_i is not None else 0.0
            else:
                amount = _to_number(r[amt_i]) if amt_i is not None else 0.0
                credit = amount if amount > 0 else 0.0
                debit = -amount if amount < 0 else 0.0

            exists = frappe.db.exists(
                "Bank Transaction",
                {
                    "bank_account": doc.bank_account,
                    "date": dt.date().isoformat() if dt else None,
                    "deposit": round(credit, 2),
                    "withdrawal": round(debit, 2),
                    "description": desc,
                    "reference_number": reference,
                },
            )
            if exists:
                skipped += 1
                continue

            bt = frappe.new_doc("Bank Transaction")
            bt.bank_account = doc.bank_account
            bt.date = dt.date().isoformat() if dt else None
            bt.description = desc
            bt.reference_number = reference
            bt.deposit = round(credit, 2)
            bt.withdrawal = round(debit, 2)
            bt.currency = doc.currency or frappe.get_cached_value("Bank Account", doc.bank_account, "account_currency")
            if bal_i is not None:
                bt.custom_balance = r[bal_i]
            bt.insert(ignore_permissions=True)
            try:
                bt.submit()
            except Exception:
                skipped += 1
                continue
            created += 1

        # Persist generated count (cumulative) on the document if the field exists
        try:
            current = int(doc.get("imported_count") or 0)
            doc.imported_count = current + int(created)
        except Exception:
            pass

        from frappe.utils import now_datetime
        doc.status = "Imported"
        doc.failure_reason = None
        # optional fields if present on the DocType
        if "imported_on" in doc.meta.get_fieldnames():
            doc.imported_on = now_datetime()
        if "lock_mapping_fields" in doc.meta.get_fieldnames():
            doc.lock_mapping_fields = 1
        doc.save(ignore_permissions=True)
        return {"created": created, "skipped": skipped, "total": created + skipped}

    except Exception as e:
        try:
            import traceback
            reason = f"{e.__class__.__name__}: {e}"
            tb = traceback.format_exc()
            doc.status = "Failed"
            doc.failure_reason = f"{reason}\n\n{tb}"
            doc.save(ignore_permissions=True)
        except Exception:
            pass
        raise


@frappe.whitelist(allow_guest=False)
def get_mapping_for_bank_account(bank_account: str):
    """Return mapping fields from the Bank Account's linked Bank Statement Mapping (if any)."""
    if not bank_account:
        return None
    acc = frappe.get_doc("Bank Account", bank_account)
    mapping_name = getattr(acc, "bank_statement_mapping", None) or getattr(acc, "custom_bank_statement_mapping", None)
    if not mapping_name:
        return None
    m = frappe.get_doc("Bank Statement Mapping", mapping_name)
    return {k: m.get(k) for k in _MAP_MAPPING_KEYS()}