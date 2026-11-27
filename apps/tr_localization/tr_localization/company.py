"""Use ERPNext's verified Turkish chart without changing existing ledgers."""

import frappe
from frappe import _

# ERPNext v16.55.0 verified/tr_chart_of_accounts.json supplies these tax leaves.
TAX_ACCOUNTS = {20: "04", 10: "05", 1: "03"}


def install_tax_templates(doc, method=None) -> None:
    """Add only missing templates after native Company.on_update creates accounts."""
    if doc.country != "Türkiye" or doc.get("chart_of_accounts") != "Turkey - Chart of Accounts":
        return
    missing = []
    for rate in TAX_ACCOUNTS:
        for doctype, prefix in (
            ("Sales Taxes and Charges Template", "391"),
            ("Purchase Taxes and Charges Template", "191"),
            ("Item Tax Template", None),
        ):
            if not frappe.db.exists(doctype, {"company": doc.name, "title": f"TRL VAT {rate}"}):
                missing.append((doctype, prefix, rate))
    if not missing:
        return
    required = set()
    for _doctype, prefix, rate in missing:
        required.update(
            (account_prefix, rate) for account_prefix in ((prefix,) if prefix else ("191", "391"))
        )
    accounts = {}
    for prefix, rate in sorted(required):
        account = frappe.db.get_value(
            "Account",
            {
                "company": doc.name,
                "account_number": f"{prefix}.01.{TAX_ACCOUNTS[rate]}",
                "is_group": 0,
                "account_type": "Tax",
                "disabled": 0,
            },
        )
        if not account:
            frappe.throw(_("The Turkish chart tax accounts must exist before installing tax templates."))
        accounts[prefix, rate] = account
    # Resolve all required accounts before inserting any template.
    for doctype, prefix, rate in missing:
        template = {"doctype": doctype, "company": doc.name, "title": f"TRL VAT {rate}"}
        if prefix:
            row = {
                "charge_type": "On Net Total",
                "account_head": accounts[prefix, rate],
                "description": _("VAT {0}%").format(rate),
                "rate": rate,
            }
            if prefix == "191":
                row.update(category="Total", add_deduct_tax="Add")
            template.update(is_default=0, taxes=[row])
        else:
            template["taxes"] = [
                {"tax_type": accounts[account_prefix, rate], "tax_rate": rate}
                for account_prefix in ("191", "391")
            ]
        frappe.get_doc(template).insert()
