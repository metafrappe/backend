"""G-139: store and read one user's tour progress. The rules are in `tour_rules`.

Callers pass the session user. The record name comes from the user and the tour,
so two parallel saves cannot create two records for the same pair.
"""

import json

import frappe

from platform_core.shell.tour_rules import (
	TourProgressError,
	merge_progress,
	normalize_progress,
	progress_name,
)

DOCTYPE = "PLT Tour Progress"


def _invalid() -> None:
	frappe.throw(
		frappe._("The tour progress is not valid.", context="shell.tour"),
		frappe.ValidationError,
	)


def _as_progress(row: dict) -> dict:
	seen = row.get("seen_steps") or "[]"
	if isinstance(seen, str):
		seen = json.loads(seen)
	return {
		"tour_id": row["tour_id"],
		"version": int(row["tour_version"]),
		"status": row["status"],
		"current_step": row.get("current_step") or None,
		"seen_steps": list(seen),
	}


def _stored(user: str, tour_id: str, *, for_update: bool = False) -> dict | None:
	row = frappe.db.get_value(
		DOCTYPE,
		progress_name(user, tour_id),
		["tour_id", "tour_version", "status", "current_step", "seen_steps", "user"],
		as_dict=True,
		for_update=for_update,
	)
	# The name is a hash. The user check guards against a collision.
	if not row or row.user != user:
		return None
	return _as_progress(row)


def get_progress(user: str, tour_id: str) -> dict | None:
	try:
		tour_id = normalize_progress(
			{"tour_id": tour_id, "version": 1, "status": "active", "current_step": None, "seen_steps": []}
		)["tour_id"]
	except TourProgressError:
		_invalid()
	return _stored(user, tour_id)


def save_progress(user: str, payload: dict, *, restart: bool = False, _retry: bool = False) -> dict:
	try:
		incoming = normalize_progress(payload)
	except TourProgressError:
		_invalid()
	name = progress_name(user, incoming["tour_id"])
	stored = _stored(user, incoming["tour_id"], for_update=True)
	merged = merge_progress(stored, incoming, restart=restart)
	values = {
		"tour_version": merged["version"],
		"status": merged["status"],
		"current_step": merged["current_step"] or "",
		"seen_steps": json.dumps(merged["seen_steps"]),
	}
	exists = frappe.db.exists(DOCTYPE, name)
	if stored is None and exists:
		# The hash name belongs to another user. Never overwrite it.
		_invalid()
	if not exists:
		doc = frappe.new_doc(DOCTYPE)
		doc.update({"user": user, "tour_id": merged["tour_id"], **values})
		try:
			# The API checked the session. Users have no direct permission on this DocType.
			doc.insert(set_name=name, ignore_permissions=True)
		except frappe.DuplicateEntryError:
			# A parallel first save won. Merge into its record instead.
			if _retry:
				raise
			return save_progress(user, payload, restart=restart, _retry=True)
	else:
		frappe.db.set_value(DOCTYPE, name, values)
	return merged


def delete_user_progress(user, method=None):
	"""Remove the user's tour progress before Frappe checks links to the user."""
	frappe.db.delete(DOCTYPE, {"user": user.name})
