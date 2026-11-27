"""HTTP entry point for the application module manifest."""

import frappe
from frappe.rate_limiter import rate_limit

from platform_core.ai.registry import app_tool_references
from platform_core.shell.app_modules import read_manifest
from platform_core.shell.http import require_session


# require_session authenticates the site's session cookie. No record selector is accepted.
@frappe.whitelist(methods=["GET"])  # nosemgrep: frappe-missing-permission
@rate_limit(limit=120, seconds=60, user_based=True, ip_based=False, methods=["GET"])
def get_manifest() -> dict:
	"""Return public module metadata for the current site and user's visible tools."""
	require_session()
	return read_manifest(app_tool_references())
