"""Evaluate native Press Support Access records without granting a tenant session."""

from datetime import datetime, timedelta
from typing import Any

MAX_SUPPORT_HOURS = 24
MAX_ADMIN_HOURS = 3
SCOPE_FIELDS = ("login_as_administrator", "site_domains", "site_release_group", "bench_ssh")
IMMUTABLE_FIELDS = ("requested_by", "requested_team", "target_team", "reason")


class ConsentDenied(ValueError):
	"""The request does not carry valid, bounded customer consent."""


def _require(condition: bool) -> None:
	if not condition:
		raise ConsentDenied("Valid customer consent is required for support access.")


def _enabled(record: dict[str, Any], field: str) -> bool:
	value = record.get(field, 0)
	_require(value in (0, 1, "0", "1", None))
	return value in (1, "1")


def _sites(record: dict[str, Any]) -> frozenset[str]:
	rows = record.get("resources")
	_require(isinstance(rows, (list, tuple)) and 0 < len(rows) <= 20)
	sites = set()
	for row in rows:
		_require(isinstance(row, dict) and row.get("document_type") == "Site")
		name = row.get("document_name")
		_require(isinstance(name, str) and bool(name.strip()))
		sites.add(name)
	_require(len(sites) == len(rows))
	return frozenset(sites)


def _hours(record: dict[str, Any]) -> int:
	value = str(record.get("allowed_for", ""))
	_require(value in {"3", "6", "12", "24"})
	hours = int(value)
	maximum = MAX_ADMIN_HOURS if _enabled(record, "login_as_administrator") else MAX_SUPPORT_HOURS
	_require(hours <= maximum)
	return hours


def _shape(record: dict[str, Any]) -> None:
	for field in IMMUTABLE_FIELDS:
		value = record.get(field)
		_require(isinstance(value, str) and bool(value.strip()))
	_require(len(record["reason"]) <= 2000)
	_require(record["requested_by"] not in {"Guest", "Administrator"})
	_require(record["requested_team"] != record["target_team"])
	_sites(record)
	for field in SCOPE_FIELDS:
		_enabled(record, field)
	# SSH and release groups can expose other customers. This MVP grants site scope only.
	_require(not _enabled(record, "bench_ssh") and not _enabled(record, "site_release_group"))
	if _enabled(record, "login_as_administrator"):
		_require(len(_sites(record)) == 1 and not _enabled(record, "site_domains"))
	_hours(record)


def validate_change(
	current: dict[str, Any],
	previous: dict[str, Any] | None,
	*,
	actor: str,
	customer_owner: str,
	now: datetime,
) -> None:
	"""Validate a save using the customer owner read from the authoritative Team record."""
	_shape(current)
	_require(bool(actor) and actor != "Guest")
	if previous is None:
		_require(current["status"] == "Pending")
		_require(current["requested_by"] == actor)
		_require(current.get("access_allowed_till") is None)
		return

	for field in IMMUTABLE_FIELDS:
		_require(current.get(field) == previous.get(field))
	for field in SCOPE_FIELDS:
		_require(_enabled(current, field) == _enabled(previous, field))
	_require(_sites(current) == _sites(previous))
	old, new = previous.get("status"), current.get("status")
	if old == "Pending" and new in {"Accepted", "Rejected"}:
		_require(actor == customer_owner and actor != current["requested_by"])
	elif old == "Accepted" and new == "Revoked":
		_require(actor == customer_owner and actor != current["requested_by"])
	elif old == "Accepted" and new == "Forfeited":
		_require(actor == current["requested_by"])
	else:
		_require(old == new and actor in {customer_owner, current["requested_by"]})

	if old == "Pending" and new == "Accepted":
		expiry = current.get("access_allowed_till")
		_require(isinstance(expiry, datetime))
		_require(now < expiry <= now + timedelta(hours=_hours(current)))
	else:
		_require(current.get("access_allowed_till") == previous.get("access_allowed_till"))
		if current.get("allowed_for") != previous.get("allowed_for"):
			_require(old == new == "Pending" and actor == customer_owner)


def authorize(
	grant: dict[str, Any],
	*,
	actor: str,
	team: str,
	site: str,
	administrator: bool,
	now: datetime,
) -> str:
	"""Recheck a persisted consent for each use, including the exact expiry boundary."""
	_shape(grant)
	_require(grant.get("status") == "Accepted")
	_require(grant["requested_by"] == actor and grant["requested_team"] == team)
	_require(site in _sites(grant))
	_require(_enabled(grant, "login_as_administrator") == administrator)
	end = grant.get("access_allowed_till")
	_require(isinstance(end, datetime) and now < end)
	_require(bool(grant.get("name")))
	return grant["name"]
