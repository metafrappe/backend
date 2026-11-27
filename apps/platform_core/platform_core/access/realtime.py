"""Realtime rooms of governed document types (G-121).

Before a socket joins a room, the realtime server asks the web process through
`/api/method/frappe.realtime.has_permission` (`frappe/realtime/auth.py:87`). An empty name asks
for the list room of a document type. Frappe sends `list_update` to that room with the name of
the changed record and the user who changed it (`frappe/model/document.py:1784`). A narrowed
user would learn about records outside their rule.

`hooks.py` puts `has_permission` below in place of Frappe's function. On a governed document
type the list room is open only to a user with a read rule of scope "all" and no filters. That
user sees every record anyway. The record room keeps Frappe's check, which asks the record hook
of the engine. A narrowed user's list does not refresh by itself; the user reloads it.
Decision note, section 9.
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.realtime import has_permission as frappe_has_permission
from frappe.utils import escape_html

from platform_core.access import rules

# Each opened form and list asks once. The limit only stops a flood of checks.
CHECKS_PER_MINUTE = 600


def sees_every_record(doctype: str, user: str) -> bool:
	"""True when the rules hide no record of the document type from the user."""
	if user == "Administrator" or not rules.is_governed(doctype):
		return True
	return any(
		rule["scope"] == "all" and not rule["filters"] for rule in rules.applicable(doctype, user, "read")
	)


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
@rate_limit(limit=CHECKS_PER_MINUTE, seconds=60, user_based=True)
def has_permission(doctype: str, name: str, ptype: str = "read") -> bool:
	if not name and not sees_every_record(doctype, frappe.session.user):
		frappe.throw(
			_("Live list updates of {0} are closed: Access Rules hide some of its records from you.").format(
				# The name comes straight from the request.
				frappe.bold(escape_html(doctype))
			),
			frappe.PermissionError,
		)
	return frappe_has_permission(doctype, name, ptype)
