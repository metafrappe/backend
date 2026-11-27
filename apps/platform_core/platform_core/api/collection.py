"""HTTP entry points for collection summaries and list pages."""

import frappe
from frappe.rate_limiter import rate_limit

from platform_core.shell.collection import read_list, read_list_query, read_query, read_summary
from platform_core.shell.http import require_session


# read_summary applies DocType and field permissions before the permission-aware list query.
@frappe.whitelist(methods=["GET"])  # nosemgrep: frappe-missing-permission
@rate_limit(limit=120, seconds=60, user_based=True, ip_based=False, methods=["GET"])
def group_summary() -> dict:
	"""Return counts and an optional numeric statistic for visible records."""
	user = require_session()
	return read_summary(read_query(), user)


# read_list checks DocType, parent record and field permissions, then calls frappe.get_list (O-73).
@frappe.whitelist(methods=["GET"])  # nosemgrep: frappe-missing-permission
@rate_limit(limit=120, seconds=60, user_based=True, ip_based=False, methods=["GET"])
def list_records() -> list[dict]:
	"""Return one page of at most 20 readable rows."""
	user = require_session()
	return read_list(read_list_query(), user)
