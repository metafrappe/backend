"""Corporate sign-in provider of an organisation and its exception record (G-160, AJA-229).

A corporate provider must require the email_verified claim. A provider that never sends the claim
needs an approved `PLT Enterprise IdP Exception` record. The rules live in `enterprise_rules`; this
module stores and finds the records.

The record is immutable (design AJA-238, section 4):

1. A record waiting for approval takes only the approval fields.
2. An approved record and a revocation record never change.
3. A record is never deleted.
4. A change opens a new record. Its `supersedes` field names the current record.
5. A revocation record ends the exception.
6. The current record of a provider and organisation is the newest approved grant or revocation
   that no other approved grant or revocation supersedes. A revocation means there is no exception.

The requester is the session user. The approver is another user in a human session; an agent
never approves. `approve` checks the session itself. Keycloak is written only by the
`atonota-login apply` command (enterprise_sync).

The module also holds the organisation membership (design AJA-361):

- `PLT Organization Membership` holds one user's membership of one organisation. A user has at most
  one active record in one organisation. The system writes `added_by`.
- `PLT Organization Sign-in Policy` holds one record per organisation. It may require corporate sign-in.
- `required_realm_roles(user)` names the Keycloak realm roles the membership needs. The sync step
  writes them to a file and `atonota-login apply` gives and takes them.
"""

from __future__ import annotations

import secrets
from zoneinfo import ZoneInfo

import frappe
from atonota_login import platforms
from frappe import _
from frappe.utils import get_datetime, get_system_timezone, now_datetime

from platform_core.identity import enterprise_rules
from platform_core.identity.enterprise_rules import EnterpriseRuleError

DOCTYPE = "PLT Enterprise IdP Exception"
APPROVER_ROLE = "System Manager"
APPROVAL_FIELDS = ("approved_by", "approved_on", "approval_principal")
DATA_FIELDS = (
	"kind",
	"provider_alias",
	"issuer",
	"organization",
	"supersedes",
	"reason",
	"provider_document",
	"expires_on",
	"requested_by",
)
DOMAIN_FIELDS = ("domain", "verification_method", "verified_on", "verification_record")
MEMBERSHIP_DOCTYPE = "PLT Organization Membership"
POLICY_DOCTYPE = "PLT Organization Sign-in Policy"
ACTIVE = "active"
ENTERPRISE_SSO_ROLE = platforms.ENTERPRISE_SSO_ROLE


def _aware(value) -> str | None:
	"""A stored time as ISO 8601 with the system time zone, for the rules and the export file."""
	if not value:
		return None
	moment = get_datetime(value)
	if moment.tzinfo is None:
		moment = moment.replace(tzinfo=ZoneInfo(get_system_timezone()))
	return moment.isoformat()


def to_record(doc) -> dict:
	"""The record in the form that `enterprise_rules` and the apply command read. No secret."""
	return {
		"name": doc.name or "",
		"kind": doc.kind,
		"provider_alias": doc.provider_alias,
		"issuer": doc.issuer or None,
		"organization": doc.organization,
		"allowed_domains": [
			{
				"domain": row.domain,
				"verification_method": row.verification_method,
				"verified_on": _aware(row.verified_on),
				"verification_record": row.verification_record,
			}
			for row in doc.get("allowed_domains") or []
		],
		"reason": doc.reason,
		"provider_document": doc.provider_document or None,
		"requested_by": doc.requested_by,
		"approved_by": doc.approved_by or None,
		"approval_principal": doc.approval_principal or None,
		"approved_on": _aware(doc.approved_on),
		"expires_on": _aware(doc.expires_on),
		"supersedes": doc.supersedes or None,
	}


def check_or_throw(function, record: dict) -> dict:
	try:
		return function(record)
	except EnterpriseRuleError as error:
		frappe.throw(
			_(
				"The corporate provider exception breaks the rule {0}.", context="platform_core.identity"
			).format(error.rule),
			frappe.ValidationError,
		)


def _effective(filters: dict) -> list:
	"""Approved grants and revocations, newest first. A request waiting for approval does not count."""
	rows = frappe.get_all(
		DOCTYPE,
		filters=filters,
		fields=["name", "kind", "provider_alias", "organization", "supersedes", "approved_by"],
		order_by="creation desc, name desc",
	)
	return [row for row in rows if row.kind == "revocation" or row.approved_by]


