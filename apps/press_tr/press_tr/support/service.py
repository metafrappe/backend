"""Persist customer consent and expose only a bounded support read operation."""

import json
from html import escape

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from press_tr.support import tenant_session
from press_tr.support.policy import ConsentDenied, authorize, validate_change

APPROVAL_FIELDS = ("custom_ptr_approved_by", "custom_ptr_approved_at", "custom_ptr_consent_version")
API_METHODS = (
	"press_tr.api.support.request_access",
	"press_tr.api.support.approve_access",
	"press_tr.api.support.revoke_access",
	"press_tr.api.support.site_status",
	"press_tr.api.support.open_tenant_session",
)
SUPPORT_ROLE = "Press Support Agent"


def deny() -> None:
	frappe.throw(_("Valid customer consent is required for support access."), frappe.PermissionError)


def _name(value: str) -> None:
	if not isinstance(value, str) or not value.strip() or len(value) > 140:
		deny()


def _record(doc) -> dict:
	data = doc.as_dict()
	for field in ("access_allowed_till", "custom_ptr_approved_at"):
		if data.get(field):
			data[field] = get_datetime(data[field])
	return data


def _customer_owner(team: str) -> str:
	return frappe.db.get_value("Team", team, "user")


def validate_support_access(doc, method=None) -> None:
	"""Guard native saves, including saves made with permission bypass flags."""
	previous = doc.get_doc_before_save()
	for field in APPROVAL_FIELDS:
		old = previous.get(field) if previous else None
		if doc.get(field) not in (old, None, "", 0) or (old and doc.get(field) != old):
			deny()
	try:
		validate_change(
			_record(doc),
			_record(previous) if previous else None,
			actor=frappe.session.user,
			customer_owner=_customer_owner(doc.target_team),
			now=now_datetime(),
		)
	except (ConsentDenied, TypeError, ValueError):
		deny()
	if previous and previous.status == "Pending" and doc.status == "Accepted":
		doc.custom_ptr_approved_by = frappe.session.user
		doc.custom_ptr_approved_at = now_datetime()
		doc.custom_ptr_consent_version = 1


def audit_support_access(doc, method=None) -> None:
	"""Write the reason and exact scope in the same transaction as the state change."""
	old = doc.get_doc_before_save()
	if old and old.status == doc.status:
		return
	_audit(doc, "consent_" + doc.status.lower())


def _audit(doc, event: str) -> None:
	# Comment is a native append operation. No session identifier or credential is logged.
	doc.add_comment(
		"Info",
		text=escape(
			json.dumps(
				{
					"event": event,
					"consent": doc.name,
					"actor": frappe.session.user,
					"reason": doc.reason,
					"requested_by": doc.requested_by,
					"requested_team": doc.requested_team,
					"target_team": doc.target_team,
					"resources": [{"site": row.document_name} for row in doc.resources],
					"administrator": bool(doc.login_as_administrator),
					"expires_at": str(doc.access_allowed_till) if doc.access_allowed_till else None,
				},
				ensure_ascii=True,
			)
		),
	)


def _support_user() -> str:
	from press.utils import get_current_team

	if frappe.session.user in {"Guest", "Administrator"} or SUPPORT_ROLE not in frappe.get_roles():
		deny()
	return get_current_team()


def request_access(site: str, reason: str, administrator: bool = False) -> dict:
	"""Create a pending request. This does not create a tenant login session."""
	team = _support_user()
	_name(site)
	if not isinstance(reason, str):
		deny()
	if type(administrator) is not bool:
		deny()
	# Native validation resolves the target team from the named site's stored owner.
	doc = frappe.get_doc(
		{
			"doctype": "Support Access",
			"status": "Pending",
			"reason": reason,
			"requested_by": frappe.session.user,
			"requested_team": team,
			"resources": [{"document_type": "Site", "document_name": site}],
			"login_as_administrator": int(administrator),
			"allowed_for": "3",
			"bench_ssh": 0,
			"site_domains": 0,
			"site_release_group": 0,
		}
	)
	doc.insert()
	return {"name": doc.name, "status": doc.status}


def _customer_record(name: str):
	_name(name)
	doc = frappe.get_doc("Support Access", name, for_update=True)
	if frappe.session.user == "Guest" or frappe.session.user != _customer_owner(doc.target_team):
		deny()
	return doc


def approve_access(name: str, allowed_for: str = "3") -> dict:
	"""Approve one pending request as the customer owner, never as its requester."""
	doc = _customer_record(name)
	if doc.status != "Pending":
		deny()
	doc.allowed_for = str(allowed_for)
	doc.status = "Accepted"
	doc.save()
	return {"name": doc.name, "status": doc.status, "expires_at": str(doc.access_allowed_till)}


def revoke_access(name: str) -> dict:
	"""Revoke an approved grant under the same row lock used by support reads."""
	doc = _customer_record(name)
	if doc.status != "Accepted":
		deny()
	doc.status = "Revoked"
	doc.save()
	return {"name": doc.name, "status": doc.status}


