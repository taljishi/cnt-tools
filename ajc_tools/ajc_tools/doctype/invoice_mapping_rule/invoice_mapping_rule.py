# Copyright (c) 2025, Cloud Nine Technologies (CNT) and contributors
# For license information, please see license.txt

from __future__ import annotations

import re
from typing import Dict, Tuple, Optional

import frappe
from frappe import _
from frappe.model.document import Document

"""
Invoice Mapping Rule
--------------------
Supports user-friendly rule configuration for parsing invoice PDFs.

UI fields expected on this DocType:
  - field    (Select): e.g., "Bill No", "Bill Date", "Due Date", "Amount", "Bill Profile", "Account Number", "VAT Amount"
  - method   (Select): "Regex", "Next Number", "Next Date", "Amount After"
  - pattern  (Code)  : regex pattern (used when method == "Regex")
  - label    (Data)  : anchor label text (used for non-Regex methods)
  - group_index (Int, default 1)
  - required (Check)
  - postprocess (Select): "", "strip", "date", "amount"
  - page_scope (Data): "all" (default), "1", "last"
"""

# Map UI "Field" options to engine field keys
FIELD_MAP: Dict[str, str] = {
    "Bill No": "bill_no",
    "Bill Date": "bill_date",
    "Due Date": "due_date",
    "Amount": "amount",
    # Optional extras you may have added to the Field Select:
    "Bill Profile": "bill_profile",
    "Account Number": "account_no",
    "VAT Amount": "vat_amount",
}

# Exact strings as configured in the "Method" Select options
SUPPORTED_METHODS = {"Regex", "Next Number", "Next Date", "Amount After"}


class InvoiceMappingRule(Document):
    # -----------------------------
    # Validation
    # -----------------------------
    def validate(self):
        m = (getattr(self, "method", "") or "").strip()
        if m not in SUPPORTED_METHODS:
            raise frappe.ValidationError(_("Unsupported method: {0}").format(m or "<empty>"))

        f = (getattr(self, "field", "") or "").strip()
        if not f:
            raise frappe.ValidationError(_("Field is required."))

        if m == "Regex":
            if not (getattr(self, "pattern", "") or "").strip():
                raise frappe.ValidationError(_("Regex Pattern is required when Method is 'Regex'."))
        else:
            if not (getattr(self, "label", "") or "").strip():
                raise frappe.ValidationError(_("Label Text is required when Method is '{0}'.").format(m))

        # Normalize group index
        try:
            self.group_index = int(self.group_index or 1)
        except Exception:
            self.group_index = 1

    # -----------------------------
    # Field normalization
    # -----------------------------
    def get_field_key(self) -> str:
        """Return normalized target field key (e.g., 'bill_no'). Falls back to snake-case."""
        ui = (getattr(self, "field", "") or "").strip()
        mapped = FIELD_MAP.get(ui)
        if mapped:
            return mapped.strip()
        return ui.lower().replace(" ", "_")

    # -----------------------------
    # Build an effective regex from the rule
    # -----------------------------
    def get_effective_regex(self) -> Tuple[str, int, int]:
        """
        Returns (pattern, flags, group_index):
          - pattern: regex pattern string
          - flags: Python re flags (we use re.I by default)
          - group_index: which capture group to extract
        """
        flags = re.I
        group_index = int(getattr(self, "group_index", 1) or 1)

        method = (getattr(self, "method", "") or "").strip()
        if method == "Regex":
            return (self.pattern or ""), flags, group_index

        # For label-based methods, build a tolerant pattern:
        # - Escape label, but treat spaces flexibly (\s+)
        # - Allow punctuation (.:–—-) between label and value
        label = (getattr(self, "label", "") or "").strip()
        if not label:
            raise frappe.ValidationError(_("Label Text is required for non-Regex methods."))

        esc_label = re.escape(label).replace(r"\ ", r"\s+")

        if method == "Next Number":
            # Accept digits with optional separators (comma, dot, dash, slash)
            pattern = rf"{esc_label}\s*[\.:\-–—]?\s*([0-9][0-9,\.\-\/]*)"
            return pattern, flags, 1

        if method == "Next Date":
            # Common date formats: "12 Apr 2025", "12/04/2025", "2025-04-12"
            dd_mmm_yyyy = r"[0-9]{1,2}\s+[A-Za-z]{3,}\s+[0-9]{2,4}"
            dd_mm_yyyy  = r"[0-9]{1,2}[\/\-][0-9]{1,2}[\/\-][0-9]{2,4}"
            yyyy_mm_dd  = r"[0-9]{4}[\/\-][0-9]{1,2}[\/\-][0-9]{1,2}"
            pattern = rf"{esc_label}\s*[\.:\-–—]?\s*({dd_mmm_yyyy}|{dd_mm_yyyy}|{yyyy_mm_dd})"
            return pattern, flags, 1

        if method == "Amount After":
            # Accept "1,234.500" or "15.400" (with optional parentheses text like "(BD)")
            amount = r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,3})?|[0-9]+(?:\.[0-9]{1,3})?)"
            pattern = rf"{esc_label}\s*[\.:\-–—]?\s*(?:\(.*?\))?\s*{amount}"
            return pattern, flags, 1

        # Should never reach here due to validate()
        raise frappe.ValidationError(_("Unsupported method: {0}").format(method))

    # -----------------------------
    # Export for the engine
    # -----------------------------
    def as_engine_rule(self) -> Dict[str, object]:
        """
        Export a dict the parsing engine understands:
          {
            'field': 'bill_no',
            'pattern': '...',
            'flags': re.I,
            'group_index': 1,
            'required': 1/0,
            'postprocess': 'date'/'amount'/'strip'/None,
            'page_scope': 'all'/'1'/'last'/None,
            'method': 'Next Number'/'Regex'/...,
            'label': 'Bill No'
          }
        """
        pattern, flags, group = self.get_effective_regex()
        return {
            "field": self.get_field_key(),
            "pattern": pattern,
            "flags": flags,
            "group_index": group,
            "required": int(getattr(self, "required", 0) or 0),
            "postprocess": (getattr(self, "postprocess", None) or None),
            "page_scope": (getattr(self, "page_scope", None) or None),
            # diagnostics (optional, helpful in logs)
            "method": (getattr(self, "method", None) or None),
            "label": (getattr(self, "label", None) or None),
        }