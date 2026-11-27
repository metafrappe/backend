"""HTTP entry points for tour progress (G-139). The rules are in `platform_core.shell.tour_rules`.

Contract: `contracts/platform_core-tour.openapi.yaml`.
Each user reads and writes only their own progress. The body never names a user.
"""

from typing import Any

import frappe
from frappe.rate_limiter import rate_limit

from platform_core.shell.http import require_session
from platform_core.shell.request_policy import BootstrapQuery, validate_query
from platform_core.shell.tour import get_progress, save_progress


class TourProgressQuery(BootstrapQuery):
	tour_id: str


class TourProgressBody(BootstrapQuery):
	tour_id: Any
	version: Any
	status: Any
	current_step: Any = None
	seen_steps: Any
	restart: bool = False


# The service reads only the session user's own record.
@frappe.whitelist(methods=["GET"])  # nosemgrep: frappe-missing-permission
@rate_limit(limit=240, seconds=60, user_based=True, ip_based=False, methods=["GET"])
def get_tour_progress(tour_id: str = "") -> dict | None:
	"""Read the current user's progress of one tour. Null on the first visit. Changes no record."""
	user = require_session()
	validate_query(TourProgressQuery)
	answer = get_progress(user, tour_id)
	if answer is None:
		# Frappe omits message when a whitelisted function returns None. Keep the contract stable.
		frappe.response["message"] = None
	return answer


# The service writes only the session user's own record. Unknown keys such as `user` are rejected.
@frappe.whitelist(methods=["POST"])  # nosemgrep: frappe-missing-permission
@rate_limit(limit=120, seconds=60, user_based=True, ip_based=False, methods=["POST"])
def save_tour_progress(
	tour_id: str = "",
	version: int | str = 0,
	status: str = "",
	current_step: str | None = None,
	seen_steps: list | None = None,
	restart: bool = False,
) -> dict:
	"""Merge and save the current user's progress of one tour. Returns the stored progress."""
	user = require_session()
	validate_query(TourProgressBody)
	return save_progress(
		user,
		{
			"tour_id": tour_id,
			"version": version,
			"status": status,
			"current_step": current_step,
			"seen_steps": seen_steps,
		},
		restart=restart is True,
	)
