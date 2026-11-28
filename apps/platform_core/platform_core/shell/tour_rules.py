"""G-139: rules of per-user tour progress. Pure functions, no Frappe import.

The frontend tour engine owns the tour content. The server stores only progress:
the version the user last saw, the status, the step to resume from and the seen steps.
Contract: `contracts/platform_core-tour.openapi.yaml`.
"""

import hashlib
import re

IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
STATUSES = ("active", "snoozed", "skipped", "completed")
MAX_VERSION = 100_000
MAX_SEEN_STEPS = 200
FIELDS = ("tour_id", "version", "status", "current_step", "seen_steps")


class TourProgressError(ValueError):
	"""The progress payload breaks the contract. `code` names the field."""

	def __init__(self, code: str):
		super().__init__(code)
		self.code = code


def _identifier(value: object, code: str) -> str:
	if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or ".." in value:
		raise TourProgressError(code)
	return value


def _version(value: object) -> int:
	if isinstance(value, bool):
		raise TourProgressError("version")
	if isinstance(value, str) and value.isdigit():
		value = int(value)
	if not isinstance(value, int) or not 1 <= value <= MAX_VERSION:
		raise TourProgressError("version")
	return value


def _unique(steps: list[str]) -> list[str]:
	return list(dict.fromkeys(steps))


def normalize_progress(payload: dict) -> dict:
	"""Check a progress payload and return it in the stored shape."""
	if not isinstance(payload, dict) or set(payload) != set(FIELDS):
		raise TourProgressError("fields")
	status = payload["status"]
	if status not in STATUSES:
		raise TourProgressError("status")
	current = payload["current_step"]
	seen = payload["seen_steps"]
	if not isinstance(seen, list):
		raise TourProgressError("seen_steps")
	seen = _unique([_identifier(step, "seen_steps") for step in seen])
	if len(seen) > MAX_SEEN_STEPS:
		raise TourProgressError("seen_steps")
	return {
		"tour_id": _identifier(payload["tour_id"], "tour_id"),
		"version": _version(payload["version"]),
		"status": status,
		"current_step": _identifier(current, "current_step") if current else None,
		"seen_steps": seen,
	}


def merge_progress(stored: dict | None, incoming: dict, *, restart: bool = False) -> dict:
	"""Merge a checked payload into the stored progress.

	Seen steps are never forgotten, so an older tab cannot erase progress.
	A lower version keeps the stored version, status and step. Restart replaces everything.
	"""
	if stored is None or restart:
		return dict(incoming)
	seen = _unique([*stored["seen_steps"], *incoming["seen_steps"]])[:MAX_SEEN_STEPS]
	if incoming["version"] < stored["version"]:
		return {**stored, "seen_steps": seen}
	return {**incoming, "seen_steps": seen}


def progress_name(user: str, tour_id: str) -> str:
	"""Stable document name for one user and one tour. The email does not appear in it."""
	digest = hashlib.sha256(f"{user}\n{tour_id}".encode()).hexdigest()[:32]
	return f"TP-{digest}"
