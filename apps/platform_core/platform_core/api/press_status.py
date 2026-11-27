"""Dedicated signed Press status ingress. Contract: platform_core-ai.openapi.yaml."""

import frappe
from frappe.rate_limiter import rate_limit

from platform_core.ai import press_events


# HMAC authentication and strict payload validation run in press_events.receive before the only inbox write.
@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep: frappe-missing-permission
@rate_limit(limit=120, seconds=60)
def receive():
	"""Persist authenticated Press status metadata once. Grants no user or MCP access."""
	return press_events.receive()
