"""G-97: field labels and hidden flags of the panel's customization page (AJA-2516, AJA-2533).

A “Property Setter” record changes one property of a field. The same type also sets the permission
level of a field. hrms_tr keeps `Employee.date_of_birth` at level 1 (`04_property_setter.json`).
Level 0 would open personal data to every employee of the tenant. So no role but the trusted
callers writes the type in general (`guard_property_setter`). The three functions below change only
the `label` and `hidden` properties of a field and write every other value of the record themselves.

A system field does not change. The caller gets 403. Hiding a field is not a security setting:
the server still reads a hidden field.
"""

import json
from pathlib import Path

import frappe
from frappe import _
from frappe.model import child_table_fields, default_fields
from frappe.utils import cint

from platform_core.access import tenant_admin

# The only properties the endpoints change, with the Frappe type of their value.
PROPERTIES = {"label": "Data", "hidden": "Check"}
# Frappe's own columns. They are not fields of the type's form.
SYSTEM_COLUMNS = frozenset({*default_fields, *child_table_fields, "amended_from", "naming_series"})
LABEL_LENGTH = 140


def guard_property_setter(doc, method=None, *args, **kwargs) -> None:
	"""Closes every path but the endpoints below: the REST API, data import and AI writes too.

	One delete passes: Frappe deletes the settings of a tenant field when the field is deleted
	(`CustomField.on_trash`). `guard_custom_field` checks that delete. The REST API never reaches
	this case: the type gives no role a delete right.
	"""
	if tenant_admin._trusted() or frappe.flags.platform_customization_write:
		return
	if method == "on_trash" and _tenant_field(doc.doc_type, doc.field_name):
		return
	tenant_admin._deny(_("Only a System Manager can change field properties."))


def _tenant_field(doctype: str, fieldname: str | None) -> bool:
	"""A field the tenant added on a business type, not an application field."""
	if not fieldname or not tenant_admin.grantable_type(doctype):
		return False
	# The flag of the type's own custom field is system data (exception to G-3).
	flag = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "is_system_generated")
	return flag is not None and not flag


def fixture_keys() -> frozenset[tuple[str, str, str]]:
	"""(type, field, property) of every “Property Setter” in the fixture files of the installed apps."""
	keys = set()
	for app in frappe.get_installed_apps():
		folder = Path(frappe.get_app_path(app, "fixtures"))
		if not folder.is_dir():
			continue
		for path in sorted(folder.glob("*.json")):
			try:
				rows = json.loads(path.read_text(encoding="utf-8"))
			except (OSError, ValueError):
				continue
			if not isinstance(rows, list):
				continue
			for row in rows:
				if isinstance(row, dict) and row.get("doctype") == "Property Setter":
					keys.add((row.get("doc_type"), row.get("field_name"), row.get("property")))
	return frozenset(keys)


def _require_type(doctype: str) -> None:
	if not doctype or not frappe.db.exists("DocType", doctype):
		frappe.throw(_("Document type {0} not found.").format(doctype), frappe.DoesNotExistError)
	if not tenant_admin._trusted() and not tenant_admin.grantable_type(doctype):
		tenant_admin._deny(_("Only a System Manager can customize {0}.").format(doctype))


def _require_property(prop: str) -> None:
	if prop not in PROPERTIES:
		tenant_admin._deny(_("Only the label and the hidden flag of a field can change here."))


def _application_field(doctype: str, fieldname: str) -> bool:
	# The flag of the type's own custom field is system data (exception to G-3).
	return bool(
		frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "is_system_generated")
	)


def _system_field(doctype: str, df) -> bool:
	"""A field no property of which changes: a required field or a field an application added."""
	return bool(df.reqd) or (bool(df.get("is_custom_field")) and _application_field(doctype, df.fieldname))


def _hidden_locked(doctype: str, df) -> bool:
	"""A field above level 0 keeps its hidden flag. Its label may change."""
	return _system_field(doctype, df) or cint(df.permlevel) > 0


