"""The Frappe cookie session follows the Keycloak session, even without a logout notice (G-163, item 3).

Keycloak sends a back-channel logout when its session ends (`sign_out.py`). If that notice is lost, the Frappe
cookie session would stay open. So a cookie request asks Keycloak itself:

- the sign-in keeps the refresh token, encrypted with Frappe's site key (`frappe.utils.password.encrypt`),
- `session_policy.before_request` calls `ensure_active` for every cookie request, background requests included,
- `ensure_active` calls Keycloak's `introspect` endpoint with the refresh token as the `site-tenant1` client,
- the answer is cached for `CACHE_SECONDS`, so most requests do not reach Keycloak,
- `active: false` closes the session at once, the same way the idle timeout does,
- when Keycloak cannot be reached, the last positive answer stays valid for `UNREACHABLE_GRACE_SECONDS`.

The introspection itself never uses `grant_type=refresh_token`: the realm rotates refresh tokens
(`revokeRefreshToken`), and a refresh on every check would replace the token each time.

Design deviation, written into AJA-405: the tenant client's sessions idle out after 3600 seconds
(`client.session.idle.timeout`), and the refresh token expires with them. Introspection alone would then end
every Frappe session one hour after sign-in, also for a user who keeps working. So when Keycloak confirms the
session and the token expires within `REFRESH_BEFORE_EXPIRY_SECONDS`, one request renews it once. A short Redis
lock lets only one request renew. The new token is kept encrypted in Redis, next to the check state.
"""

import time

import frappe

from platform_core.identity import helpers, site_settings

CACHE_SECONDS = 60
UNREACHABLE_GRACE_SECONDS = 300
REFRESH_BEFORE_EXPIRY_SECONDS = 900
REQUEST_TIMEOUT = 3
REFRESH_LOCK_SECONDS = 30
# Check state and renewed tokens outlive the one-hour idle limit of the session.
KEY_TTL = 86400
SESSION_TOKEN_FIELD = "keycloak_refresh_token"
SESSION_CHECKED_FIELD = "keycloak_checked_at"
STATE_PREFIX = "kimlik_kc_check"
TOKEN_PREFIX = "kimlik_kc_refresh"
LOCK_PREFIX = "kimlik_kc_refresh_lock"


def _log():
	return frappe.logger("platform_core.identity", allow_site=True)


class KeycloakUnreachableError(Exception):
	"""No usable answer from Keycloak. The response body is never logged."""


def encrypt_token(token: str) -> str:
	from frappe.utils.password import encrypt

	return encrypt(token)


def decrypt_token(stored: object) -> str | None:
	if not isinstance(stored, str) or not stored:
		return None
	from frappe.utils.password import decrypt

	try:
		return decrypt(stored)
	except Exception:
		return None


def session_values(refresh_token: object) -> dict:
	"""Values the sign-in writes into the Frappe session record. The token is never stored as plain text."""
	token = refresh_token if isinstance(refresh_token, str) and refresh_token else None
	return {
		SESSION_TOKEN_FIELD: encrypt_token(token) if token else None,
		SESSION_CHECKED_FIELD: int(time.time()),
	}


def remember_sign_in(sid: str) -> None:
	"""The sign-in itself is a positive answer from Keycloak."""
	now = int(time.time())
	save_state(sid, checked_at=now, ok_at=now)


def _state_key(sid: str) -> str:
	return f"{STATE_PREFIX}:{sid}"


def _token_key(sid: str) -> str:
	return f"{TOKEN_PREFIX}:{sid}"


def save_state(sid: str, checked_at: int, ok_at: int) -> None:
	frappe.cache.set_value(
		_state_key(sid), {"checked_at": int(checked_at), "ok_at": int(ok_at)}, expires_in_sec=KEY_TTL
	)


def load_state(sid: str) -> dict | None:
	state = frappe.cache.get_value(_state_key(sid), expires=True, use_local_cache=False)
	if not isinstance(state, dict):
		return None
	if type(state.get("checked_at")) is not int or type(state.get("ok_at")) is not int:
		return None
	return state


def forget(sid: str) -> None:
	frappe.cache.delete_value(_state_key(sid))
	frappe.cache.delete_value(_token_key(sid))


