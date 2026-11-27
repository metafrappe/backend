"""Site-local Marketplace plan and application feature decisions."""

from datetime import datetime
from functools import wraps
from time import time
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
import requests

CACHE_SECONDS = 60
_CACHE_PREFIX = "platform_core:subscription"
_GENERATION_KEY = f"{_CACHE_PREFIX}:generation"
_PRESS_METHOD = "/api/method/press.api.developer.marketplace.get_subscription_info"


def _settings() -> dict:
	return frappe.conf.get("platform_subscriptions", {})


def _generation() -> str:
	return frappe.cache.get_value(_GENERATION_KEY, use_local_cache=False) or "initial"


def _cache_key(app: str, generation: str) -> str:
	return f"{_CACHE_PREFIX}:{generation}:{app}"


def subscription_update_hook() -> None:
	"""Invalidate the site snapshot after a trusted subscription/configuration change."""
	previous = _generation()
	frappe.cache.set_value(_GENERATION_KEY, uuid4().hex)
	for app in _settings():
		frappe.cache.delete_value(_cache_key(app, previous))


def meta_changed(doc=None, method=None) -> None:
	frappe.db.after_commit.add(subscription_update_hook)


def _fetch_plan(app: str) -> tuple[str | None, bool, bool] | None:
	base = frappe.conf.get("press_subscription_url")
	secret = frappe.conf.get(f"sk_{app}")
	if not base or not secret:
		return None

	try:
		url = urlsplit(base)
		if url.scheme != "https" or not url.hostname or url.username or url.password:
			return None
		if url.query or url.fragment or url.path not in {"", "/"}:
			return None
		response = requests.post(
			base.rstrip("/") + _PRESS_METHOD,
			json={"secret_key": secret},
			timeout=3,
			allow_redirects=False,
		)
		if response.status_code == 401:
			# Press accepts the subscription key only while its Subscription is enabled.
			return None, False, True
		if response.status_code != 200:
			return None
		payload = response.json()
	except (requests.RequestException, ValueError):
		return None

	subscription_info = payload.get("message") if isinstance(payload, dict) else None
	if not isinstance(subscription_info, dict):
		return None
	# Marketplace subscriptions may omit site. In that case Press identifies the
	# tenant through the app-specific key it placed in this site's configuration.
	if (
		subscription_info.get("site") not in (None, "", frappe.local.site)
		or subscription_info.get("document_name") != app
	):
		return None
	plan = subscription_info.get("plan")
	enabled = subscription_info.get("enabled")
	if not isinstance(plan, str) or not plan or enabled not in (0, 1):
		return None
	return plan, bool(enabled), not enabled


def _plan_snapshot(app: str) -> tuple[str | None, bool, bool]:
	generation = _generation()
	key = _cache_key(app, generation)
	snapshot = frappe.cache.get_value(key, expires=True, use_local_cache=False)
	if snapshot is None:
		snapshot = _fetch_plan(app)
		if _generation() != generation:
			# A fetch crossing an invalidation cannot grant access.
			return None, False, False
		ttl = CACHE_SECONDS if snapshot is not None else 5
		snapshot = snapshot or (None, False, False)
		frappe.cache.set_value(key, snapshot, expires_in_sec=ttl)
	return snapshot


def _trial_ended(app: str, settings: dict, plan: str | None) -> bool:
	trial_plan = settings.get("trial_plan")
	if trial_plan and plan and plan != trial_plan:
		return False
	deadline = settings.get("trial_ends_at")
	if deadline is not None:
		return type(deadline) not in (int, float) or not time() < deadline

	# Press writes this shared config entry for prepaid trials. Bind it to the app.
	subscription = frappe.conf.get("subscription") or {}
	secret = frappe.conf.get(f"sk_{app}")
	expiry = subscription.get("expiry")
	if not secret or subscription.get("secret_key") != secret or expiry is None:
		return False
	try:
		expiry_time = datetime.fromisoformat(expiry)
		if expiry_time.tzinfo is None:
			expiry_time = expiry_time.replace(tzinfo=ZoneInfo(frappe.utils.get_system_timezone()))
		return time() >= expiry_time.timestamp()
	except (TypeError, ValueError, OverflowError, ZoneInfoNotFoundError):
		return True


def _decision(app: str, feature: str, operation: str) -> dict:
	settings = _settings().get(app)
	installed = app in frappe.get_installed_apps(_ensure_on_bench=True)
	managed = settings is not None and installed
	plan, subscribed, suspended = _plan_snapshot(app) if managed else (None, False, False)
	settings = settings or {}
	enabled = managed and settings.get("enabled") is True
	plan_rules = settings.get("plans", {}).get(plan)
	trial_ended = managed and _trial_ended(app, settings, plan)
	read_only = bool(managed and (trial_ended or (plan_rules and plan_rules.get("read_only"))))
	entitled = bool(enabled and subscribed and plan_rules and feature in plan_rules.get("features", ()))

	# Export still needs the application's ordinary session and record checks.
	allowed = {
		"read": entitled,
		"write": entitled and not read_only,
		"export": managed,
	}.get(operation, False)

	return {
		"allowed": allowed,
		"plan": plan,
		"state": {
			"installed": installed,
			"subscribed": subscribed,
			"enabled": enabled,
			"suspended": suspended,
			"read_only": read_only,
		},
	}


def has_feature(app: str, feature: str, *, operation: str = "write") -> bool:
	"""Check the application gate. This is independent of record permissions."""
	return _decision(app, feature, operation)["allowed"]


def require_feature(app: str, feature: str, *, operation: str = "write"):
	"""Apply the gate to a server action before running its existing handler."""

	def decorate(function):
		@wraps(function)
		def guarded(*args, **kwargs):
			if not has_feature(app, feature, operation=operation):
				raise frappe.PermissionError(frappe._("This feature is unavailable for this action."))
			return function(*args, **kwargs)

		return guarded

	return decorate


# Only the current site's plan and application flags are exposed.
@frappe.whitelist(methods=["GET"])
def feature_decision(app: str, feature: str, operation: str = "write") -> dict:
	"""Return the same application decision used by server-side feature guards."""
	if frappe.session.user in (None, "", "Guest"):
		raise frappe.PermissionError(frappe._("Log in to check feature access."))
	doctype = (_settings().get(app) or {}).get("permission_doctype")
	if not doctype:
		raise frappe.PermissionError(frappe._("Feature status is unavailable for this app."))
	if not frappe.has_permission(doctype, ptype="read", print_logs=False):
		frappe.throw(frappe._("You cannot read this app's records."), frappe.PermissionError)
	frappe.local.response_headers["Cache-Control"] = "private, no-store"
	return _decision(app, feature, operation)
