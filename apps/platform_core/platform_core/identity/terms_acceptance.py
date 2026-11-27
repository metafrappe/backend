"""Terms acceptance record: terms version and shown language (AJA-1781, AJA-1733).

The record shape is `contracts/terms_acceptance.schema.json` (AJA-1776). The open languages come
from `contracts/locales.json`. This module keeps no language list of its own.

- A new acceptance writes a new `PLT Terms Acceptance` record. An old record is never changed
  or deleted, so it keeps showing the version that the user accepted.
- `shown_locale` is the language of the text on the screen. The account language of the user is a
  separate value and never fills this field.
- The client names the version it showed. A version that is not a published `PLT Terms Version`
  is refused with HTTP 422, and no record is written.
"""

import json
import re
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import frappe
from frappe import _

ACCEPTANCE_DOCTYPE = "PLT Terms Acceptance"
VERSION_DOCTYPE = "PLT Terms Version"
SCHEMA_NAME = "terms_acceptance.schema.json"
LOCALES_NAME = "locales.json"
LOCALE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
FIELDS = ("terms_id", "terms_version", "shown_locale", "user", "accepted_at")


class TermsAcceptanceRefused(frappe.ValidationError):
	"""The acceptance names an unknown text, an unknown version or a closed language."""

	http_status_code = 422


def _contract_path(name: str) -> Path:
	here = Path(__file__).resolve()
	# In the image the contracts sit in the app folder. In the repository they sit at the root.
	for root in (here.parents[2], here.parents[4]):
		candidate = root / "contracts" / name
		if candidate.is_file():
			return candidate
	raise FileNotFoundError(name)


def contract_file() -> Path:
	return _contract_path(SCHEMA_NAME)


@cache
def open_languages() -> frozenset[str]:
	data = json.loads(_contract_path(LOCALES_NAME).read_text(encoding="utf-8"))
	return frozenset(data["open_languages"])


def _text(value: Any) -> str:
	return value.strip() if isinstance(value, str) else ""


def _refuse(message: str) -> None:
	"""Refuse with a message that the caller already translated."""
	frappe.throw(message, TermsAcceptanceRefused)


def publish_version(terms_id: str, terms_version: str):
	"""Publish a version of a binding text. Publishing the same version again returns the old record."""
	values = {"terms_id": _text(terms_id), "terms_version": _text(terms_version)}
	if not values["terms_id"] or not values["terms_version"]:
		_refuse(_("Enter the terms id and the terms version.", context="platform_core.identity"))
	name = frappe.db.exists(VERSION_DOCTYPE, values)
	if name:
		return frappe.get_doc(VERSION_DOCTYPE, name)
	return frappe.get_doc({"doctype": VERSION_DOCTYPE, **values}).insert(ignore_permissions=True)


def accept(terms_id: Any, terms_version: Any, shown_locale: Any, subject: Any):
	"""Write a new acceptance record. Raise TermsAcceptanceRefused for an unknown version or language."""
	terms_id, terms_version, subject = _text(terms_id), _text(terms_version), _text(subject)
	if not subject:
		_refuse(_("The user who accepted the terms is missing.", context="platform_core.identity"))
	if not isinstance(shown_locale, str) or not LOCALE.match(shown_locale):
		_refuse(_("The language of the shown terms is not valid.", context="platform_core.identity"))
	if shown_locale.split("-")[0] not in open_languages():
		_refuse(_("The terms are not offered in this language.", context="platform_core.identity"))
	if not terms_id or not frappe.db.exists(
		VERSION_DOCTYPE, {"terms_id": terms_id, "terms_version": terms_version}
	):
		_refuse(_("This terms version is not published.", context="platform_core.identity"))
	accepted_at = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
	return frappe.get_doc(
		{
			"doctype": ACCEPTANCE_DOCTYPE,
			"terms_id": terms_id,
			"terms_version": terms_version,
			"shown_locale": shown_locale,
			"user": subject,
			"accepted_at": accepted_at,
		}
	).insert(ignore_permissions=True)


def record(name: str) -> dict[str, str]:
	"""An acceptance in the shape of `contracts/terms_acceptance.schema.json`."""
	row = frappe.db.get_value(ACCEPTANCE_DOCTYPE, name, FIELDS, as_dict=True)
	if not row:
		raise frappe.DoesNotExistError(name)
	return {"acceptance_id": name, **{field: row[field] for field in FIELDS}}
