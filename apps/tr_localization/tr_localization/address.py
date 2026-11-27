"""Validate Turkish address data using an operator-reviewed district catalogue."""

import re

import frappe
from frappe import _


def validate_address(doc, method=None) -> None:
    """Keep native Address permissions and reject mismatched province/district data."""
    if doc.country != "Türkiye":
        return
    if frappe.conf.get("trl_address_catalogue_ready") is True and not frappe.db.exists(
        "TRL District",
        {
            "province": doc.get("state"),
            "district": doc.get("custom_trl_district"),
            "enabled": 1,
        },
    ):
        frappe.throw(_("Select a province and district from the installed district catalogue."))
    for field, length in (("custom_trl_tax_id", 10), ("custom_trl_identity_number", 11)):
        value = doc.get(field)
        if value and (not isinstance(value, str) or not re.fullmatch(rf"[0-9]{{{length}}}", value)):
            frappe.throw(_("Tax and identity numbers must contain the required number of ASCII digits."))
