"""Terms Acceptance: the append-only record of a terms acceptance (AJA-1781)."""

import frappe
from frappe import _
from frappe.model.document import Document


class PLTTermsAcceptance(Document):
	def validate(self) -> None:
		if not self.is_new():
			frappe.throw(
				_("A terms acceptance cannot be changed.", context="platform_core.identity"),
				frappe.PermissionError,
			)

	def on_trash(self) -> None:
		frappe.throw(
			_("A terms acceptance cannot be deleted.", context="platform_core.identity"),
			frappe.PermissionError,
		)