def current_record(provider_alias: str, organization: str):
	"""The current approved grant or revocation of a provider and organisation, or None."""
	rows = _effective({"provider_alias": provider_alias, "organization": organization})
	superseded = {row.supersedes for row in rows if row.supersedes}
	for row in rows:
		if row.name not in superseded:
			return row
	return None


def current_exception(provider_alias: str, organization: str):
	"""The valid exception document of a provider and organisation, or None."""
	row = current_record(provider_alias, organization)
	if row is None or row.kind != "grant":
		return None
	return frappe.get_doc(DOCTYPE, row.name)


def _check_chain(doc) -> None:
	"""The new record supersedes the current one. One provider alias serves one organisation."""
	current = current_record(doc.provider_alias, doc.organization)
	if current is None:
		if doc.supersedes:
			frappe.throw(
				_(
					"The first record of a provider and organisation supersedes no record.",
					context="platform_core.identity",
				),
				frappe.ValidationError,
			)
	elif doc.supersedes != current.name:
		frappe.throw(
			_("This record must supersede the current record {0}.", context="platform_core.identity").format(
				current.name
			),
			frappe.ValidationError,
		)
	if doc.kind == "revocation" and (current is None or current.kind != "grant"):
		frappe.throw(
			_("Only a current grant can be revoked.", context="platform_core.identity"),
			frappe.ValidationError,
		)
	if doc.kind == "grant":
		others = {
			row.organization
			for row in _effective(
				{"provider_alias": doc.provider_alias, "organization": ("!=", doc.organization)}
			)
		}
		for organization in others:
			other = current_record(doc.provider_alias, organization)
			if other is not None and other.kind == "grant":
				frappe.throw(
					_(
						"The provider {0} already has an exception for another organisation.",
						context="platform_core.identity",
					).format(doc.provider_alias),
					frappe.ValidationError,
				)


def before_insert(doc) -> None:
	# The requester is never picked by hand.
	doc.requested_by = frappe.session.user
	if any(doc.get(field) for field in APPROVAL_FIELDS):
		frappe.throw(
			_("Only the approval endpoint fills the approval fields.", context="platform_core.identity"),
			frappe.ValidationError,
		)


def validate(doc) -> None:
	if doc.is_new():
		check_or_throw(enterprise_rules.check_request, to_record(doc))
		_check_chain(doc)
		return
	before = doc.get_doc_before_save()
	if before is None:
		return
	if before.approved_by or before.kind == "revocation":
		frappe.throw(
			_(
				"An approved exception record cannot change. Open a new record that supersedes it.",
				context="platform_core.identity",
			),
			frappe.ValidationError,
		)
	if not doc.flags.enterprise_approval or _data(doc) != _data(before):
		frappe.throw(
			_("Only the approval endpoint fills the approval fields.", context="platform_core.identity"),
			frappe.ValidationError,
		)


def _data(doc) -> tuple:
	fields = tuple(str(doc.get(field) or "") for field in DATA_FIELDS)
	rows = tuple(
		tuple(str(row.get(field) or "") for field in DOMAIN_FIELDS)
		for row in doc.get("allowed_domains") or []
	)
	return fields, rows


def on_trash(doc) -> None:
	frappe.throw(
		_(
			"An exception record cannot be deleted. Open a revocation record instead.",
			context="platform_core.identity",
		),
		frappe.ValidationError,
	)


def approve(name: str):
	"""Approve a waiting grant. Writes only the approval fields. Needs a human session (G-160)."""
	principal = _require_human()
	frappe.only_for(APPROVER_ROLE)
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.kind != "grant" or doc.approved_by:
		frappe.throw(
			_("Only a grant record waiting for approval can be approved.", context="platform_core.identity"),
			frappe.ValidationError,
		)
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.approval_principal = principal
	check_or_throw(enterprise_rules.check_record, to_record(doc))
	_check_chain(doc)
	doc.flags.enterprise_approval = True
	# No role has write permission on this DocType; the record is immutable (design AJA-238).
	# This line is the only writer of the approval fields. Before it runs, this function has checked
	# a human session and `APPROVER_ROLE`, the endpoint has checked read permission, and the rules
	# above have passed. `validate` still refuses any change other than the approval fields.
	doc.save(ignore_permissions=True)  # nosemgrep: frappe-ignore-permissions
	return doc


