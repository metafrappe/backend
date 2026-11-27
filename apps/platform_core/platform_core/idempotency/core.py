"""Shared idempotency key layer for new-record and payment endpoints (G-125).

The contract is `contracts/idempotency.md` (AJA-1749). An endpoint opts in with the `idempotent`
decorator. The client sends a lowercase UUID 4 in the `Idempotency-Key` header. The key is valid
together with the organization, the account and the endpoint. The server never returns another
organization's result.

Order of work (contract section 6):

1. The layer writes the key row as `processing` and commits it at once.
2. The endpoint does its work.
3. The layer marks the row `done` in the same transaction as the work's last write.
4. When the work fails, the layer deletes the row, so a retry starts again.

Each reservation carries its own attempt token. A request whose row another request took over
after the lock ran out does not finish its work and does not delete the other request's row.

The decorator commits the key row in the middle of the request. Use it only on top-level
whitelisted endpoints, never on functions that other code calls inside its own transaction.

The row stores no response body. A replay renders the response again from the result record, so
no secret or personal data collects in the key table.

The version condition of contract section 7 (`VersionConflictError`) lives in AJA-1751's
`platform_core/version_check.py`, not here.
"""

import functools
import hashlib
import json
import re
import uuid
from collections.abc import Callable
from datetime import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, get_datetime, now_datetime

KEY_DOCTYPE = "PLT Idempotency Key"
HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
# Translation context of the layer's visible text. It keeps short words such as "Processing" from
# overriding Frappe's own translation of the same English words.
CONTEXT = "platform_core.idempotency"
SERVER_LOG = "platform_core.idempotency"
LOCK_SECONDS = 120
RETENTION_HOURS = 24
RETRY_AFTER_SECONDS = 2
# Request fields that are not part of the body digest (contract section 3).
UNSIGNED_FIELDS = frozenset({"cmd", "csrf_token"})
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
PROCESSING = "processing"
DONE = "done"
ROW_FIELDS = [
	"name",
	"attempt_id",
	"request_digest",
	"status",
	"lock_expires_at",
	"finished_at",
	"result_doctype",
	"result_name",
	"response_status",
]
# Attempts to reserve a key whose row a failed first call deleted in the meantime.
RESERVE_ATTEMPTS = 3


class IdempotencyKeyMissingError(frappe.ValidationError):
	"""The endpoint needs a key and the request has none, or the key is not a lowercase UUID 4."""

	http_status_code = 400


class IdempotencyKeyReusedError(frappe.ValidationError):
	"""The same key came with another body."""

	http_status_code = 422


class IdempotencyInProgressError(frappe.ValidationError):
	"""The first request with this key is still running. The client asks again after 2 seconds."""

	http_status_code = 409


def default_organization() -> str:
	"""On a tenant site the organization is the site itself (contract section 2)."""
	return frappe.local.site


def default_render(doc: Document) -> dict:
	return {"doctype": doc.doctype, "name": doc.name}


def no_permission_check() -> None:
	return None


def idempotent(
	*,
	organization: Callable[[], str] = default_organization,
	permission: Callable[[], None] = no_permission_check,
	render: Callable[[Document], object] = default_render,
):
	"""Make a top-level whitelisted new-record endpoint idempotent.

	The endpoint returns the Document it created.

	- `organization` returns the organization from server state, never from the request body.
	- `permission` raises `frappe.PermissionError` when the user may not call the endpoint. It runs
	  on every call, also before a replay (contract section 2).
	- `render` turns the result record into the response, for the first call and every replay.
	"""

	def decorate(function):
		endpoint = f"{function.__module__}.{function.__qualname__}"

		@functools.wraps(function)
		def wrapper(*args, **kwargs):
			permission()
			return run(
				endpoint=endpoint,
				key=request_key(),
				payload=request_body(args, kwargs),
				handler=lambda: function(*args, **kwargs),
				organization=organization(),
				account=frappe.session.user,
				render=render,
			)

		return wrapper

	return decorate


def request_key() -> str | None:
	request = getattr(frappe.local, "request", None)
	return request.headers.get(HEADER) if request is not None else None


def request_body(args: tuple, kwargs: dict) -> dict:
	"""The body of the HTTP request. Outside a request, the call's own arguments."""
	if getattr(frappe.local, "request", None) is not None:
		return dict(frappe.local.form_dict or {})
	return {"args": list(args), **kwargs}


