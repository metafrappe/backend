"""SA-1/SA-2: prelinked operators, separate service users and financial permissions."""

import logging

import frappe
from frappe import _

ROLE_MAP = {
	"ops-admin": "Press Ops Admin",
	"ops-billing": "Press Ops Billing",
	"ops-support": "Press Support Agent",
	"ops-finance": "Press Ops Billing",
}
MANAGED_ROLES = frozenset(ROLE_MAP.values())
SERVICE_ROLES = frozenset({"Press Service", "All", "Guest"})
FINANCIAL_DOCTYPES = frozenset({"Invoice", "Balance Transaction"})
BILLING_PERMISSIONS = {
	"Invoice": ("read", "write", "create", "submit", "print"),
	"Balance Transaction": ("read", "write", "create", "submit"),
	"Payment Due Extension": ("read", "write", "create"),
	"Team": ("read", "select"),
}


def deny() -> None:
	frappe.throw(_("Operator access is denied.", context="press_tr"), frappe.PermissionError)


def accounts() -> dict:
	value = frappe.conf.get("press_operator_accounts", {})
	if not isinstance(value, dict):
		deny()
	return value


def service_users() -> set[str]:
	value = frappe.conf.get("press_service_users", [])
	if not isinstance(value, list) or not all(isinstance(user, str) for user in value):
		deny()
	return set(value)


def verified_roles(claims: dict) -> set[str]:
	"""Called only after the existing ID-token signature, issuer, audience and nonce checks."""
	groups = claims.get("groups", [])
	access = claims.get("realm_access", {})
	roles = access.get("roles", []) if isinstance(access, dict) else None
	if not isinstance(groups, list) or not all(isinstance(group, str) for group in groups):
		deny()
	if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
		deny()
	selected = set(roles) & ROLE_MAP.keys()
	if "/platform-operator" not in groups:
		selected = set()
	if selected and str(claims.get("preferred_username", "")).startswith("service-account-"):
		deny()
	return {ROLE_MAP[role] for role in selected}


def bind_operator(claims: dict):
	"""Return an existing operator link, or None for the existing customer login flow."""
	roles = verified_roles(claims)
	registered = [
		user
		for user, binding in accounts().items()
		if isinstance(binding, dict)
		and binding.get("issuer") == claims.get("iss")
		and binding.get("subject") == claims.get("sub")
		and binding.get("issuer")
		and binding.get("subject")
	]
	if not roles and not registered:
		return None
	if len(registered) != 1:
		deny()
	user = registered[0]
	if user in service_users() or user in {"Guest", "Administrator"}:
		deny()
	link = frappe.db.get_value(
		"PTR Identity Link",
		{"issuer": claims["iss"], "subject": claims["sub"], "user": user},
		["name", "user"],
		as_dict=True,
		for_update=True,
	)
	if not link or link.user != user:
		deny()
	doc = frappe.get_doc("User", user, for_update=True)
	if not doc.enabled or doc.user_type != "System User":
		deny()
	if getattr(doc, "role_profiles", None) or getattr(doc, "role_profile_name", None):
		deny()
	for row in list(doc.roles):
		if row.role == "System Manager":
			deny()
		if row.role in MANAGED_ROLES and row.role not in roles:
			doc.remove(row)
	existing = {row.role for row in doc.roles}
	for role in sorted(roles - existing):
		doc.append("roles", {"role": role})
	# The target comes from an exact, preconfigured issuer/subject binding, never an email claim.
	from press_tr.press_identity.accounts import save_authorized_document

	save_authorized_document(doc)
	if not roles:
		# Persist this verified identity revocation despite the callback refusal rollback.
		# No business operation or new session has been started.
		frappe.db.commit()
		deny()
	audit(
		"operator_sign_in",
		actor=user,
		realm_roles=sorted(set(claims["realm_access"]["roles"]) & ROLE_MAP.keys()),
	)
	return link


def validate_user_roles(doc, method=None) -> None:
	roles = {row.role for row in doc.roles}
	if doc.name in accounts() and (
		getattr(doc, "role_profiles", None) or getattr(doc, "role_profile_name", None)
	):
		deny()
	if doc.name in service_users():
		if roles - SERVICE_ROLES or doc.name in accounts():
			deny()
	elif roles & MANAGED_ROLES:
		if doc.name not in accounts() or doc.user_type != "System User" or "System Manager" in roles:
			deny()


def audit(
	event: str,
	*,
	privileged_support: bool = False,
	doctype: str | None = None,
	actor: str | None = None,
	realm_roles: list[str] | None = None,
) -> None:
	# Never attach form_dict, headers, URL parameters, tokens or user-supplied record content.
	logger = frappe.logger("press_operator_audit", with_more_info=False, allow_site=True)
	logger.setLevel(logging.INFO)
	record = {"event": event, "actor": actor or frappe.session.user, "privileged_support": privileged_support}
	if doctype in FINANCIAL_DOCTYPES:
		record["doctype"] = doctype
	if realm_roles is not None:
		record["realm_roles"] = [role for role in realm_roles if role in ROLE_MAP]
	logger.info(record)


def guard_request() -> None:
	"""auth_hooks runs after Frappe resolves cookie and individual API-key identities."""
	user = frappe.session.user
	if user in {"Guest", "Administrator"}:
		return
	roles = set(frappe.get_roles(user))
	if user in service_users():
		if roles - SERVICE_ROLES or user in accounts():
			deny()
		return
	if not roles & MANAGED_ROLES and user not in accounts():
		return
	if user not in accounts() or "System Manager" in roles:
		deny()
	if not roles & MANAGED_ROLES:
		deny()
	if frappe.db.exists("User Role Profile", {"parent": user, "parenttype": "User"}) or frappe.db.exists(
		"User", {"name": user, "role_profile_name": ["is", "set"]}
	):
		deny()
	binding = accounts()[user]
	if not isinstance(binding, dict) or not binding.get("issuer") or not binding.get("subject"):
		deny()
	if frappe.db.get_value("User", user, ["enabled", "user_type"]) != (1, "System User"):
		deny()
	link = frappe.db.get_value(
		"PTR Identity Link",
		{"issuer": binding["issuer"], "subject": binding["subject"], "user": user},
		["name", "user"],
		as_dict=True,
	)
	if not link or link.user != user:
		deny()
	audit("operator_request", privileged_support="Press Support Agent" in roles)


def install_permissions() -> None:
	"""Idempotent install/migrate policy; preserve unrelated custom permission rows."""
	from frappe.permissions import add_permission, setup_custom_perms

	for role in sorted(MANAGED_ROLES | {"Press Service"}):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()
	for doctype, permissions in BILLING_PERMISSIONS.items():
		setup_custom_perms(doctype)
		add_permission(doctype, "Press Ops Billing")
		# Reconcile our role exactly, including stale owner/higher-level rows from older installs.
		for name in frappe.get_all(
			"Custom DocPerm", filters={"parent": doctype, "role": "Press Ops Billing"}, pluck="name"
		):
			doc = frappe.get_doc("Custom DocPerm", name)
			for permission in (
				"read",
				"write",
				"create",
				"submit",
				"cancel",
				"amend",
				"delete",
				"share",
				"import",
				"export",
				"print",
				"email",
				"report",
				"select",
			):
				doc.set(
					permission, int(doc.permlevel == 0 and not doc.if_owner and permission in permissions)
				)
			doc.save()
		frappe.clear_cache(doctype=doctype)
	# Invoice/Balance Transaction create, write and submit are used by Press internal billing.
	# Generic HTTP writes are independently guarded by financial_policy.guard_request (AJA-197).
