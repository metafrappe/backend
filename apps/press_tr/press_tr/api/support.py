"""Customer approval and bounded support access endpoints."""

import frappe
from frappe.rate_limiter import rate_limit

from press_tr.support import service


@frappe.whitelist(methods=["POST"])
def request_access(site: str, reason: str, administrator: bool = False) -> dict:
	"""Request one site and one purpose. Customer approval is a separate operation."""
	frappe.only_for("Press Support Agent")
	if not frappe.has_permission("Support Access", ptype="create"):
		frappe.throw(
			frappe._("Valid customer consent is required for support access."), frappe.PermissionError
		)
	return service.request_access(site, reason, administrator)


@frappe.whitelist(methods=["POST"])
def approve_access(name: str, allowed_for: str = "3") -> dict:
	"""Approve a pending request as its customer owner for a bounded number of hours."""
	doc = frappe.get_doc("Support Access", name, for_update=True)
	doc.check_permission("write")
	return service.approve_access(name, allowed_for)


@frappe.whitelist(methods=["POST"])
def revoke_access(name: str) -> dict:
	"""Withdraw customer consent so subsequent support reads are denied."""
	doc = frappe.get_doc("Support Access", name, for_update=True)
	doc.check_permission("write")
	return service.revoke_access(name)


@frappe.whitelist(methods=["POST"])
def site_status(name: str) -> dict:
	"""Read only the site's name and status and persist an audit entry."""
	frappe.only_for("Press Support Agent")
	doc = frappe.get_doc("Support Access", name, for_update=True)
	doc.check_permission("read")
	return service.site_status(name)


@frappe.whitelist(methods=["POST"])
def open_tenant_session(name: str) -> dict:
	"""Issue a single-use ticket for the consented tenant site. The opening is audited with its reason."""
	frappe.only_for("Press Support Agent")
	doc = frappe.get_doc("Support Access", name, for_update=True)
	doc.check_permission("read")
	return service.open_tenant_session(name)


# The tenant site calls the next two over the private network (O-55). They carry no Press session:
# the single-use ticket or the session key is the only credential and is bound to one site.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=60)
def redeem_tenant_session(ticket: str, site: str) -> dict:
	"""Exchange a ticket once for a session key bound to the same consent and site."""
	return service.redeem_tenant_session(ticket, site)


@frappe.whitelist(allow_guest=True, methods=["POST"])
# One tenant server checks every request of its support users, so this limit is higher.
@rate_limit(limit=1200, seconds=60)
def check_tenant_session(session_key: str, site: str) -> dict:
	"""Recheck the consent behind one open tenant support session."""
	return service.check_tenant_session(session_key, site)