def ensure_active(sid: str, data: dict, renew: bool = True) -> bool:
	"""False when the Frappe session must close. Sessions not opened through Keycloak are not checked.

	`renew=False` for background requests: polling must not keep the Keycloak session alive.
	"""
	if not data.get("keycloak_sub"):
		return True
	now = int(time.time())
	state = load_state(sid)
	if (
		state
		and 0 <= now - state["checked_at"] < CACHE_SECONDS
		and now - state["ok_at"] <= UNREACHABLE_GRACE_SECONDS
	):
		return True
	token = _current_token(sid, data)
	if not token:
		return False
	last_ok = state["ok_at"] if state else data.get(SESSION_CHECKED_FIELD)
	last_ok = last_ok if type(last_ok) is int else 0
	try:
		result = introspect(token)
		if not _confirms(result, data):
			# Another request may have renewed the token while this one asked Keycloak about the old one.
			newer = _current_token(sid, data)
			if not newer or newer == token:
				return False
			token, result = newer, introspect(newer)
			if not _confirms(result, data):
				return False
	except KeycloakUnreachableError:
		save_state(sid, checked_at=now, ok_at=last_ok)
		return bool(last_ok) and now - last_ok <= UNREACHABLE_GRACE_SECONDS
	save_state(sid, checked_at=now, ok_at=now)
	if renew:
		_renew_if_expiring(sid, token, result, now)
	return True


def _confirms(result: dict, data: dict) -> bool:
	if result.get("active") is not True:
		return False
	keycloak_sid = data.get("keycloak_sid")
	return not (keycloak_sid and result.get("sid") and result.get("sid") != keycloak_sid)


def _current_token(sid: str, data: dict) -> str | None:
	renewed = frappe.cache.get_value(_token_key(sid), expires=True, use_local_cache=False)
	return decrypt_token(renewed) or decrypt_token(data.get(SESSION_TOKEN_FIELD))


def _endpoint(suffix: str) -> tuple[str, frappe._dict]:
	settings = site_settings.get()
	return helpers.realm_url(settings.internal_url, settings.realm) + suffix, settings


def introspect(token: str) -> dict:
	"""RFC 7662 introspection of the refresh token. Only the configured Keycloak is called (G-13)."""
	import requests

	try:
		url, settings = _endpoint("/protocol/openid-connect/token/introspect")
	except Exception as error:
		raise KeycloakUnreachableError("settings missing") from error
	try:
		response = requests.post(
			url,
			data={
				"token": token,
				"token_type_hint": "refresh_token",
				"client_id": settings.client_id,
				"client_secret": settings.client_secret,
			},
			headers={"Accept": "application/json"},
			timeout=REQUEST_TIMEOUT,
		)
	except requests.RequestException as error:
		raise KeycloakUnreachableError("request failed") from error
	if response.status_code != 200:
		# A wrong client secret answers 401 and would end every session after the grace time. Log the status only.
		_log().warning("Keycloak introspection answered HTTP %s", response.status_code)
		raise KeycloakUnreachableError(f"status {response.status_code}")
	try:
		body = response.json()
	except ValueError as error:
		raise KeycloakUnreachableError("invalid json") from error
	if not isinstance(body, dict) or not isinstance(body.get("active"), bool):
		raise KeycloakUnreachableError("unexpected answer")
	return body


def _renew_if_expiring(sid: str, token: str, result: dict, now: int) -> None:
	expires_at = result.get("exp")
	if type(expires_at) is not int or expires_at - now > REFRESH_BEFORE_EXPIRY_SECONDS:
		return
	lock = frappe.cache.make_key(f"{LOCK_PREFIX}:{sid}")
	if not frappe.cache.set(lock, 1, nx=True, ex=REFRESH_LOCK_SECONDS):
		return
	renewed = _renew(token)
	if not renewed:
		return
	stored = encrypt_token(renewed)
	frappe.cache.set_value(_token_key(sid), stored, expires_in_sec=KEY_TTL)
	# The session record follows the rotation too, so a cache clear or a Redis restart keeps the new token.
	session_obj = getattr(frappe.local, "session_obj", None)
	if session_obj is not None and getattr(session_obj, "sid", None) == sid:
		frappe.local.session.data[SESSION_TOKEN_FIELD] = stored
		session_obj.update(force=True)


def _renew(token: str) -> str | None:
	"""One refresh grant. A failure keeps the old token: the next introspection decides."""
	import requests

	try:
		url, settings = _endpoint("/protocol/openid-connect/token")
		response = requests.post(
			url,
			data={
				"grant_type": "refresh_token",
				"refresh_token": token,
				"client_id": settings.client_id,
				"client_secret": settings.client_secret,
			},
			headers={"Accept": "application/json"},
			timeout=REQUEST_TIMEOUT,
		)
		body = response.json() if response.status_code == 200 else {}
	except Exception as error:
		# The renewal may have reached Keycloak. The next introspection decides about the session.
		_log().warning("Keycloak token renewal failed: %s", type(error).__name__)
		return None
	if response.status_code != 200:
		_log().warning("Keycloak token renewal answered HTTP %s", response.status_code)
	renewed = body.get("refresh_token") if isinstance(body, dict) else None
	return renewed if isinstance(renewed, str) and renewed else None
