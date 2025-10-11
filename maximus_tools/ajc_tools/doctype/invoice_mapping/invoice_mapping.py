# Copyright (c) 2025, Cloud Nine Technologies (CNT) and contributors
# For license information, please see license.txt

from __future__ import annotations

import re
from typing import List, Dict, Optional, Tuple

import frappe
from frappe import _
from frappe.model.document import Document


class InvoiceMapping(Document):
    """Configuration for parsing supplier invoice PDFs using child rules."""

    def validate(self):
        # Require Supplier
        if not getattr(self, "supplier", None):
            raise frappe.ValidationError(_("Supplier is required."))

        # Normalize priority
        try:
            self.priority = int(self.priority or 10)
        except Exception:
            self.priority = 10

        # Tidy keywords
        self.keywords = (self.keywords or "").strip()

        # Soft guard: warn (don't block) if another active mapping at same priority exists
        if getattr(self, "active", 0):
            dup = frappe.get_all(
                "Invoice Mapping",
                filters={
                    "name": ["!=", self.name] if self.name else ["!=", ""],
                    "supplier": self.supplier,
                    "active": 1,
                    "priority": self.priority,
                },
                fields=["name"],
                limit=1,
            )
            if dup:
                frappe.msgprint(
                    _(
                        "Another active mapping for supplier {0} with priority {1} exists: {2}. "
                        "Consider changing priority."
                    ).format(self.supplier, self.priority, dup[0]["name"]),
                    alert=True,
                )

    # -----------------------------
    # Utilities used by the engine
    # -----------------------------
    def keywords_list(self) -> List[str]:
        """Return normalized keyword tokens (lowercase), comma or newline separated in the field."""
        text = (self.keywords or "").replace(",", "\n")
        toks = [t.strip().lower() for t in text.splitlines() if t.strip()]
        seen, out = set(), []
        for t in toks:
            if t not in seen:
                out.append(t)
                seen.add(t)
        return out

    def rules_for_engine(self) -> List[Dict]:
        """
        Export child rule rows into a list the parsing engine can apply.
        Each child (Invoice Mapping Rule) should implement `as_engine_rule()`.
        """
        rules = []
        for r in getattr(self, "rules", []) or []:
            if hasattr(r, "as_engine_rule"):
                rules.append(r.as_engine_rule())
            else:
                # Back-compat: minimal export if method helpers are not present on the child DocType class
                field_key = (getattr(r, "field", "") or "").strip().lower().replace(" ", "_")
                rules.append({
                    "field": field_key,
                    "pattern": getattr(r, "pattern", "") or "",
                    "flags": re.I,
                    "group_index": int(getattr(r, "group_index", 1) or 1),
                    "required": int(getattr(r, "required", 0) or 0),
                    "postprocess": getattr(r, "postprocess", None),
                    "page_scope": getattr(r, "page_scope", None),
                    # diagnostics
                    "method": getattr(r, "method", None),
                    "label": getattr(r, "label", None),
                })
        return rules


# -----------------------------
# Helper: Select the best mapping
# -----------------------------
def select_invoice_mapping(supplier_hint: Optional[str], full_text: str) -> Optional[InvoiceMapping]:
    """
    Pick the best active Invoice Mapping given an optional supplier hint and the PDF full text.
    Selection order:
      1) Exact supplier match among active mappings (lowest priority wins)
      2) Otherwise, auto-detect by keyword hits (most hits, then lowest priority)
    """
    full_text_lc = (full_text or "").lower()

    # 1) Prefer explicit supplier match
    if supplier_hint:
        recs = frappe.get_all(
            "Invoice Mapping",
            filters={"active": 1, "supplier": supplier_hint},
            fields=["name", "priority"],
            order_by="priority asc, modified desc",
        )
        if recs:
            return frappe.get_doc("Invoice Mapping", recs[0]["name"])

    # 2) Keyword auto-detect among all active mappings
    recs = frappe.get_all(
        "Invoice Mapping",
        filters={"active": 1},
        fields=["name", "priority", "keywords"],
    )
    scored: List[Tuple[int, int, str]] = []  # (hits, -priority, name)
    for r in recs:
        kw_text = (r.get("keywords") or "").replace(",", "\n")
        kws = [t.strip().lower() for t in kw_text.splitlines() if t.strip()]
        if not kws:
            continue
        hits = sum(1 for k in kws if k and k in full_text_lc)
        if hits:
            scored.append((hits, -int(r.get("priority") or 10), r["name"]))

    if not scored:
        return None

    # Sort by most hits, then lowest priority (highest -priority), then name
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return frappe.get_doc("Invoice Mapping", scored[0][2])