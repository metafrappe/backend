"""Export the current corporate provider exceptions for the apply command (G-160, AJA-229).

Frappe never writes Keycloak. The DevOps owner runs two steps by hand:

1. `bench --site <site> execute platform_core.identity.enterprise_sync.export_exceptions
   --kwargs '{"path": "<file>"}'` writes the current grants to a JSON file.
2. `bin/atonota-login apply --from-env --enterprise-exceptions <file>` checks every corporate
   provider against the file.

The file holds only the record fields and no secret. It is written with mode 0600 and must not be
committed to Git. The file is not signed: the apply command checks the rules again, but it cannot
prove from the file alone that the approval was given. Only the DevOps owner carries the file.

The membership roles travel the same way (G-160, design AJA-361):

1. `bench --site <site> execute platform_core.identity.enterprise_sync.export_realm_roles
   --kwargs '{"path": "<file>"}'` writes the realm roles that active memberships need.
2. `bin/atonota-login apply --from-env --realm-roles <file>` gives the roles and takes them back
   from users who no longer need them.

The roles file is `{"organizations": [...], "entries": [...]}`. The platform realm serves every
tenant site, so `organizations` names this site's source organisations by their Keycloak
organisation id (AJA-391). The apply step takes the role back only from their members. Each entry
names a user only by the subject of the identity link of the platform realm. The file holds no
e-mail. A member without such a link has no Keycloak account yet and is not in the file.

No scheduled job runs these exports.
"""

from __future__ import annotations

import json
import os

import frappe

from platform_core.identity import enterprise_membership, enterprise_rules, site_settings

LINK = "PLT Identity Link"


def current_grants() -> list[dict]:
	"""Every current grant, checked by the rules. A rule break stops the export."""
	pairs = frappe.get_all(
		enterprise_membership.DOCTYPE,
		fields=["provider_alias", "organization"],
		distinct=True,
		order_by="provider_alias asc, organization asc",
	)
	records = []
	for pair in pairs:
		doc = enterprise_membership.current_exception(pair.provider_alias, pair.organization)
		if doc is None:
			continue
		record = enterprise_membership.to_record(doc)
		enterprise_membership.check_or_throw(enterprise_rules.check_record, record)
		records.append(record)
	return records


def _write_private(path: str, value) -> None:
	descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
	with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
		os.fchmod(handle.fileno(), 0o600)
		json.dump(value, handle, indent=2, sort_keys=True)
		handle.write("\n")


def export_exceptions(path: str) -> int:
	"""Write the current grants to `path` with mode 0600. Returns the number of records."""
	frappe.only_for(enterprise_membership.APPROVER_ROLE)
	records = current_grants()
	_write_private(path, records)
	return len(records)


def realm_role_entries() -> list[dict]:
	"""One entry per linked member who needs a realm role, keyed by the platform realm subject."""
	issuer = site_settings.issuer()
	users = frappe.get_all(
		enterprise_membership.MEMBERSHIP_DOCTYPE,
		filters={"status": enterprise_membership.ACTIVE},
		pluck="user",
		distinct=True,
		order_by="user asc",
	)
	entries = []
	for user in users:
		roles = enterprise_membership.required_realm_roles(user)
		if not roles:
			continue
		subject = frappe.db.get_value(LINK, {"user": user, "issuer": issuer}, "subject")
		if subject:
			entries.append({"subject": subject, "realm_roles": roles})
	return sorted(entries, key=lambda entry: entry["subject"])


def source_organizations() -> list[str]:
	"""Keycloak organisation ids of this site: every organisation of a sign-in policy or a membership.

	An organisation whose memberships all ended stays in the list, so the apply step takes the role
	back from its former members.
	"""
	found = set()
	for doctype in (enterprise_membership.POLICY_DOCTYPE, enterprise_membership.MEMBERSHIP_DOCTYPE):
		found.update(frappe.get_all(doctype, pluck="organization", distinct=True))
	return sorted(organization for organization in found if organization)


def export_realm_roles(path: str) -> int:
	"""Write the membership realm roles to `path` with mode 0600. Returns the number of entries.

	A site without any organisation writes an empty organisation list. The apply step refuses such
	a file and takes no role back.
	"""
	frappe.only_for(enterprise_membership.APPROVER_ROLE)
	entries = realm_role_entries()
	_write_private(path, {"organizations": source_organizations(), "entries": entries})
	return len(entries)
