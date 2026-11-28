"""Tenant support session bound to customer consent on Press (G-18, O-65).

- `start` exchanges a single-use Press ticket for a session of one limited local user.
- `check_request` asks Press on every request of that user whether the consent still holds.
  Expiry, revocation, a transferred site, a lost support role or an unreachable Press end the session.
  It runs as an auth hook after the credential hooks, so it sees the final user of every request.
  The support user may use only its cookie session. Tokens, API keys and realtime sockets are refused:
  an open socket would keep receiving events after the consent ends.
- The support user must not be Administrator and must not hold an administrator role.
  An Administrator session needs its own consent and is not opened here.

Site config keys: `support_press_url` (private https address of Press, O-55) and
`support_session_user` (an existing, enabled, limited tenant user).
"""

import http.client
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import frappe
from frappe import _

PRESS_URL_KEY = "support_press_url"
SUPPORT_USER_KEY = "support_session_user"
CACHE_PREFIX = "plt_support_session:sid:"
REDEEM_METHOD = "press_tr.api.support.redeem_tenant_session"
CHECK_METHOD = "press_tr.api.support.check_tenant_session"
ADMINISTRATOR_ROLES = frozenset({"Administrator", "System Manager"})
TIMEOUT_SECONDS = 3
MAX_RESPONSE_BYTES = 16 * 1024
MAX_SECRET_LENGTH = 128
REALTIME_METHOD = "frappe.realtime.get_user_info"
REALTIME_PATHS = frozenset(
	prefix + REALTIME_METHOD for prefix in ("/api/method/", "/api/v1/method/", "/api/v2/method/")
)


class _NoRedirect(HTTPRedirectHandler):
	def redirect_request(self, req, fp, code, msg, headers, newurl):
		# The request carries a site-bound secret for the configured host only.
		return None


_OPENER = build_opener(_NoRedirect())


def deny() -> None:
	frappe.throw(
		_("The support session is not authorized.", context="platform_core.identity"), frappe.PermissionError
	)


def _press_url() -> str:
	base = frappe.conf.get(PRESS_URL_KEY)
	if not isinstance(base, str) or any(ord(char) <= 32 or ord(char) == 127 for char in base):
		deny()
	address = urlsplit(base)
	if (
		address.scheme != "https"
		or not address.hostname
		or address.username is not None
		or address.password is not None
		or address.query
		or address.fragment
	):
		deny()
	return base.rstrip("/")


def _call_press(method: str, data: dict) -> dict:
	"""POST to Press. Any failure, including an unreachable Press, is a refusal."""
	request = Request(
		f"{_press_url()}/api/method/{method}",
		data=json.dumps(data).encode(),
		headers={"Content-Type": "application/json", "Accept": "application/json"},
		method="POST",
	)
	try:
		with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
			if response.status != 200:
				deny()
			body = response.read(MAX_RESPONSE_BYTES + 1)
	except (HTTPError, URLError, TimeoutError, OSError, http.client.HTTPException):
		deny()
	if len(body) > MAX_RESPONSE_BYTES:
		deny()
	try:
		message = json.loads(body).get("message")
	except (ValueError, AttributeError):
		deny()
	if not isinstance(message, dict):
		deny()
	return message


def _support_user() -> str:
	user = frappe.conf.get(SUPPORT_USER_KEY)
	if not isinstance(user, str) or not user or user in {"Administrator", "Guest"}:
		deny()
	if not frappe.db.get_value("User", user, "enabled"):
		deny()
	if ADMINISTRATOR_ROLES.intersection(frappe.get_roles(user)):
		deny()
	return user


def _seconds(reply: dict) -> int:
	value = reply.get("expires_in")
	if type(value) is not int or value <= 0:
		deny()
	return value


def _consent(reply: dict) -> str:
	value = reply.get("consent")
	if not isinstance(value, str) or not value:
		deny()
	return value


def start(ticket: str) -> dict:
	"""Open a support session from a Press ticket. The browser never receives the Press session key."""
	if frappe.session.user not in ("", "Guest"):
		deny()
	user = _support_user()
	if not isinstance(ticket, str) or not 0 < len(ticket) <= MAX_SECRET_LENGTH:
		deny()
	reply = _call_press(REDEEM_METHOD, {"ticket": ticket, "site": frappe.local.site})
	if reply.get("site") != frappe.local.site:
		deny()
	consent, seconds = _consent(reply), _seconds(reply)
	session_key = reply.get("session_key")
	if not isinstance(session_key, str) or not 0 < len(session_key) <= MAX_SECRET_LENGTH:
		deny()
	frappe.local.login_manager.login_as(user)
	frappe.cache.set_value(
		CACHE_PREFIX + frappe.session.sid,
		{"consent": consent, "session_key": session_key, "ends_at": time.time() + seconds},
		expires_in_sec=seconds,
	)
	return {"user": user, "expires_in": seconds}


def _end(sid: str) -> None:
	frappe.cache.delete_value(CACHE_PREFIX + sid)
	from frappe.sessions import delete_session

	delete_session(sid, reason="Support consent ended")
	deny()


def _realtime_request() -> bool:
	request = getattr(frappe.local, "request", None)
	form = getattr(frappe, "form_dict", None) or {}
	path = getattr(request, "path", "") or ""
	return path.rstrip("/") in REALTIME_PATHS or form.get("cmd") == REALTIME_METHOD


def check_request() -> None:
	"""Recheck the consent behind every request of the support user. Other users are untouched."""
	user = frappe.conf.get(SUPPORT_USER_KEY)
	session = getattr(frappe, "session", None)
	if not user or session is None or session.user != user:
		return
	if frappe.get_request_header("Authorization") or _realtime_request():
		deny()
	sid = session.sid
	record = frappe.cache.get_value(CACHE_PREFIX + sid)
	try:
		if not isinstance(record, dict) or time.time() >= record.get("ends_at", 0):
			deny()
		# Roles can change while the session is open. An administrator role ends it.
		_support_user()
		reply = _call_press(CHECK_METHOD, {"session_key": record["session_key"], "site": frappe.local.site})
		if _consent(reply) != record["consent"]:
			deny()
		_seconds(reply)
	except frappe.PermissionError:
		_end(sid)
