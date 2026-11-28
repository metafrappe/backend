"""G-97 customization endpoints. The business rule is in `platform_core.access.customization`.

Contract: `contracts/platform_core-customization.openapi.yaml`.
"""

import frappe

from platform_core.access import customization


@frappe.whitelist(methods=["GET"])
def list_field_properties(doctype: str) -> dict:
	"""The label and hidden records of a type. “System Manager” and “Tenant Admin” only."""
	return customization.list_field_properties(doctype)


@frappe.whitelist(methods=["POST"])
def set_field_property(doctype: str, fieldname: str, property: str, value: object = None) -> dict:  # noqa: A002
	"""Adds or changes the label or the hidden flag of a field. Same callers as the list."""
	return customization.set_field_property(doctype, fieldname, property, value)


@frappe.whitelist(methods=["POST"])
def remove_field_property(doctype: str, fieldname: str, property: str) -> dict:  # noqa: A002
	"""Deletes the label or hidden record of a field. Same callers as the list."""
	return customization.remove_field_property(doctype, fieldname, property)
