"""Frappe hooks and durable delivery for O-57 status events."""

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import frappe

from press_tr.job_status.events import DEPLOY_RECORDS, EVENT_TYPES, build_event, is_active
from press_tr.job_status.signing import sign_event

STATE = "PTR Job Status State"
OUTBOX = "PTR Job Status Outbox"
WORKER = "press_tr.job_status.runtime.reconcile"
JOB_ID = "press-status-reconcile"
PRESS_JOB_PREFIX = "press.press.doctype.agent_job.agent_job."


def _log(code):
	# No exception, request body or document is attached to this diagnostic.
	try:
		frappe.log_error(title="Press status delivery", message=code)
	except Exception:
		# Diagnostics must not fail the Press transaction either.
		return


def _enqueue():
	try:
		frappe.enqueue(WORKER, job_id=JOB_ID, deduplicate=True, queue="short")
	except Exception:
		_log("enqueue_failed")


def _register(record_type, record_name):
	if record_type not in EVENT_TYPES or not record_name:
		return
	# Match the source-write -> tracking-state order used by hooks and the worker.
	# Lock only the primary key; execution data is not needed for registration.
	if not frappe.db.get_value(record_type, record_name, "name", for_update=True):
		return
	state_key = hashlib.sha256(f"{record_type}\n{record_name}".encode()).hexdigest()
	document = frappe.get_doc(
		{
			"doctype": STATE,
			"state_key": state_key,
			"record_type": record_type,
			"record_name": record_name,
			"observed_status": None,
			"active": 1,
		}
	)
	# Private tracking state is keyed by a trusted source DocType/name pair.
	document.insert(ignore_permissions=True, ignore_if_duplicate=True)  # nosemgrep: frappe-ignore-permissions
	frappe.db.set_value(STATE, state_key, "active", 1, update_modified=False)
	return state_key


def _register_related(doc):
	if doc.get("doctype") != "Agent Job":
		return
	for record_type, name in sorted(
		{
			("Site", doc.get("site") or ""),
			("Bench", doc.get("bench") or ""),
			(doc.get("reference_doctype") or "", doc.get("reference_name") or ""),
		}
	):
		_register(record_type, name)


def on_record(doc, method=None, *, capture=True):
	"""Register a supported record and enqueue only after commit."""
	if doc.get("doctype") not in EVENT_TYPES:
		return
	point = "press_status_" + uuid.uuid4().hex
	point_created = False
	try:
		frappe.db.savepoint(point)
		point_created = True
		state_name = _register(doc.doctype, doc.name)
		if state_name and capture:
			_observe(state_name, record=doc, capture="hook")
		_register_related(doc)
		frappe.db.after_commit.add(_enqueue)
	except Exception:
		if point_created:
			try:
				frappe.db.rollback(save_point=point)
			except Exception:
				_log("registration_rollback_failed")
		_log("registration_failed")


def after_callback(doc, method=None):
	"""Reconcile after an Agent Job Callback transaction commits."""
	try:
		job = frappe.get_doc("Agent Job", doc.get("agent_job"))
		on_record(job, capture=False)
	except Exception:
		_log("callback_registration_failed")


def after_press_job(method=None, **kwargs):
	"""Only existing Press Agent Job workers trigger reconciliation."""
	if isinstance(method, str) and method.startswith(PRESS_JOB_PREFIX):
		# Frappe calls after_job after committing; do not add an unrun after_commit callback here.
		_enqueue()


def _metadata(doc):
	kind = doc.doctype
	result = {field: doc.get(field) for field in ("name", "status", "site", "team")}
	result["doctype"] = kind
	if kind == "Site":
		result["site"] = doc.name
	if result["site"] and not result["team"]:
		result["team"] = frappe.db.get_value("Site", result["site"], "team")
	if kind in DEPLOY_RECORDS:
		result["group"] = doc.get("group")
		result["candidate"] = (
			doc.get("deploy_candidate") if kind == "Deploy Candidate Build" else doc.get("candidate")
		)
		if kind == "New Bench Queue" and not result["candidate"]:
			payload = doc.get("payload") or {}
			if isinstance(payload, str):
				payload = json.loads(payload)
			if isinstance(payload, dict):
				result["candidate"] = payload.get("candidate")
		queue = doc.name if kind == "New Bench Queue" else None
		if kind == "Bench":
			queue = frappe.db.get_value("New Bench Queue", {"bench": doc.name}, "name")
		result["deploy"] = frappe.db.get_value("Deploy Bench", {"bench": queue}, "parent") if queue else None
		if result["deploy"]:
			for field in ("candidate", "group", "team"):
				result[field] = result.get(field) or frappe.db.get_value("Deploy", result["deploy"], field)
	return result


