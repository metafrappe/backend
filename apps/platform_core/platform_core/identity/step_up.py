"""Sensitive operations need a fresh and strong sign-in (G-163, item 2).

The list is the `x-sensitive-operations` extension of contracts/platform_core-identity.openapi.yaml.
`tests/test_step_up.py` keeps this table and the contract equal, and checks that every listed method calls
`require` in its first statement.

The check reads two values that the Keycloak callback wrote into the Frappe session record (`sign_in.py`):
`keycloak_acr` (level of authentication) and `keycloak_auth_time` (time of the last real sign-in at Keycloak).
A session whose sign-in is older than the limit, or whose level is too low, gets 403
`reauthentication_required` with a sign-in address that forces a fresh strong sign-in.

Requests with a token (`Authorization` header) carry no session record. They cannot call these methods.
A direct Python call without an HTTP request is server code and is not checked here.
"""

import time
from dataclasses import dataclass
from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.utils import get_url

from platform_core.identity import helpers

# Same value as press_tr account deletion (`REAUTHENTICATION_TTL`).
DEFAULT_MAX_AGE = 300
# Keycloak's clock can run a little ahead of the tenant site.
CLOCK_LEEWAY = 30
ERROR_CODE = "reauthentication_required"
START_LOGIN_PATH = "/api/method/platform_core.api.auth.start_login"


@dataclass(frozen=True)
class Rule:
	min_acr: str
	max_age: int = DEFAULT_MAX_AGE


SENSITIVE_OPERATIONS: dict[str, Rule] = {
	"platform_core.api.access.set_field_level": Rule(helpers.ADMIN_ACR),
	"platform_core.api.access.set_level_access": Rule(helpers.ADMIN_ACR),
	# End users approve their own AI proposals and have no strong key: a fresh sign-in at their level.
	"platform_core.api.ai.approve_proposal": Rule(helpers.EMPLOYEE_ACR),
	"platform_core.api.ai.purge_logs": Rule(helpers.ADMIN_ACR),
	"platform_core.api.model.save_connection": Rule(helpers.ADMIN_ACR),
	"platform_core.api.model.clear_api_credential": Rule(helpers.ADMIN_ACR),
	"platform_core.api.model.purge_usage": Rule(helpers.ADMIN_ACR),
}


class ReauthenticationRequired(frappe.PermissionError):
	http_status_code = 403


def reauthentication_url(rule: Rule) -> str:
	"""Sign-in address of this site. `start_login` passes the three values on to Keycloak."""
	query = urlencode({"prompt": "login", "max_age": 0, "acr_values": rule.min_acr})
	return get_url(f"{START_LOGIN_PATH}?{query}")


def require(method: str) -> None:
	"""Stops the request unless its cookie session has a fresh sign-in at the required level."""
	rule = SENSITIVE_OPERATIONS[method]
	request = getattr(frappe.local, "request", None)
	if request is None:
		return
	if _fresh_enough(request, rule):
		return
	frappe.local.response["error"] = ERROR_CODE
	frappe.local.response["reauthentication_url"] = reauthentication_url(rule)
	raise ReauthenticationRequired(
		_("Sign in again to continue this operation.", context="platform_core.identity")
	)


def _fresh_enough(request, rule: Rule) -> bool:
	session = getattr(frappe.local, "session", None) or {}
	sid = session.get("sid")
	if not sid or sid == "Guest" or request.cookies.get("sid") != sid:
		return False
	if frappe.get_request_header("Authorization"):
		return False
	data = session.get("data") or {}
	if helpers.acr_level(data.get("keycloak_acr")) < helpers.acr_level(rule.min_acr):
		return False
	auth_time = data.get("keycloak_auth_time")
	if type(auth_time) is not int:
		return False
	age = int(time.time()) - auth_time
	return -CLOCK_LEEWAY <= age <= rule.max_age
