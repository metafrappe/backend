"""AJA-197: close generic financial writes without intercepting Press's internal billing."""

import json

import frappe
from frappe import _

from press_tr.press_identity import operators

FINANCIAL_DOCTYPES = frozenset({"Invoice", "Balance Transaction"})
READ_METHODS = frozenset(
	{
		"get",
		"get_doc",
		"get_list",
		"get_count",
		"get_value",
		"get_single_value",
		"get_meta",
		"get_doc_permissions",
		"has_permission",
		"get_permission",
		"document_list",
		"count",
		"copy_doc",
		"get_import_status",
		"get_import_log_count",
		"get_import_logs",
		"get_import_fields",
		"download_template",
		"get_users",
		"get_shared",
	}
)
DOCUMENT_KEYS = frozenset({"doctype", "dt", "parenttype", "reference_doctype", "attached_to_doctype"})
PAYLOAD_KEYS = frozenset({"doc", "docs", "document", "data", "args"})
MAX_DOCUMENT_DEPTH = 16
# AJA-201: the dashboard opens an invoice's payment link through this read-only method.
PAYMENT_LINK = {"dt": "Invoice", "method": "stripe_payment_url"}


def deny() -> None:
	frappe.throw(
		_("Financial changes require a billing operator.", context="press_tr"), frappe.PermissionError
	)


def document_types(payload, depth: int = 0) -> set[str]:
	if depth > MAX_DOCUMENT_DEPTH:
		deny()
	if isinstance(payload, str):
		if not payload.lstrip().startswith(("{", "[")):
			return set()
		try:
			payload = json.loads(payload)
		except (ValueError, RecursionError):
			deny()
	if isinstance(payload, list):
		found = set()
		for row in payload:
			found.update(document_types(row, depth + 1))
		return found
	if not isinstance(payload, dict):
		return set()
	found = {payload[key] for key in DOCUMENT_KEYS if isinstance(payload.get(key), str)}
	if payload.get("doctype", payload.get("dt")) == "File":
		names = []
		for key in ("name", "docname", "dn", "old_name"):
			if key in payload:
				if not isinstance(payload[key], str):
					deny()
				names.append(payload[key])
		for key in ("names", "docnames", "items"):
			batch = payload.get(key, [])
			if isinstance(batch, str):
				try:
					batch = json.loads(batch)
				except (ValueError, RecursionError):
					deny()
			if not isinstance(batch, list) or any(not isinstance(name, str) for name in batch):
				deny()
			names.extend(batch)
		if names:
			# File privacy/URL changes can write the attached field through db.set_value.
			# Resolve the old server-side attachment even if the request claims another parent.
			parent = frappe.db.get_value(
				"File",
				{"name": ["in", names], "attached_to_doctype": ["in", sorted(FINANCIAL_DOCTYPES)]},
				"attached_to_doctype",
			)
			if isinstance(parent, str):
				found.add(parent)
	for key in PAYLOAD_KEYS:
		if payload.get(key) is not None:
			found.update(document_types(payload[key], depth + 1))
	return found


def is_payment_link(arguments, payload) -> bool:
	sources = [source for source in (arguments, payload) if isinstance(source, dict)]
	for key, expected in PAYMENT_LINK.items():
		values = [source[key] for source in sources if key in source]
		if not values or any(value != expected for value in values):
			return False
	if any(source.get("args") for source in sources):
		return False
	return document_types(arguments or {}) | document_types(payload) == {"Invoice"}


def guard_request() -> None:
	# request_policy resolves the actual callable, including overrides and v1/v2 route aliases.
	resolved = getattr(frappe.local, "press_request_target", None)
	if resolved is None:
		return
	target, arguments = resolved
	module = getattr(target, "__module__", "")
	name = getattr(target, "__name__", "")
	if not module.startswith("frappe.") and module != "press.api.client":
		return
	payload = frappe.form_dict
	if name in READ_METHODS:
		return
	if name == "read_doc" and not payload.get("run_method"):
		return
	# Press checks invoice ownership; this exception covers no other method or document.
	if module == "press.api.client" and name == "run_doc_method" and is_payment_link(arguments, payload):
		return
	# Other handler entry points are unrelated to arbitrary document writes.
	if module == "frappe.handler" and name not in {"run_doc_method", "upload_file"}:
		return
	doctypes = document_types(arguments or {}) | document_types(payload)
	if module == "frappe.core.doctype.data_import.data_import":
		import_name = payload.get("data_import") or payload.get("data_import_name") or payload.get("doc_name")
		if isinstance(import_name, str):
			reference = frappe.db.get_value("Data Import", import_name, "reference_doctype")
			if isinstance(reference, str):
				doctypes.add(reference)
	protected = bool(doctypes & FINANCIAL_DOCTYPES)
	for doctype in doctypes - FINANCIAL_DOCTYPES:
		if frappe.get_meta(doctype).istable and frappe.db.exists(
			"DocField",
			{
				"parent": ["in", sorted(FINANCIAL_DOCTYPES)],
				"options": doctype,
				"fieldtype": ["in", ["Table", "Table MultiSelect"]],
			},
		):
			protected = True
	if not protected:
		return
	user = frappe.session.user
	if user in operators.service_users() or user not in operators.accounts():
		deny()
	if "Press Ops Billing" not in frappe.get_roles(user):
		deny()
	operators.guard_request()
	operators.audit("financial_request")
