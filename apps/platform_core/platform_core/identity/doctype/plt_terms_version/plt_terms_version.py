"""Terms Version: one published version of a binding text (AJA-1781)."""

import frappe
from frappe import _
from frappe.model.document import Document


class PLTTermsVersion(Document):
	def validate(self) -> None:
		if not self.is_new():
			frappe.throw(
				_("A published terms version cannot be changed.", context="platform_core.identity"),
				frappe.PermissionError,
			)
		if frappe.db.exists(self.doctype, {"terms_id": self.terms_id, "terms_version": self.terms_version}):
			frappe.throw(
				_("This terms version is already published.", context="platform_core.identity"),
				frappe.DuplicateEntryError,
			)

	def on_trash(self) -> None:
		frappe.throw(
			_("A published terms version cannot be deleted.", context="platform_core.identity"),
			frappe.PermissionError,
		)
