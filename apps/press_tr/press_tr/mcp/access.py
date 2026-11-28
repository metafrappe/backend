"""Who may call the press_tr MCP server, and from where."""

import ipaddress

import frappe
from frappe import _

SERVICE_USER_KEY = "press_tr_mcp_service_user"
ALLOWED_NETWORKS_KEY = "press_tr_mcp_allowed_networks"
REQUIRED_ROLE = "System Manager"


def check_request() -> None:
	"""Raise `frappe.AuthenticationError` unless the request may use the server."""
	_check_enabled()
	_check_service_account()
	_check_network()


def _refuse(message: str) -> None:
	frappe.throw(message, frappe.AuthenticationError)


def _check_enabled() -> None:
	value = frappe.get_value("Press Settings", None, "enable_mcp")
	if str(value).strip().lower() not in {"1", "true", "yes"}:
		_refuse(_("Press MCP is not enabled.", context="press_tr"))


def _check_service_account() -> None:
	service_user = (frappe.conf.get(SERVICE_USER_KEY) or "").strip()
	user = frappe.session.user
	if not service_user or user != service_user:
		_refuse(_("Only the MCP service account may use this server.", context="press_tr"))
	if frappe.get_cached_value("User", user, "user_type") != "System User":
		_refuse(_("The MCP service account must be a System User.", context="press_tr"))
	if REQUIRED_ROLE not in frappe.get_roles(user):
		_refuse(_("The MCP service account needs the System Manager role.", context="press_tr"))


def allowed_networks() -> list:
	value = frappe.conf.get(ALLOWED_NETWORKS_KEY) or []
	if isinstance(value, str):
		value = value.split(",")
	networks = []
	for item in value:
		text = str(item).strip()
		if not text:
			continue
		try:
			networks.append(ipaddress.ip_network(text, strict=False))
		except ValueError:
			# A malformed entry allows nothing. The other entries still apply.
			continue
	return networks


def _check_network() -> None:
	address = getattr(frappe.local, "request_ip", None)
	try:
		ip = ipaddress.ip_address(str(address or "").strip())
	except ValueError:
		ip = None
	if ip is None or not any(ip in network for network in allowed_networks()):
		_refuse(_("This network may not use the MCP server.", context="press_tr"))