def _observe(state_name, *, record=None, capture="reconcile", identity=None):
	# Hooks already hold the source row through Frappe.save. Workers lock source first.
	# Current reads of both rows prevent stale-source/new-state pairs under repeatable read.
	if record is None:
		try:
			record = frappe.get_doc(identity["record_type"], identity["record_name"], for_update=True)
		except frappe.DoesNotExistError:
			frappe.get_doc(STATE, state_name, for_update=True)
			frappe.db.set_value(STATE, state_name, "active", 0, update_modified=False)
			return
	state = frappe.get_doc(STATE, state_name, for_update=True)
	if not state.active:
		return
	event = build_event(
		_metadata(record),
		state.observed_status or None,
		capture=capture,
		event_id=uuid.uuid4().hex,
		occurred_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
	)
	if event:
		document = frappe.get_doc(
			{
				"doctype": OUTBOX,
				"event_id": event["event_id"],
				"payload": json.dumps(event, separators=(",", ":")),
				"delivered": 0,
			}
		)
		# Private immutable metadata, created only by trusted hooks and the internal worker.
		document.insert(ignore_permissions=True)  # nosemgrep: frappe-ignore-permissions
	frappe.db.set_value(
		STATE,
		state.name,
		{
			"observed_status": record.get("status"),
			"active": int(is_active(record.doctype, record.get("status"))),
		},
		update_modified=False,
	)


def reconcile():
	"""Compare every active record and deliver the durable outbox."""
	identities = frappe.get_all(
		STATE, filters={"active": 1}, fields=["name", "record_type", "record_name"], limit_page_length=0
	)
	# End the list snapshot. No record is ever committed without its outbox transition.
	frappe.db.commit()
	for identity in sorted(identities, key=lambda row: row["name"]):
		_observe(identity["name"], identity=identity)
		# Avoid holding unrelated source rows while another hook waits on their state rows.
		frappe.db.commit()
	dispatch()


def _https_endpoint(endpoint):
	try:
		parts = urlsplit(endpoint)
		return (
			parts.scheme == "https"
			and bool(parts.hostname)
			and not parts.username
			and not parts.password
			and not parts.fragment
		)
	except (ValueError, TypeError):
		return False


def dispatch():
	"""Keep failed deliveries for the next existing trigger."""
	endpoint = frappe.conf.get("press_job_status_endpoint")
	key_id = frappe.conf.get("press_job_status_key_id")
	secret = frappe.conf.get("press_job_status_key")
	if not endpoint and not key_id and not secret:
		return
	if (
		not _https_endpoint(endpoint)
		or not isinstance(key_id, str)
		or not key_id
		or not isinstance(secret, str)
	):
		_log("sender_configuration_invalid")
		return
	import requests

	for name in frappe.get_all(
		OUTBOX, filters={"delivered": 0}, pluck="name", order_by="creation asc", limit_page_length=25
	):
		row = frappe.get_doc(OUTBOX, name, for_update=True)
		if row.delivered:
			continue
		body = row.payload.encode("utf-8")
		timestamp = int(time.time())
		try:
			signature = sign_event(body, secret.encode("utf-8"), timestamp, event_id=row.event_id)
			response = requests.post(
				endpoint,
				data=body,
				headers={
					"Content-Type": "application/octet-stream",
					"X-Press-Event-Id": row.event_id,
					"X-Press-Timestamp": str(timestamp),
					"X-Press-Key-Id": key_id,
					"X-Press-Signature": signature,
				},
				timeout=(3, 10),
				allow_redirects=False,
			)
			if response.status_code != 200:
				_log("delivery_failed")
				continue
			ack = response.json()
			ack = ack.get("message", ack) if isinstance(ack, dict) else None
			if (
				not isinstance(ack, dict)
				or ack.get("accepted") is not True
				or ack.get("event_id") != row.event_id
			):
				_log("invalid_acknowledgement")
				continue
			frappe.db.set_value(OUTBOX, row.name, "delivered", 1, update_modified=False)
		except (requests.RequestException, ValueError, TypeError):
			_log("delivery_failed")
		finally:
			# A crash before this commit causes a safe retry with the same event ID.
			frappe.db.commit()


def validate_webhook(doc, method=None):
	"""Require HTTPS except for explicitly local development."""
	endpoint = doc.get("endpoint")
	if _https_endpoint(endpoint):
		return
	try:
		parts = urlsplit(endpoint)
		local = (
			frappe.conf.get("deployment_environment") == "local"
			and frappe.conf.get("developer_mode")
			and parts.scheme == "http"
			and parts.hostname in {"localhost", "127.0.0.1", "::1"}
			and not parts.username
			and not parts.password
			and not parts.fragment
		)
	except (ValueError, TypeError):
		local = False
	if not local:
		frappe.throw(frappe._("Webhook endpoint must use HTTPS.", context="press_tr"), frappe.ValidationError)
