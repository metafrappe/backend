"""Seed initial single rows and Tenant Admin permissions for Tenant Settings and Tenant Branding.

Frappe's REST PUT optimistic concurrency check requires a `modified` timestamp.
Seeding missing single rows ensures a freshly installed site returns a `modified`
value on the very first GET without overwriting existing tenant values.

Permissions are granted here (after `panel_roles.ensure`) rather than in the DocType
JSON so Frappe's DocType sync never auto-creates the `Tenant Admin` role with
`desk_access=1` on a fresh site install. Inserting `Custom DocPerm` directly avoids
`setup_custom_perms` adding a default `System Manager` row, keeping both DocTypes
restricted strictly to the `Tenant Admin` role.
"""

import frappe
from frappe.core.doctype.custom_docperm.custom_docperm import update_custom_docperm
from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

from platform_core.shell.doctype.tenant_settings.tenant_settings import (
	DEFAULT_SESSION_EXPIRY,
	SYNCED_FIELDS,
	parse_session_expiry_minutes,
	read_only_email_values,
)

TENANT_ADMIN_ROLE = "Tenant Admin"
TENANT_SETTING_DOCTYPES = ("Tenant Settings", "Tenant Branding")

DEFAULT_SETTINGS = {
	"language": "tr",
	"time_zone": "Europe/Istanbul",
	"date_format": "dd.mm.yyyy",
	"time_format": "HH:mm",
	"number_format": "#.###,##",
	"session_expiry": DEFAULT_SESSION_EXPIRY,
}
DEFAULT_BRANDING = {
	"logo": "",
	"primary_color": "#1F6F5C",
	"accent_color": "#B35C1E",
}


def _clamped_session_expiry(value: object) -> str:
	if isinstance(value, str) and parse_session_expiry_minutes(value) is not None:
		return value
	return DEFAULT_SESSION_EXPIRY


def _ensure_tenant_admin_permissions() -> None:
	"""Grant read and write on both single DocTypes to Tenant Admin only."""
	if not frappe.db.exists("Role", TENANT_ADMIN_ROLE):
		return
	changed = False
	for doctype in TENANT_SETTING_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		row = {"parent": doctype, "role": TENANT_ADMIN_ROLE, "permlevel": 0, "if_owner": 0}
		if not frappe.db.exists("Custom DocPerm", row):
			frappe.get_doc(
				{
					"doctype": "Custom DocPerm",
					"parent": doctype,
					"parenttype": "DocType",
					"parentfield": "permissions",
					"role": TENANT_ADMIN_ROLE,
					"permlevel": 0,
					"if_owner": 0,
					"read": 1,
					"write": 1,
				}
			).insert()
			validate_permissions_for_doctype(doctype)
			changed = True
		else:
			name = frappe.db.get_value("Custom DocPerm", row)
			missing = {
				ptype: 1
				for ptype in ("read", "write")
				if not frappe.db.get_value("Custom DocPerm", name, ptype)
			}
			if missing:
				update_custom_docperm(name, missing)
				changed = True
	if changed:
		frappe.clear_cache()


def ensure() -> None:
	"""Seed missing single records, clamp O-25 expiry and ensure Tenant Admin permissions."""
	_ensure_tenant_admin_permissions()
	if frappe.db.exists("DocType", "Tenant Settings"):
		existing = frappe.db.get_singles_dict("Tenant Settings")
		system_values = frappe.db.get_singles_dict("System Settings")
		if not existing:
			email_domain, email_account = read_only_email_values()
			values = {field: system_values.get(field) or DEFAULT_SETTINGS[field] for field in SYNCED_FIELDS}
			values["session_expiry"] = _clamped_session_expiry(values["session_expiry"])
			values["email_domain"] = email_domain
			values["email_account"] = email_account
			frappe.db.set_single_value("Tenant Settings", values)
		else:
			updates = {}
			for field in SYNCED_FIELDS:
				if field == "session_expiry":
					clamped = _clamped_session_expiry(existing.get(field))
					if existing.get(field) != clamped:
						updates[field] = clamped
				elif not existing.get(field):
					updates[field] = system_values.get(field) or DEFAULT_SETTINGS[field]
			if updates:
				frappe.db.set_single_value("Tenant Settings", updates)

	if frappe.db.exists("DocType", "Tenant Branding") and not frappe.db.get_singles_dict("Tenant Branding"):
		frappe.db.set_single_value("Tenant Branding", DEFAULT_BRANDING)
