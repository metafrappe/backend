"""Versioned edits: a stale version cannot overwrite a newer record (G-125).

The contract is `contracts/idempotency.md`, section 7. The client sends the record's `modified`
value as `version`. The server locks the record and compares the two values. A stale version
changes nothing and gets HTTP 409 with `VersionConflictError`.
"""

from typing import Any

import frappe
from frappe import _


class VersionConflictError(frappe.TimestampMismatchError):
	"""The record changed after the client read it."""

	http_status_code = 409


def check_version(doc, version: str, message: str | None = None) -> None:
	"""Refuse a stale version. The caller locks and permission-checks the record first.

	The reply carries the latest version, so the client can reload the record and show the conflict.
	"""
	current = str(doc.modified)
	if version == current:
		return
	frappe.local.response["conflict"] = {
		"code": VersionConflictError.__name__,
		"doctype": doc.doctype,
		"name": doc.name,
		"current_version": current,
	}
	frappe.throw(
		message or _("This record changed after you opened it.", context="platform_core.version_check"),
		VersionConflictError,
	)


def update_with_version(doctype: str, name: str, version: str, values: dict[str, Any]) -> dict[str, str]:
	"""Change the fields of a record only when the client read its latest version."""
	doc = frappe.get_doc(doctype, name, for_update=True)
	doc.check_permission("write")
	check_version(doc, version)
	doc.update(values)
	doc.save()
	return {"name": doc.name, "version": str(doc.modified)}
