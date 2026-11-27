"""Billing address and tax number check by billing country (AJA-1779, AJA-1733).

The contract is `contracts/billing_identity.schema.json` (AJA-1776). The billing country selects
the address format in its `x-address-formats` part. The interface language never selects it, so
a Turkish address needs a province on an English screen too. This module keeps no format list of
its own: it reads the contract file.

A refused draft gets HTTP 422. `billing_errors` in the response lists each problem with its
field, a code, the translation key and the translated sentence. Every message is one whole
sentence, so no sentence is built from parts.

The tax number check has three results: `valid`, `invalid` and `unavailable`. Only an answer of
the tax service gives `invalid`. When the service is down or not set up, the result is
`unavailable` and the draft is still saved.
"""

import json
import re
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

CONTRACT_NAME = "billing_identity.schema.json"
COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")
CONTEXT = "platform_core.billing_identity"

# One whole English sentence per field. Frappe uses the English source as the translation key.
MESSAGE_KEYS = {
	"party.kind": "Choose whether the billing party is a person or a company.",
	"party.name": "Enter the name or the company title.",
	"billing_address.billing_country": "Choose the billing country.",
	"billing_address.line1": "Enter the street address.",
	"billing_address.district": "Enter the district.",
	"billing_address.province": "Enter the province.",
	"billing_address.city": "Enter the city.",
	"billing_address.region": "Enter the region.",
	"billing_address.postal_code": "Enter the postal code.",
}

TaxIdChecker = Callable[[str, str], bool]


class BillingIdentityError(frappe.ValidationError):
	"""The billing data does not meet the format of its billing country."""

	http_status_code = 422


class TaxIdServiceUnavailableError(Exception):
	"""The tax service did not answer. Nothing is known about the number."""


def contract_file() -> Path:
	here = Path(__file__).resolve()
	# In the image the contract sits in the app folder. In the repository it sits at the root.
	for root in (here.parents[1], here.parents[3]):
		candidate = root / "contracts" / CONTRACT_NAME
		if candidate.is_file():
			return candidate
	raise FileNotFoundError(CONTRACT_NAME)


@cache
def _contract() -> dict[str, Any]:
	return json.loads(contract_file().read_text(encoding="utf-8"))


def address_format(country: str) -> dict[str, list[str]]:
	"""The address format of a billing country. Unknown countries use the default format."""
	formats = _contract()["x-address-formats"]
	return formats.get(country, formats["default"])


def _text(value: Any) -> str:
	return value.strip() if isinstance(value, str) else ""


def _error(field: str, code: str = "required") -> dict[str, str]:
	key = MESSAGE_KEYS[field]
	return {"field": field, "code": code, "message_key": key, "message": _(key, context=CONTEXT)}


def validate(billing: dict[str, Any]) -> dict[str, Any]:
	"""Check the billing data. Return a cleaned copy or raise BillingIdentityError."""
	party = dict(billing.get("party") or {})
	address = dict(billing.get("billing_address") or {})
	errors = []

	if party.get("kind") not in ("person", "company"):
		errors.append(_error("party.kind", "invalid"))
	party["name"] = _text(party.get("name"))
	if not party["name"]:
		errors.append(_error("party.name"))
	party["tax_id"] = _text(party.get("tax_id")) or None

	country = address.get("billing_country")
	if not isinstance(country, str) or not COUNTRY_CODE.match(country):
		errors.append(_error("billing_address.billing_country", "invalid"))
	else:
		for field in address_format(country)["required"]:
			if not _text(address.get(field)):
				errors.append(_error(f"billing_address.{field}"))

	if errors:
		frappe.local.response["billing_errors"] = errors
		frappe.throw(errors[0]["message"], BillingIdentityError)
	return {**billing, "party": party, "billing_address": address}


def check_tax_id(country: str, tax_id: str, checker: TaxIdChecker | None) -> dict[str, str]:
	"""Ask the tax service. A silent or missing service gives `unavailable`, never `invalid`."""
	result = "unavailable"
	if checker is not None:
		try:
			result = "valid" if checker(country, tax_id) else "invalid"
		except Exception:
			# Timeout, network error or a service error: the number is not known to be wrong.
			frappe.log_error(title="Tax number service did not answer")
			result = "unavailable"
	return {"result": result, "checked_at": now_datetime().isoformat(), "billing_country": country}


def save_draft(doctype: str, values: dict[str, Any], billing: dict[str, Any], checker: TaxIdChecker | None):
	"""Save the draft after the address check. Return the record and the tax number check."""
	clean = validate(billing)
	tax_check = None
	if clean["party"]["tax_id"]:
		tax_check = check_tax_id(
			clean["billing_address"]["billing_country"], clean["party"]["tax_id"], checker
		)
		frappe.local.response["tax_id_check"] = tax_check
	doc = frappe.get_doc({**values, "doctype": doctype}).insert()
	return doc, tax_check