def _checked_grant(name: str, *, actor: str, team: str, lock: bool = True):
	"""Recheck one ordinary consent and the site's current owner for this use.

	Reads that return data or issue a credential lock both rows. The per-request tenant check reads
	committed rows without locks, so a busy support session does not hold Press's Site row.
	"""
	_name(name)
	lock_args = {"for_update": True} if lock else {}
	doc = frappe.get_doc("Support Access", name, **lock_args)
	data = _record(doc)
	owner = _customer_owner(doc.target_team)
	if (
		data.get("custom_ptr_consent_version") != 1
		or not owner
		or data.get("custom_ptr_approved_by") != owner
		or not data.get("custom_ptr_approved_at")
	):
		deny()
	try:
		rows = data.get("resources", [])
		if len(rows) != 1:
			deny()
		site = rows[0]["document_name"]
		authorize(data, actor=actor, team=team, site=site, administrator=False, now=now_datetime())
	except (ConsentDenied, TypeError, ValueError, KeyError):
		deny()
	# Check current ownership too. A transferred site never inherits its old customer's consent.
	resource = frappe.get_doc("Site", site, **lock_args)
	if resource.team != doc.target_team:
		deny()
	return doc, resource


def site_status(name: str) -> dict:
	"""Read the approved site's name and status, with a fresh consent check and audit."""
	team = _support_user()
	doc, resource = _checked_grant(name, actor=frappe.session.user, team=team)
	_audit(doc, "site_status_read")
	return {"site": resource.name, "status": resource.status}


def _remaining_seconds(doc) -> int:
	return max(1, int((get_datetime(doc.access_allowed_till) - now_datetime()).total_seconds()))


def _take(key: str):
	"""Read and delete a single-use value. Only the caller whose delete succeeds may use it."""
	try:
		value = frappe.cache.get_value(key)
		removed = frappe.cache.delete(frappe.cache.make_key(key))
	except Exception:
		# An unavailable cache is a refusal, not a server error.
		return None
	return value if removed == 1 else None


def _bound_grant(prefix: str, secret, site, *, single_use: bool):
	try:
		key = tenant_session.storage_key(prefix, secret)
		_name(site)
		record = _take(key) if single_use else frappe.cache.get_value(key)
		bound = tenant_session.match(record, site=site)
	except ConsentDenied:
		deny()
	# A requester who left the support role loses every open session at the next check.
	if SUPPORT_ROLE not in frappe.get_roles(bound["actor"]):
		deny()
	doc, resource = _checked_grant(
		bound["consent"], actor=bound["actor"], team=bound["team"], lock=single_use
	)
	return bound, doc, resource


def open_tenant_session(name: str) -> dict:
	"""Issue a single-use ticket for the consented site. The opening and its reason are audited first."""
	team = _support_user()
	doc, resource = _checked_grant(name, actor=frappe.session.user, team=team)
	_audit(doc, "tenant_session_opened")
	ticket = tenant_session.new_secret()
	frappe.cache.set_value(
		tenant_session.storage_key(tenant_session.TICKET_PREFIX, ticket),
		tenant_session.binding(consent=doc.name, site=resource.name, actor=frappe.session.user, team=team),
		expires_in_sec=tenant_session.TICKET_SECONDS,
	)
	return {"site": resource.name, "ticket": ticket, "expires_in": tenant_session.TICKET_SECONDS}


def redeem_tenant_session(ticket: str, site: str) -> dict:
	"""Exchange a ticket, once, for a session key that the named tenant site presents on every request."""
	bound, doc, resource = _bound_grant(tenant_session.TICKET_PREFIX, ticket, site, single_use=True)
	session_key = tenant_session.new_secret()
	remaining = _remaining_seconds(doc)
	# The key's lifetime only cleans up storage. Every check rereads the consent itself.
	frappe.cache.set_value(
		tenant_session.storage_key(tenant_session.SESSION_PREFIX, session_key),
		bound,
		expires_in_sec=remaining,
	)
	return {"consent": doc.name, "site": resource.name, "expires_in": remaining, "session_key": session_key}


def check_tenant_session(session_key: str, site: str) -> dict:
	"""Confirm, for one tenant request, that the session's consent is still approved and unexpired."""
	_bound, doc, _resource = _bound_grant(tenant_session.SESSION_PREFIX, session_key, site, single_use=False)
	return {"consent": doc.name, "expires_in": _remaining_seconds(doc)}


def enforce_support_routes(target) -> None:
	"""Keep support identities away from native Press's unbound consent shortcuts."""
	from frappe.handler import logout

	if "Press Support Agent" not in frappe.get_roles():
		return
	request = getattr(frappe.local, "request", None)
	# This existing authenticated, no-store page supplies Frappe's browser CSRF token.
	# A resolved RPC target must never become allowed merely because of its page path.
	if (
		target is None
		and request is not None
		and request.method in {"GET", "HEAD"}
		and request.path.rstrip("/") == "/account-deletion"
	):
		return
	allowed = {logout, *(frappe.get_attr(name) for name in API_METHODS)}
	if target not in allowed:
		deny()


class SiteSupportPolicy:
	"""Preserve customer team and internal worker login while closing support SID issuance."""

	def _require_native_login_actor(self):
		actor = frappe.session.user
		if actor == "Administrator":
			# execute_job creates local.job in the worker. HTTP input cannot create it.
			# Reject HTTP even if an in-process caller has left a job marker behind.
			if getattr(frappe.local, "request", None) is None and getattr(frappe.local, "job", None):
				return
			deny()
		if actor == "Guest" or "Press Support Agent" in frappe.get_roles():
			deny()
		if actor != _customer_owner(self.team) and not frappe.db.exists(
			"Team Member",
			{"parent": self.team, "parenttype": "Team", "parentfield": "team_members", "user": actor},
		):
			deny()

	def get_login_sid(self, user: str = "Administrator"):
		self._require_native_login_actor()
		return super().get_login_sid(user=user)

	def get_sid_from_agent(self, user: str):
		self._require_native_login_actor()
		return super().get_sid_from_agent(user)
