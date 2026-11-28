"""Seed initial single rows for Tenant Settings and Tenant Branding on install/migrate.

Frappe's REST PUT optimistic concurrency check requires a `modified` timestamp.
Seeding missing single rows ensures a freshly installed site returns a `modified`
value on the very first GET without overwriting existing tenant values.
"""

import frappe

from platform_core.shell.doctype.tenant_settings.tenant_settings import (
	SYNCED_FIELDS,
	read_only_email_values,
)

DEFAULT_SETTINGS = {
	"language": "tr",
	"time_zone": "Europe/Istanbul",
	"date_format": "dd.mm.yyyy",
	"time_format": "HH:mm",
	"number_format": "#.###,##",
	"session_expiry": "01:00",
}
DEFAULT_BRANDING = {
	"logo": "",
	"primary_color": "#1F6F5C",
	"accent_color": "#B35C1E",
}


def ensure() -> None:
	"""Seed missing single records without touching already saved tenant choices."""
	if frappe.db.exists("DocType", "Tenant Settings") and not frappe.db.get_singles_dict("Tenant Settings"):
		system_values = frappe.db.get_singles_dict("System Settings")
		email_domain, email_account = read_only_email_values()
		values = {field: system_values.get(field) or DEFAULT_SETTINGS[field] for field in SYNCED_FIELDS}
		values["email_domain"] = email_domain
		values["email_account"] = email_account
		frappe.db.set_single_value("Tenant Settings", values)

	if frappe.db.exists("DocType", "Tenant Branding") and not frappe.db.get_singles_dict("Tenant Branding"):
		frappe.db.set_single_value("Tenant Branding", DEFAULT_BRANDING)
