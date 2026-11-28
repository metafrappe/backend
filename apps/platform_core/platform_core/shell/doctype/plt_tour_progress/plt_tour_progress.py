"""The “Tour Progress” record: one user's progress of one interface tour (G-139)."""

from frappe.model.document import Document


class PLTTourProgress(Document):
	"""Written only through `platform_core.api.tour`. The name comes from the user and the tour."""
