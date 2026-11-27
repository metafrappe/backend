"""Functions bound to the permission hooks of Frappe.

The `hooks.py` file binds these functions to all document types with the `"*"` key.
In Frappe 16, access is denied if the `has_permission` hook returns `None`
(`frappe/permissions.py:497`). So the function always returns `True` or `False`.
"""

import frappe

from platform_core.access import engine, reports, rules


def has_permission(doc, ptype: str | None = None, user: str | None = None, debug: bool = False) -> bool:
	"""The single record hook. The engine only narrows: `True` does not grant permission, the role permission is checked separately."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	if doc.doctype == reports.PREPARED_REPORT:
		# Prepared Report is switched off for reports that touch governed data.
		return not reports.touches_governed(doc.report_name)
	if doc.doctype == engine.FILE:
		attached = doc.get("attached_to_doctype")
		if attached == reports.PREPARED_REPORT:
			return not reports.prepared_report_closed(doc.get("attached_to_name"))
		if not attachment_visible(doc, ptype, user):
			return False
	if not rules.is_governed(doc.doctype):
		return True
	return engine.decide(doc, ptype, user)


def attachment_visible(file, ptype: str | None, user: str) -> bool:
	"""An attachment of a governed record is read only by the record's readers (G-121).

	Frappe lets anyone read a public file record, and the owner read a private one
	(`frappe/core/doctype/file/file.py:1088`). The file record names the record it belongs to.
	Writing and deleting already ask the record through Frappe (`file.py:1120`).
	"""
	attached = file.get("attached_to_doctype")
	if not attached or not rules.is_governed(attached) or rules.operation_of(ptype) != "read":
		return True
	return engine.stored_record_visible(attached, file.get("attached_to_name"), user)


def query_conditions(user: str | None = None, doctype: str | None = None):
	"""The list hook. Adds no condition for a document type that is not governed."""
	user = user or frappe.session.user
	if user == "Administrator" or not doctype:
		return None
	criterion = engine.list_criterion(doctype, user)
	if doctype == engine.FILE:
		attachments = engine.attachment_criterion(user)
		if attachments is not None:
			criterion = attachments if criterion is None else criterion & attachments
	return criterion
