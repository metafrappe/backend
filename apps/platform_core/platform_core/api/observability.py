"""G-149 RUM collection point. The rules are in `platform_core.observability.rum`.

Contract: `backend/contracts/platform_core-observability.openapi.yaml`.
"""

import json

import frappe
from frappe.rate_limiter import rate_limit

from platform_core.observability import rum


# The sign-in page is a measured journey too, so guests may send a beacon.
# The beacon names no person and the server adds none, so there is no record permission to check.
@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep: frappe-missing-permission
@rate_limit(limit=120, seconds=60, methods=["POST"])
def collect_rum(**beacon) -> dict:
	"""Store one web-vitals beacon after the checks. Refuses any field that is not in the contract."""
	# Frappe's v1 method route copies the method path into `cmd`; it is not part of the beacon.
	beacon.pop("cmd", None)
	if isinstance(beacon.get("metrics"), str):
		try:
			beacon["metrics"] = json.loads(beacon["metrics"])
		except ValueError:
			beacon["metrics"] = None
	rum.store(rum.clean_beacon(beacon))
	return {"stored": True}
