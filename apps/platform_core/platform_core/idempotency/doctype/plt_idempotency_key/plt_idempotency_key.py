"""Internal key record. Only the idempotency layer writes it (`platform_core.idempotency.core`)."""

import frappe
from frappe import _
from frappe.model.document import Document

from platform_core.idempotency.core import CONTEXT, KEY_DOCTYPE, key_name

# The organization, account, endpoint and key are unique together (contract section 3).
SCOPE_FIELDS = ["organization", "account", "endpoint", "idempotency_key"]


class PLTIdempotencyKey(Document):
	def autoname(self) -> None:
		self.name = key_name(
			organization=self.organization,
			account=self.account,
			endpoint=self.endpoint,
			key=self.idempotency_key,
		)

	def validate(self) -> None:
		if not self.flags.from_idempotency_layer:
			self._reject()

	def on_trash(self) -> None:
		self._reject()

	@staticmethod
	def _reject() -> None:
		frappe.throw(_("Idempotency keys are internal.", context=CONTEXT), frappe.PermissionError)


def on_doctype_update() -> None:
	frappe.db.add_unique(KEY_DOCTYPE, SCOPE_FIELDS, constraint_name="unique_idempotency_scope")
