"""Checks shared by the customer endpoints that change a team."""

import secrets

import frappe
from frappe import _

from press_tr.press_identity.deletion import human_identity


def team_admin(allowed_fields: set[str]):
	"""Return the team of a signed-in owner or admin. The request may carry only `allowed_fields`."""
	human_identity()
	csrf_token = frappe.get_request_header("X-Frappe-CSRF-Token", "")
	saved_token = frappe.session.data.get("csrf_token")
	if not csrf_token or not saved_token or not secrets.compare_digest(csrf_token, saved_token):
		_deny()
	if set(frappe.form_dict) - {"cmd", *allowed_fields}:
		_deny()

	from press.utils import is_admin_user, is_team_owner

	team = frappe.local.team()
	if not (is_team_owner(team.name) or is_admin_user(team.name)):
		frappe.throw(
			_("Only the team owner or an admin can do this.", context="press_tr"), frappe.PermissionError
		)
	return team


def _deny():
	frappe.throw(_("This Press request is not allowed.", context="press_tr"), frappe.PermissionError)
