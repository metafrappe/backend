"""Manual, permission-checked TCMB import. The request owns the transaction."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import frappe
from frappe import _

from tr_localization.exchange import MAX_BULLETIN_BYTES, parse_rates


def bulletin_today():
    return datetime.now(ZoneInfo("Europe/Istanbul")).date()


def fetch_rates() -> list[dict]:
    import requests

    try:
        with requests.get(
            "https://www.tcmb.gov.tr/kurlar/today.xml", timeout=(3, 10), allow_redirects=False, stream=True
        ) as response:
            if response.status_code != 200:
                frappe.throw(_("The currency bulletin is unavailable."))
            payload = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                payload.extend(chunk)
                if len(payload) > MAX_BULLETIN_BYTES:
                    frappe.throw(_("The currency bulletin is too large."))
        return parse_rates(bytes(payload), today=bulletin_today())
    except (requests.RequestException, ValueError) as error:
        raise frappe.ValidationError(_("The currency bulletin could not be imported.")) from error


@frappe.whitelist(methods=["POST"])
def import_rates() -> dict:
    """Import into the authenticated site's native Currency Exchange records."""
    if frappe.session.user == "Guest":
        frappe.throw(_("Sign in to import exchange rates."), frappe.PermissionError)
    frappe.only_for(("System Manager", "Accounts Manager"))
    if not frappe.has_permission("Currency Exchange", ptype="create"):
        frappe.throw(_("Currency Exchange create permission is required."), frappe.PermissionError)
    rates = fetch_rates()
    pending, unchanged = [], 0
    skipped_currencies = set()
    for rate in rates:
        if not frappe.db.exists("Currency", rate["from_currency"]):
            skipped_currencies.add(rate["from_currency"])
            continue
        filters = {key: value for key, value in rate.items() if key != "exchange_rate"}
        matched = False
        # Native lookups also match a combined Selling-Buying record.
        combined = {**filters, "for_buying": 1, "for_selling": 1}
        for candidate in (filters, combined):
            if not frappe.db.exists("Currency Exchange", candidate):
                continue
            existing = frappe.db.get_value("Currency Exchange", candidate, "exchange_rate")
            if Decimal(str(existing)) != rate["exchange_rate"]:
                frappe.throw(_("An existing exchange rate conflicts with the bulletin."))
            matched = True
        if matched:
            unchanged += 1
        else:
            pending.append(rate)
    for rate in pending:
        # Native autoname provides uniqueness across concurrent imports.
        frappe.get_doc({"doctype": "Currency Exchange", **rate}).insert()
    return {
        "date": rates[0]["date"],
        "inserted": len(pending),
        "unchanged": unchanged,
        "skipped_currencies": sorted(skipped_currencies),
        "skipped_currency_count": len(skipped_currencies),
    }
