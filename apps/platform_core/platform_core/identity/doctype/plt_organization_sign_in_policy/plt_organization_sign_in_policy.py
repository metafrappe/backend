# Copyright (c) 2026, Platform and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PLTOrganizationSigninPolicy(Document):
	"""Sign-in rule of one organisation (G-160). `enterprise_membership.required_realm_roles` reads it."""
