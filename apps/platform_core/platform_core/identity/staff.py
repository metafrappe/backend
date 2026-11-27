"""SA-3: opt-in operations-site staff policy on the existing verified OIDC callback."""

import re

import frappe
from frappe import _

ROLE_MAP = {
	"ops-admin": "PLT Ops Admin",
	"ops-billing": "Sales User",
	"ops-support": "Agent",
	"ops-finance": "Accounts Manager",
}
MANAGED_ROLES = frozenset(ROLE_MAP.values())


def deny() -> None:
	frappe.throw(_("Staff access is denied.", context="platform_core.identity"), frappe.PermissionError)


def verified_roles(claims: dict) -> set[str]:
	groups = claims.get("groups")
	access = claims.get("realm_access")
	roles = access.get("roles") if isinstance(access, dict) else None
	if not isinstance(groups, list) or not all(isinstance(group, str) for group in groups):
		deny()
	if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
		deny()
	if str(claims.get("preferred_username", "")).startswith("service-account-"):
		deny()
	if "/platform-operator" not in groups:
		return set()
	selected = {ROLE_MAP[role] for role in set(roles) & ROLE_MAP.keys()}
	return selected


def resolve_staff_user(issuer: str, claims: dict) -> str:
	"""Sign-ups remain closed; neither email nor token roles can create an account binding."""
	revision = frappe.conf.get("platform_staff_helpdesk_revision")
	if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
		deny()
	if "helpdesk" not in frappe.get_installed_apps() or not frappe.db.exists("DocType", "HD Agent"):
		deny()
	verified_roles(claims)
	accounts = frappe.conf.get("platform_staff_accounts", {})
	if not isinstance(accounts, dict) or claims.get("iss") != issuer:
		deny()
	users = [
		user
		for user, binding in accounts.items()
		if isinstance(binding, dict)
		and binding.get("issuer") == issuer
		and binding.get("subject") == claims.get("sub")
		and binding.get("subject")
	]
	if len(users) != 1 or users[0] in {"Guest", "Administrator"}:
		deny()
	user = users[0]
	linked = frappe.db.get_value("PLT Identity Link", {"issuer": issuer, "subject": claims["sub"]}, "user")
	if linked != user:
		deny()
	if frappe.db.get_value("User", user, ["enabled", "user_type"]) != (1, "System User"):
		deny()
	return user


def save_authorized(doc, *, insert: bool = False) -> None:
	"""Only a verified, prelinked staff account reaches this internal write."""
	previous = doc.flags.ignore_permissions
	try:
		if insert:
			doc.insert(ignore_permissions=True)
		else:
			doc.save(ignore_permissions=True)
	finally:
		doc.flags.ignore_permissions = previous


def synchronize_staff(user: str, claims: dict) -> None:
	if resolve_staff_user(claims.get("iss"), claims) != user:
		deny()
	roles = verified_roles(claims)
	# The caller holds the identity lock; locking the User row serializes HD Agent creation.
	doc = frappe.get_doc("User", user, for_update=True)
	if getattr(doc, "role_profiles", None) or getattr(doc, "role_profile_name", None):
		deny()
	agent_name = frappe.db.exists("HD Agent", {"user": user})
	for row in list(doc.roles):
		if row.role == "System Manager":
			deny()
		if row.role in MANAGED_ROLES and row.role not in roles:
			doc.remove(row)
	existing = {row.role for row in doc.roles}
	for role in sorted(roles - existing):
		if role == "Agent" and not agent_name:
			# Helpdesk's controller grants the role when the first HD Agent is inserted.
			continue
		doc.append("roles", {"role": role})
	save_authorized(doc)
	if "Agent" in roles and not agent_name:
		# A missing Helpdesk installation fails closed. It must not produce a partial staff session.
		agent = frappe.get_doc(
			{"doctype": "HD Agent", "user": user, "agent_name": doc.full_name or user, "is_active": 1}
		)
		save_authorized(agent, insert=True)
	elif agent_name:
		agent = frappe.get_doc("HD Agent", agent_name, for_update=True)
		active = int("Agent" in roles)
		if agent.is_active != active:
			agent.is_active = active
			save_authorized(agent)

	if not roles:
		# Persist this verified identity revocation despite the callback refusal rollback.
		# The caller holds the identity lock and has not opened a new session.
		frappe.db.commit()
		deny()