def digest(payload: dict) -> str:
	"""SHA-256 of the body as JSON with sorted keys. `cmd` and `csrf_token` are left out."""
	body = {key: value for key, value in payload.items() if key not in UNSIGNED_FIELDS}
	text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=plain_value)
	return hashlib.sha256(text.encode()).hexdigest()


def plain_value(value):
	"""JSON form of values that JSON does not know. An upload counts by its content."""
	if hasattr(value, "stream") and hasattr(value, "filename"):
		position = value.stream.tell()
		content = value.stream.read()
		value.stream.seek(position)
		return {"filename": value.filename, "sha256": hashlib.sha256(content).hexdigest()}
	if isinstance(value, datetime | bytes):
		return str(value)
	raise TypeError(f"The request body holds a value of type {type(value).__name__}.")


def key_name(*, organization: str, account: str, endpoint: str, key: str) -> str:
	"""Row name of a key. The four parts together are unique, so the name is their digest."""
	text = "\n".join((organization, account, endpoint, key))
	return hashlib.sha256(text.encode()).hexdigest()


def run(
	*,
	endpoint: str,
	key: str | None,
	payload: dict,
	handler: Callable[[], Document],
	organization: str,
	account: str,
	render: Callable[[Document], object] = default_render,
):
	"""Do the work of `handler` once for this key, or return the first call's result."""
	if not isinstance(key, str) or not UUID4.fullmatch(key):
		frappe.throw(_("Something went wrong. Reload the page.", context=CONTEXT), IdempotencyKeyMissingError)
	if not isinstance(organization, str) or not organization:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	request_digest = digest(payload)
	scope = {"organization": organization, "account": account, "endpoint": endpoint, "key": key}
	claimed = claim(scope, request_digest)
	if isinstance(claimed, dict):
		return replay(claimed, render)
	name, attempt = claimed
	try:
		result = handler()
		if not isinstance(result, Document):
			raise TypeError(f"{endpoint} must return the Document it created.")
		response = render(result)
		finish(name, attempt, result)
	except BaseException:
		release(name, attempt)
		raise
	return response


def claim(scope: dict, request_digest: str) -> tuple[str, str] | frappe._dict:
	"""Reserve the key for this request, or return the finished row of an earlier request.

	A pair of row name and attempt token means the caller does the work. A row is a finished
	earlier request: the caller replays it.
	"""
	for _attempt in range(RESERVE_ATTEMPTS):
		reserved = reserve(digest=request_digest, **scope)
		if reserved is not None:
			return reserved
		row = locked_row(scope)
		if row is None:
			# The first request failed and deleted its row in the meantime. Reserve again.
			continue
		if is_expired(row):
			# A finished key older than 24 hours is an unknown key (contract section 3).
			return row.name, take_over(row.name, request_digest)
		if row.request_digest != request_digest:
			frappe.throw(
				_(
					"This action was sent with different details. Reload the page and try again.",
					context=CONTEXT,
				),
				IdempotencyKeyReusedError,
			)
		if row.status == DONE:
			return row
		if get_datetime(row.lock_expires_at) > now_datetime():
			in_progress()
		# The first request stopped half way and its lock ran out. Take the row over.
		return row.name, take_over(row.name, request_digest)
	in_progress()


def reserve(
	*, organization: str, account: str, endpoint: str, key: str, digest: str
) -> tuple[str, str] | None:
	"""Write the key row as `processing` and commit it (contract section 6, steps 1 and 2).

	Returns the row name and the attempt token, or None when a row for this scope exists. The row
	is written with one plain insert, so a duplicate leaves no message in the response.
	"""
	name = key_name(organization=organization, account=account, endpoint=endpoint, key=key)
	attempt = str(uuid.uuid4())
	moment = now_datetime()
	table = frappe.qb.DocType(KEY_DOCTYPE)
	query = (
		frappe.qb.into(table)
		.columns(
			"name",
			"creation",
			"modified",
			"owner",
			"modified_by",
			"docstatus",
			"organization",
			"account",
			"endpoint",
			"idempotency_key",
			"request_digest",
			"attempt_id",
			"status",
			"lock_expires_at",
			"response_status",
		)
		.insert(
			name,
			moment,
			moment,
			account,
			account,
			0,
			organization,
			account,
			endpoint,
			key,
			digest,
			attempt,
			PROCESSING,
			lock_end(),
			0,
		)
	)
	try:
		query.run()
	except Exception as error:
		if frappe.db.is_duplicate_entry(error):
			return None
		raise
	frappe.db.commit()
	return name, attempt


