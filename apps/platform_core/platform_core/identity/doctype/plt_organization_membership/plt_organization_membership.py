# Copyright (c) 2026, Platform and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from platform_core.identity import enterprise_membership


class PLTOrganizationMembership(Document):
	"""Membership of one user in one organisation (G-160). See `enterprise_membership`."""

	def before_insert(self):
		enterprise_membership.membership_before_insert(self)

	def validate(self):
		enterprise_membership.membership_validate(self)
