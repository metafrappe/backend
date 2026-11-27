"""Internal status delivery record, unavailable to customer mutations."""

from frappe.model.document import Document


class PTRJobStatusOutbox(Document):
	pass
