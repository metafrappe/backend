"""Register the native Press localisation relation after marketplace setup."""

import frappe
from frappe import _


def register_localization() -> bool:
	"""Do not create marketplace sources or release groups with guessed settings."""
	if not all(frappe.db.exists("Marketplace App", app) for app in ("erpnext", "tr_localization")):
		return False
	app = frappe.get_doc("Marketplace App", "erpnext")
	for row in app.localisation_apps:
		if row.country == "Türkiye":
			if row.marketplace_app != "tr_localization":
				frappe.throw(_("Turkey already has a different localization app."))
			return True
	app.append("localisation_apps", {"country": "Türkiye", "marketplace_app": "tr_localization"})
	app.save()
	return True