def locked_row(scope: dict) -> frappe._dict | None:
	"""Read the newest state of the row and lock it. A lock wait or deadlock means "in progress"."""
	filters = {
		"organization": scope["organization"],
		"account": scope["account"],
		"endpoint": scope["endpoint"],
		"idempotency_key": scope["key"],
	}
	try:
		return frappe.db.get_value(KEY_DOCTYPE, filters, ROW_FIELDS, as_dict=True, for_update=True)
	except (frappe.QueryTimeoutError, frappe.QueryDeadlockError):
		frappe.db.rollback()
		in_progress()


def take_over(name: str, request_digest: str) -> str:
	"""Reset a stale row to `processing` under a new attempt token, then commit it.

	The caller holds the row lock and has checked that the row is stale.
	"""
	attempt = str(uuid.uuid4())
	table = frappe.qb.DocType(KEY_DOCTYPE)
	(
		frappe.qb.update(table)
		.set(table.attempt_id, attempt)
		.set(table.status, PROCESSING)
		.set(table.request_digest, request_digest)
		.set(table.lock_expires_at, lock_end())
		.set(table.result_doctype, None)
		.set(table.result_name, None)
		.set(table.response_status, 0)
		.set(table.finished_at, None)
		.where(table.name == name)
		.run()
	)
	frappe.db.commit()
	return attempt


def finish(name: str, attempt: str, result: Document) -> None:
	"""Mark the row `done` in the work's transaction, if this request still owns the row."""
	owner = frappe.db.get_value(KEY_DOCTYPE, name, "attempt_id", for_update=True)
	if owner != attempt:
		# Another request took the row over after the lock ran out. That request does the work.
		in_progress()
	frappe.db.set_value(
		KEY_DOCTYPE,
		name,
		{
			"status": DONE,
			"lock_expires_at": None,
			"response_status": int(frappe.local.response.get("http_status_code") or 200),
			"result_doctype": result.doctype,
			"result_name": result.name,
			"finished_at": now_datetime(),
		},
		update_modified=False,
	)


def release(name: str, attempt: str) -> None:
	"""Undo the work and delete this request's row, so a retry starts again (contract section 4).

	A cleanup failure goes to the server log. The caller raises the original error.
	"""
	try:
		frappe.db.rollback()
		frappe.db.delete(KEY_DOCTYPE, {"name": name, "attempt_id": attempt})
		frappe.db.commit()
	except Exception as error:
		frappe.logger(SERVER_LOG, allow_site=False).warning(
			"Idempotency key cleanup failed: %s", type(error).__name__
		)


def replay(row: frappe._dict, render: Callable[[Document], object]):
	"""Return the first call's result. The read permission is checked again on every replay."""
	result = frappe.get_doc(row.result_doctype, row.result_name, for_update=True)
	if not frappe.has_permission(row.result_doctype, "read", doc=result):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if row.response_status and row.response_status != 200:
		frappe.local.response["http_status_code"] = row.response_status
	frappe.local.response_headers[REPLAYED_HEADER] = "true"
	return render(result)


# BORC(mvp): nothing calls `purge_expired()` yet. Effect: expired key rows stay in the table, and
# each row keeps the user id in its `account` field until it is deleted (G-15). Owner: Team A PO
# decides the schedule; V-9 requires an explicit `cron` decision. Closes when a follow-up task adds
# a `scheduler_events` entry in `platform_core/hooks.py` that runs this function at least daily.
def purge_expired() -> None:
	"""Delete rows older than the 24-hour retention. Nothing schedules this function yet."""
	cutoff = retention_start()
	frappe.db.delete(KEY_DOCTYPE, {"status": DONE, "finished_at": ("<", cutoff)})
	frappe.db.delete(KEY_DOCTYPE, {"status": PROCESSING, "lock_expires_at": ("<", cutoff)})


def in_progress():
	frappe.local.response_headers["Retry-After"] = str(RETRY_AFTER_SECONDS)
	frappe.throw(_("Processing", context=CONTEXT), IdempotencyInProgressError)


def lock_end() -> datetime:
	return add_to_date(now_datetime(), seconds=LOCK_SECONDS)


def retention_start() -> datetime:
	return add_to_date(now_datetime(), hours=-RETENTION_HOURS)


def is_expired(row: frappe._dict) -> bool:
	return (
		row.status == DONE
		and row.finished_at is not None
		and get_datetime(row.finished_at) < retention_start()
	)