def _require_open_field(doctype: str, fieldname: str, prop: str):
	"""The field's definition, or 403 for a system field and for a record an application wrote."""
	if fieldname in SYSTEM_COLUMNS:
		tenant_admin._deny(_("The field {0} is a system field.").format(fieldname))
	df = frappe.get_meta(doctype).get_field(fieldname)
	if df is None:
		frappe.throw(_("Field {0} not found in {1}.").format(fieldname, doctype), frappe.DoesNotExistError)
	locked = _hidden_locked(doctype, df) if prop == "hidden" else _system_field(doctype, df)
	if locked or (doctype, fieldname, prop) in fixture_keys():
		tenant_admin._deny(_("The field {0} is a system field.").format(fieldname))
	return df


def _value(prop: str, value) -> str:
	if prop == "label":
		label = value.strip() if isinstance(value, str) else ""
		if not label or len(label) > LABEL_LENGTH:
			frappe.throw(_("The label must have from 1 to {0} characters.").format(LABEL_LENGTH))
		return label
	if isinstance(value, bool):
		return "1" if value else "0"
	if value in (0, 1, "0", "1"):
		return str(value)
	frappe.throw(_("The hidden flag must be 0 or 1."))


def _setter_name(doctype: str, fieldname: str, prop: str) -> str | None:
	# The endpoint reads the one record it changes (exception to G-3).
	return frappe.db.get_value(
		"Property Setter",
		{"doctype_or_field": "DocField", "doc_type": doctype, "field_name": fieldname, "property": prop},
	)


def _write(callback) -> None:
	"""Runs one write of these endpoints past `guard_property_setter`."""
	frappe.flags.platform_customization_write = True
	try:
		callback()
	finally:
		frappe.flags.platform_customization_write = False


def list_field_properties(doctype: str) -> dict:
	"""The label and hidden records of a type, and which fields stay as they are."""
	tenant_admin.require_manager()
	_require_type(doctype)
	locked = fixture_keys()
	# Only the two properties are read. A `permlevel` record is never returned (exception to G-3).
	rows = frappe.get_all(
		"Property Setter",
		filters={"doc_type": doctype, "doctype_or_field": "DocField", "property": ("in", list(PROPERTIES))},
		fields=["field_name", "property", "value"],
		order_by="field_name asc, property asc",
		limit=0,
	)
	properties = [
		{
			"fieldname": row.field_name,
			"property": row.property,
			"value": row.value,
			"locked": (doctype, row.field_name, row.property) in locked,
		}
		for row in rows
	]
	fields = [
		{
			"fieldname": df.fieldname,
			"label": df.label,
			"fieldtype": df.fieldtype,
			"system": _system_field(doctype, df),
			"hidden_locked": _hidden_locked(doctype, df),
		}
		for df in frappe.get_meta(doctype).fields
		if df.fieldname
	]
	return {"doctype": doctype, "properties": properties, "fields": fields}


def set_field_property(doctype: str, fieldname: str, prop: str, value) -> dict:
	"""Adds or changes the label or the hidden flag of a field."""
	tenant_admin.require_manager()
	_require_property(prop)
	_require_type(doctype)
	_require_open_field(doctype, fieldname, prop)
	stored = _value(prop, value)
	doc = frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": doctype,
			"field_name": fieldname,
			"property": prop,
			"value": stored,
			"property_type": PROPERTIES[prop],
			"is_system_generated": 0,
		}
	)
	doc.flags.validate_fields_for_doctype = True
	# The caller's right was checked above. `PropertySetter.validate` deletes the old record.
	_write(lambda: doc.insert(ignore_permissions=True))
	frappe.clear_cache(doctype=doctype)
	return {"doctype": doctype, "fieldname": fieldname, "property": prop, "value": stored}


def remove_field_property(doctype: str, fieldname: str, prop: str) -> dict:
	"""Deletes the label or hidden record of a field. The field shows its standard value again."""
	tenant_admin.require_manager()
	_require_property(prop)
	_require_type(doctype)
	_require_open_field(doctype, fieldname, prop)
	name = _setter_name(doctype, fieldname, prop)
	if not name:
		frappe.throw(_("The field has no such setting."), frappe.DoesNotExistError)
	# The caller's right was checked above.
	_write(lambda: frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True))
	frappe.clear_cache(doctype=doctype)
	return {"doctype": doctype, "fieldname": fieldname, "property": prop}
