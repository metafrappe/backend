"""Apply the tenant localization defaults required by G-41."""

import frappe
from frappe.core.doctype.system_settings.system_settings import clear_system_settings_cache
from frappe.translate import set_default_language

SYSTEM_SETTINGS = {
	"country": "Türkiye",
	"language": "tr",
	"time_zone": "Europe/Istanbul",
	"currency": "TRY",
	"number_format": "#.###,##",
	"date_format": "dd.mm.yyyy",
	"time_format": "HH:mm",
	"first_day_of_the_week": "Monday",
	"float_precision": "2",
	"currency_precision": "2",
	# Product decision, 24 November 2026: half values round up. Change it here only.
	"rounding_method": "Commercial Rounding",
}
# Accounts, Selling and Buying Settings keep the ERPNext defaults on purpose.

# G-48: upload security. These are System Settings fields, not user defaults.
UPLOAD_SECURITY = {
	"max_file_size": 25,  # MB
	"strip_exif_metadata_from_uploaded_images": 1,
	"allow_guests_to_upload_files": 0,
	"only_allow_system_managers_to_upload_public_files": 1,
}
# Orchestrator decision, 25 November 2026 (AJA-701). Change the list here only.
# xml is allowed for e-invoice and e-archive files. svg, html, htm, js and executables
# stay out because they can run code in the browser. An empty list keeps the site value.
ALLOWED_FILE_EXTENSIONS: tuple[str, ...] = (
	"pdf", "jpg", "jpeg", "png", "webp", "gif", "heic", "csv", "txt",
	"xlsx", "xls", "ods", "docx", "doc", "odt", "pptx", "xml", "zip",
)  # fmt: skip


def apply(_wizard_args=None) -> None:
	"""Apply defaults after the wizard and after migrations."""
	system_settings = SYSTEM_SETTINGS | UPLOAD_SECURITY | _extension_settings() | _brand_settings()
	if _update_settings("System Settings", system_settings):
		clear_system_settings_cache()

	for key, value in SYSTEM_SETTINGS.items():
		if frappe.db.get_default(key) != value:
			frappe.db.set_default(key, value)
	if frappe.db.get_default("lang") != SYSTEM_SETTINGS["language"]:
		set_default_language(SYSTEM_SETTINGS["language"])

	if "erpnext" in frappe.get_installed_apps():
		currency = SYSTEM_SETTINGS["currency"]
		_update_settings(
			"Global Defaults", {"country": SYSTEM_SETTINGS["country"], "default_currency": currency}
		)
		if not frappe.db.get_value("Currency", currency, "enabled"):
			frappe.db.set_value("Currency", currency, "enabled", 1)


def _extension_settings() -> dict[str, str]:
	"""Write the whitelist in the form Frappe compares: one upper-case extension per line."""
	extensions = [ext.strip().lstrip(".").upper() for ext in ALLOWED_FILE_EXTENSIONS if ext.strip()]
	return {"allowed_file_extensions": "\n".join(extensions)} if extensions else {}


def _brand_settings() -> dict[str, str]:
	"""Show the tenant brand from the existing identity setting; never invent one."""
	brand = (frappe.conf.get("identity_brand_name") or "").strip()
	return {"app_name": brand} if brand else {}


def _update_settings(doctype: str, defaults: dict[str, str | int]) -> bool:
	settings = frappe.get_single(doctype)
	changes = {field: value for field, value in defaults.items() if settings.get(field) != value}
	if not changes:
		return False

	# A full save can rewrite unrelated security settings and ERPNext print property setters.
	frappe.db.set_single_value(doctype, changes)
	return True
