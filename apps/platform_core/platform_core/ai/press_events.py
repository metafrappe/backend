"""O-57 signed Press event protocol. No user identity is created here."""

import hashlib
import hmac
import json
import logging
import re
import time
from collections.abc import Mapping
from datetime import datetime, timedelta

MAX_BODY_BYTES = 16_384
EVENT_TYPES = {
	"Agent Job": "press.job_status.changed.v1",
	"Site": "press.job_status.changed.v1",
	"Site Update": "press.job_status.changed.v1",
	"Deploy Candidate Build": "press.deploy_candidate_build.status",
	"New Bench Queue": "press.new_bench_queue.status",
	"Bench": "press.bench.status",
}
DEPLOY_RECORDS = frozenset({"Deploy Candidate Build", "New Bench Queue", "Bench"})
BASE_FIELDS = frozenset(
	{
		"event_id",
		"event_type",
		"occurred_at",
		"record_type",
		"record_name",
		"old_status",
		"new_status",
		"team",
		"site",
		"capture",
	}
)


class RejectedEventError(ValueError):
	"""A request rejected before persistence."""

	def __init__(self, status: int, code: str):
		self.status = status
		self.code = code
		super().__init__(code)


def authenticate(
	body: bytes, headers: Mapping[str, str], keys: dict[str, bytes | str] | None, *, now: int
) -> str:
	"""Authenticate exact transport bytes and return the bound event ID."""
	if isinstance(body, bytes) and len(body) > MAX_BODY_BYTES:
		raise RejectedEventError(413, "event_too_large")
	event_id = headers.get("X-Press-Event-Id", "")
	timestamp = headers.get("X-Press-Timestamp", "")
	signature = headers.get("X-Press-Signature", "")
	key_id = headers.get("X-Press-Key-Id", "")
	secret = keys.get(key_id) if isinstance(keys, dict) and isinstance(key_id, str) else None
	if isinstance(secret, str):
		secret = secret.encode("utf-8")
	valid = (
		isinstance(body, bytes)
		and 0 < len(body) <= MAX_BODY_BYTES
		and isinstance(event_id, str)
		and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event_id)
		and isinstance(timestamp, str)
		and re.fullmatch(r"0|[1-9][0-9]{0,9}", timestamp)
		and isinstance(signature, str)
		and re.fullmatch(r"v1=[0-9a-f]{64}", signature)
		and isinstance(key_id, str)
		and 0 < len(key_id) <= 128
		and isinstance(secret, bytes)
		and len(secret) >= 32
		and type(now) is int
		and abs(now - int(timestamp)) <= 300
	)
	if not valid:
		raise RejectedEventError(401, "invalid_signature")
	message = timestamp.encode("ascii") + b"." + event_id.encode("ascii") + b"." + body
	expected = "v1=" + hmac.new(secret, message, hashlib.sha256).hexdigest()
	if not hmac.compare_digest(expected, signature):
		raise RejectedEventError(401, "invalid_signature")
	return event_id


def _unique_object(pairs):
	result = {}
	for key, value in pairs:
		if key in result:
			raise ValueError("Duplicate field")
		result[key] = value
	return result


def parse_event(body: bytes, event_id: str) -> dict[str, str | None]:
	"""Validate the strict event schema before the inbox is touched."""
	try:
		event = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object)
		if not isinstance(event, dict):
			raise ValueError("Expected object")
		record_type = event.get("record_type")
		if not isinstance(record_type, str) or record_type not in EVENT_TYPES:
			raise ValueError("Unknown record type")
		fields = BASE_FIELDS | ({"group", "candidate", "deploy"} if record_type in DEPLOY_RECORDS else set())
		if event.keys() != fields or event["event_id"] != event_id:
			raise ValueError("Invalid fields")
		if event["capture"] not in {"hook", "reconcile"}:
			raise ValueError("Invalid capture mode")
		if event["event_type"] != EVENT_TYPES[record_type]:
			raise ValueError("Wrong event type")
		for field in fields - {"event_id", "event_type", "occurred_at", "record_type"}:
			value = event[field]
			if value is None and field not in {"record_name", "new_status"}:
				continue
			if not isinstance(value, str) or len(value) > 140:
				raise ValueError("Invalid field value")
			if field in {"record_name", "new_status"} and not value:
				raise ValueError("Empty required field")
		occurred_at = event["occurred_at"]
		if not isinstance(occurred_at, str) or not re.fullmatch(
			r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|\+00:00)", occurred_at
		):
			raise ValueError("Invalid event time")
		instant = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
		if instant.utcoffset() != timedelta(0):
			raise ValueError("Event time must use UTC")
		return event
	except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
		raise RejectedEventError(400, "invalid_event") from error


CANONICAL_PATH = "/api/method/platform_core.api.press_status.receive"
METHOD = "platform_core.api.press_status.receive"


def _authenticated_body():
	import frappe

	request = frappe.request
	if (
		request.path != CANONICAL_PATH
		or request.method != "POST"
		or request.args
		or not request.is_secure
		or request.mimetype != "application/octet-stream"
	):
		raise RejectedEventError(401, "invalid_transport")
	if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
		raise RejectedEventError(413, "event_too_large")
	body = request.get_data(cache=True)
	event_id = authenticate(
		body, request.headers, frappe.conf.get("press_job_status_keys"), now=int(time.time())
	)
	return body, event_id


def _log_rejection(code):
	logging.getLogger("platform_core.press_status").warning("Press status rejected: %s", code)


def receive():
	"""Accept an authenticated event without creating a user session."""
	import frappe

	try:
		body, event_id = _authenticated_body()
		event = parse_event(body, event_id)
	except RejectedEventError as error:
		_log_rejection(error.code)
		frappe.local.response["http_status_code"] = error.status
		return {"error": error.code}
	# The primary key is the event ID. SQL uniqueness handles concurrent retries.
	# This is a narrow internal write after HMAC and strict schema validation.
	document = frappe.get_doc(
		{
			"doctype": "PLT Press Event Inbox",
			"event_id": event_id,
			"payload": json.dumps(event, separators=(",", ":")),
		}
	)
	# Only this private inbox write follows verified HMAC and strict metadata validation.
	document.insert(ignore_permissions=True, ignore_if_duplicate=True)  # nosemgrep: frappe-ignore-permissions
	return {"accepted": True, "event_id": event_id}


def guard_request():
	"""Keep the signed path isolated from Frappe legacy cmd dispatch."""
	import frappe

	request = frappe.request
	paths = {CANONICAL_PATH, "/api/v1/method/" + METHOD, "/api/v2/method/" + METHOD}
	if request.path.rstrip("/") not in paths and frappe.form_dict.get("cmd") != METHOD:
		return
	from frappe.rate_limiter import rate_limit

	# A separate stable counter also includes requests denied before endpoint dispatch.
	rate_limit(limit=120, seconds=60, endpoint="platform_core.press_status.ingress")(_guard_authenticated)()


def _guard_authenticated():
	import frappe

	try:
		_authenticated_body()
	except RejectedEventError as error:
		_log_rejection(error.code)
		exception = frappe.AuthenticationError(error.code)
		exception.http_status_code = error.status
		raise exception from None