def revoke(name: str, reason: str):
	"""Open a revocation record for the current grant `name`. The old record stays."""
	frappe.only_for(APPROVER_ROLE)
	grant = frappe.get_doc(DOCTYPE, name)
	return frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"kind": "revocation",
			"provider_alias": grant.provider_alias,
			"organization": grant.organization,
			"supersedes": grant.name,
			"reason": reason,
		}
	).insert()


HUMAN_SESSION = enterprise_rules.APPROVAL_PRINCIPAL


def request_principal() -> str:
	"""`human_session` only for an HTTP cookie session with a checked CSRF token.

	A request with an `Authorization` header is not a human session. Agent tokens and MCP OAuth
	tokens come in that header. The CSRF comparison is always done here, also when Frappe would skip
	it (no token in the session, `ignore_csrf`, an allowed referrer).
	"""
	# A call outside an HTTP request (bench execute, a job, a console) is never a human session.
	if getattr(frappe.local, "request", None) is None:
		return "other"
	if frappe.session.user in ("", "Guest") or frappe.get_request_header("Authorization"):
		return "other"
	expected = frappe.session.data.get("csrf_token")
	sent = frappe.get_request_header("X-Frappe-CSRF-Token")
	if not (expected and sent and secrets.compare_digest(str(sent), str(expected))):
		return "other"
	return HUMAN_SESSION


def _require_human() -> str:
	principal = request_principal()
	if principal != HUMAN_SESSION:
		raise frappe.PermissionError(
			_("This action needs a human session.", context="platform_core.identity")
		)
	return principal


@frappe.whitelist(methods=["POST"])
def approve_exception(name: str) -> str:
	"""Approval endpoint. Needs a human session with a checked CSRF token; an agent token is refused."""
	frappe.only_for(APPROVER_ROLE)
	if not frappe.has_permission(DOCTYPE, "read", name):
		frappe.throw(
			_("You cannot open this exception record.", context="platform_core.identity"),
			frappe.PermissionError,
		)
	return approve(name).name


@frappe.whitelist(methods=["POST"])
def revoke_exception(name: str, reason: str) -> str:
	"""Revocation endpoint. Needs a human session with a checked CSRF token; an agent token is refused."""
	frappe.only_for(APPROVER_ROLE)
	if not frappe.has_permission(DOCTYPE, "read", name):
		frappe.throw(
			_("You cannot open this exception record.", context="platform_core.identity"),
			frappe.PermissionError,
		)
	_require_human()
	return revoke(name, reason).name


def active_organizations(user: str) -> list[str]:
	"""The organisations in which `user` has an active membership record."""
	if not user or user == "Guest":
		return []
	return frappe.get_all(
		MEMBERSHIP_DOCTYPE,
		filters={"user": user, "status": ACTIVE},
		pluck="organization",
		order_by="organization asc",
	)


def required_realm_roles(user: str) -> list[str]:
	"""Keycloak realm roles that the memberships of `user` need (design AJA-361, decision 3).

	An active membership of an organisation that requires corporate sign-in needs
	`enterprise-sso-required`. Desk roles and ended memberships give no role.
	"""
	organizations = active_organizations(user)
	if organizations and frappe.db.exists(
		POLICY_DOCTYPE, {"organization": ("in", organizations), "enterprise_sso_required": 1}
	):
		return [ENTERPRISE_SSO_ROLE]
	return []


def membership_before_insert(doc) -> None:
	# The adder is never picked by hand.
	doc.added_by = frappe.session.user


def membership_validate(doc) -> None:
	if not doc.is_new():
		before = doc.get_doc_before_save()
		if before is not None and (before.added_by or "") != (doc.added_by or ""):
			frappe.throw(
				_("Only the system writes the Added By field.", context="platform_core.identity"),
				frappe.ValidationError,
			)
	if doc.status != ACTIVE:
		return
	other = frappe.db.exists(
		MEMBERSHIP_DOCTYPE,
		{
			"organization": doc.organization,
			"user": doc.user,
			"status": ACTIVE,
			"name": ("!=", doc.name or ""),
		},
	)
	if other:
		frappe.throw(
			_(
				"The user already has an active membership in this organisation: {0}.",
				context="platform_core.identity",
			).format(other),
			frappe.ValidationError,
		)
