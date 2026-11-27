"""Shared, non-authorizing correlation for tenant AI records."""

import hashlib

import frappe

CONVERSATION_HEADER = "Mcp-Conversation-Id"


def session_id() -> str | None:
	"""Hash the optional client conversation header; never persist its raw value."""
	value = frappe.get_request_header(CONVERSATION_HEADER) if frappe.request else None
	return hashlib.sha256(value.encode()).hexdigest() if value else None
