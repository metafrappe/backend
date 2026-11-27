"""The shared idempotency key layer (AJA-1750, contract `contracts/idempotency.md`, G-125).

The layer writes its key row and commits it before the work, so these tests commit too. Each test
uses its own marker text and removes its rows afterwards.
"""

import threading
import time
import uuid
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase
from werkzeug.test import EnvironBuilder

from platform_core.idempotency import core
from platform_core.idempotency.core import (
	IdempotencyInProgressError,
	IdempotencyKeyMissingError,
	IdempotencyKeyReusedError,
	idempotent,
)

KEY_DOCTYPE = "PLT Idempotency Key"
ORGANIZATION = {"value": "org-a.example.test"}


def current_organization() -> str:
	return ORGANIZATION["value"]


@idempotent(organization=current_organization)
def create_note(description: str, slow: int = 0):
	"""A new-record endpoint for the tests. It opens one ToDo."""
	note = frappe.get_doc({"doctype": "ToDo", "description": description}).insert()
	if slow:
		time.sleep(slow)
	return note


FLAGS = {"fail": False, "allowed": True}


@idempotent(organization=current_organization)
def failing_note(description: str):
	"""Fails after its insert while FLAGS["fail"] is set."""
	note = frappe.get_doc({"doctype": "ToDo", "description": description}).insert()
	if FLAGS["fail"]:
		raise frappe.ValidationError("Test failure after the insert.")
	return note


def check_allowed():
	if not FLAGS["allowed"]:
		frappe.throw("Not permitted", frappe.PermissionError)


@idempotent(organization=current_organization, permission=check_allowed)
def guarded_note(description: str):
	return frappe.get_doc({"doctype": "ToDo", "description": description}).insert()


def broken_render(_doc):
	raise RuntimeError("Test failure while rendering.")


@idempotent(organization=current_organization, render=broken_render)
def unrenderable_note(description: str):
	return frappe.get_doc({"doctype": "ToDo", "description": description}).insert()


@idempotent(organization=current_organization)
def overtaken_note(description: str):
	"""Another request takes the key row over while this one still works."""
	note = frappe.get_doc({"doctype": "ToDo", "description": description}).insert()
	key = frappe.local.request.headers.get("Idempotency-Key")
	site = frappe.local.site

	def take_over():
		frappe.init(site=site)
		frappe.connect()
		try:
			frappe.db.set_value(KEY_DOCTYPE, {"idempotency_key": key}, "attempt_id", "other-attempt")
			frappe.db.commit()
		finally:
			frappe.destroy()

	worker = threading.Thread(target=take_over)
	worker.start()
	worker.join(timeout=60)
	return note


def call(function, key: str | None, extra: dict | None = None, **payload):
	"""Call an endpoint as Frappe would for `/api/method/`: request headers and `form_dict`.

	`extra` holds body fields that the endpoint reads from `form_dict`, not as arguments.
	"""
	headers = {"Idempotency-Key": key} if key is not None else {}
	frappe.local.request = EnvironBuilder(method="POST", headers=headers).get_request()
	frappe.local.form_dict = frappe._dict(cmd="test.endpoint", csrf_token="x", **payload, **(extra or {}))
	frappe.local.response_headers = frappe.local.response_headers.__class__()
	frappe.local.message_log = []
	return function(**payload)


class IdempotencyCase(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ORGANIZATION["value"] = "org-a.example.test"
		FLAGS.update(fail=False, allowed=True)
		self.marker = f"idempotency-test-{uuid.uuid4()}"
		self.addCleanup(self.remove_rows)

	def remove_rows(self):
		frappe.db.rollback()
		frappe.db.delete("ToDo", {"description": ("like", f"{self.marker}%")})
		frappe.db.delete(KEY_DOCTYPE, {"endpoint": ("like", f"{__name__}.%")})
		frappe.db.commit()
		frappe.local.request = None

	def notes(self) -> int:
		return frappe.db.count("ToDo", {"description": ("like", f"{self.marker}%")})

	# 1. Same key, same body: one record, the second call returns the same record.
	def test_same_key_same_body_returns_the_first_record(self):
		key = str(uuid.uuid4())
		first = call(create_note, key, description=self.marker)
		frappe.db.commit()
		second = call(create_note, key, description=self.marker)
		frappe.db.commit()
		self.assertEqual(self.notes(), 1)
		self.assertEqual(first, second)
		self.assertEqual(second["doctype"], "ToDo")
		self.assertEqual(frappe.local.response_headers.get("Idempotent-Replayed"), "true")
		# The failed insert of the second call leaves no "already exists" message in the response.
		self.assertEqual(frappe.local.message_log, [])
		row = frappe.get_all(KEY_DOCTYPE, filters={"idempotency_key": key}, fields=["*"])
		self.assertEqual(len(row), 1)
		self.assertEqual(row[0].status, "done")
		self.assertEqual(row[0].result_doctype, "ToDo")
		self.assertEqual(row[0].result_name, first["name"])
		self.assertEqual(row[0].organization, "org-a.example.test")
		self.assertEqual(row[0].account, "Administrator")
		self.assertEqual(row[0].endpoint, f"{__name__}.create_note")

	# 2. Same key, other body: refused with 422, no new record.
	def test_same_key_other_body_is_refused(self):
		key = str(uuid.uuid4())
		call(create_note, key, description=self.marker)
		frappe.db.commit()
		with self.assertRaises(IdempotencyKeyReusedError) as caught:
			call(create_note, key, description=f"{self.marker}-other")
		self.assertEqual(caught.exception.http_status_code, 422)
		frappe.db.commit()
		self.assertEqual(self.notes(), 1)

	# 3. The organization changes: the old organization's key does not return its result.
	def test_key_of_another_organization_does_not_replay(self):
		key = str(uuid.uuid4())
		first = call(create_note, key, description=self.marker)
		frappe.db.commit()
		ORGANIZATION["value"] = "org-b.example.test"
		second = call(create_note, key, description=self.marker)
		frappe.db.commit()
		self.assertNotEqual(first["name"], second["name"])
		self.assertIsNone(frappe.local.response_headers.get("Idempotent-Replayed"))
		organizations = frappe.get_all(
			KEY_DOCTYPE, filters={"idempotency_key": key}, pluck="organization", order_by="organization"
		)
		self.assertEqual(organizations, ["org-a.example.test", "org-b.example.test"])

	# 4. Two requests at the same time: one record.
	def test_two_concurrent_requests_open_one_record(self):
		key = str(uuid.uuid4())
		site = frappe.local.site
		results = {}
		start = threading.Barrier(2)

		def worker(name):
			frappe.init(site=site)
			frappe.connect()
			try:
				frappe.set_user("Administrator")
				start.wait(timeout=30)
				results[name] = call(create_note, key, description=self.marker, slow=1)
				frappe.db.commit()
			except Exception as error:
				results[name] = error
				frappe.db.rollback()
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=worker, args=(name,)) for name in ("a", "b")]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join(timeout=120)
		frappe.db.rollback()
		self.assertEqual(self.notes(), 1)
		records = [value for value in results.values() if isinstance(value, dict)]
		waits = [value for value in results.values() if isinstance(value, IdempotencyInProgressError)]
		self.assertEqual(len(records) + len(waits), 2, results)
		self.assertGreaterEqual(len(records), 1, results)
		self.assertEqual(len({record["name"] for record in records}), 1)
		self.assertEqual(frappe.db.count(KEY_DOCTYPE, {"idempotency_key": key}), 1)

	# 5. A new-record endpoint refuses a request without a key, and a malformed key.
	def test_missing_or_malformed_key_is_refused(self):
		for key in (None, "", "not-a-uuid", str(uuid.uuid4()).upper()):
			with self.subTest(key=key):
				with self.assertRaises(IdempotencyKeyMissingError) as caught:
					call(create_note, key, description=self.marker)
				self.assertEqual(caught.exception.http_status_code, 400)
		frappe.db.commit()
		self.assertEqual(self.notes(), 0)
		self.assertFalse(frappe.db.exists(KEY_DOCTYPE, {"endpoint": f"{__name__}.create_note"}))

	# Contract section 4: a failed first call leaves no key row, so the retry does the work.
	def test_failed_first_call_can_be_retried(self):
		key = str(uuid.uuid4())
		FLAGS["fail"] = True
		with self.assertRaises(frappe.ValidationError):
			call(failing_note, key, description=self.marker)
		self.assertEqual(self.notes(), 0)
		self.assertFalse(frappe.db.exists(KEY_DOCTYPE, {"idempotency_key": key}))
		FLAGS["fail"] = False
		call(failing_note, key, description=self.marker)
		frappe.db.commit()
		self.assertEqual(self.notes(), 1)

	# Contract section 6: a request that finds the first one still running gets 409 and Retry-After.
	def test_running_first_call_answers_in_progress(self):
		key = str(uuid.uuid4())
		_name, _attempt = core.reserve(
			endpoint=f"{__name__}.create_note",
			key=key,
			digest=core.digest({"description": self.marker}),
			organization="org-a.example.test",
			account="Administrator",
		)
		with self.assertRaises(IdempotencyInProgressError) as caught:
			call(create_note, key, description=self.marker)
		self.assertEqual(caught.exception.http_status_code, 409)
		self.assertEqual(frappe.local.response_headers.get("Retry-After"), "2")
		frappe.db.commit()
		self.assertEqual(self.notes(), 0)

	# Contract section 6, rule 4: a row whose lock ran out is taken over and the work is done once.
	def test_expired_lock_is_taken_over(self):
		key = str(uuid.uuid4())
		name, _attempt = core.reserve(
			endpoint=f"{__name__}.create_note",
			key=key,
			digest=core.digest({"description": self.marker}),
			organization="org-a.example.test",
			account="Administrator",
		)
		frappe.db.set_value(
			KEY_DOCTYPE,
			name,
			"lock_expires_at",
			frappe.utils.add_to_date(None, seconds=-1),
			update_modified=False,
		)
		frappe.db.commit()
		result = call(create_note, key, description=self.marker)
		frappe.db.commit()
		self.assertEqual(self.notes(), 1)
		self.assertEqual(frappe.db.get_value(KEY_DOCTYPE, name, "result_name"), result["name"])

	# Contract section 2: permission is checked again on a replay.
	def test_replay_checks_permission_again(self):
		key = str(uuid.uuid4())
		call(create_note, key, description=self.marker)
		frappe.db.commit()
		with mock.patch.object(core.frappe, "has_permission", return_value=False):
			with self.assertRaises(frappe.PermissionError):
				call(create_note, key, description=self.marker)

	# Review B1: the key row does not block deleting the result record.
	def test_result_record_can_be_deleted(self):
		key = str(uuid.uuid4())
		result = call(create_note, key, description=self.marker)
		frappe.db.commit()
		frappe.delete_doc("ToDo", result["name"])
		frappe.db.commit()
		self.assertEqual(self.notes(), 0)

	# Review M4: the digest covers the request body, also fields the endpoint reads itself.
	def test_other_body_field_outside_the_arguments_is_refused(self):
		key = str(uuid.uuid4())
		call(create_note, key, extra={"priority": "Low"}, description=self.marker)
		frappe.db.commit()
		with self.assertRaises(IdempotencyKeyReusedError):
			call(create_note, key, extra={"priority": "High"}, description=self.marker)

	# Review M5: the endpoint's own permission check runs on every call, also on a replay.
	def test_permission_check_runs_on_replay(self):
		key = str(uuid.uuid4())
		call(guarded_note, key, description=self.marker)
		frappe.db.commit()
		FLAGS["allowed"] = False
		with self.assertRaises(frappe.PermissionError):
			call(guarded_note, key, description=self.marker)

	# Review M2: a request whose row another request took over does not finish the work.
	def test_overtaken_request_does_not_finish(self):
		key = str(uuid.uuid4())
		with self.assertRaises(IdempotencyInProgressError):
			call(overtaken_note, key, description=self.marker)
		frappe.db.commit()
		self.assertEqual(self.notes(), 0)
		# The row of the other request stays. The overtaken request does not delete it.
		self.assertEqual(
			frappe.db.get_value(KEY_DOCTYPE, {"idempotency_key": key}, "attempt_id"), "other-attempt"
		)

	# Review m1: a failure after the work, while rendering, frees the key at once.
	def test_render_failure_frees_the_key(self):
		key = str(uuid.uuid4())
		with self.assertRaises(RuntimeError):
			call(unrenderable_note, key, description=self.marker)
		self.assertEqual(self.notes(), 0)
		self.assertFalse(frappe.db.exists(KEY_DOCTYPE, {"idempotency_key": key}))

	# Review M6: rows finished more than 24 hours ago are removed, newer rows stay.
	def test_purge_removes_only_expired_rows(self):
		old_key, new_key = str(uuid.uuid4()), str(uuid.uuid4())
		call(create_note, old_key, description=self.marker)
		call(create_note, new_key, description=f"{self.marker}-new")
		frappe.db.set_value(
			KEY_DOCTYPE,
			{"idempotency_key": old_key},
			"finished_at",
			frappe.utils.add_to_date(None, hours=-25),
			update_modified=False,
		)
		frappe.db.commit()
		core.purge_expired()
		frappe.db.commit()
		self.assertFalse(frappe.db.exists(KEY_DOCTYPE, {"idempotency_key": old_key}))
		self.assertTrue(frappe.db.exists(KEY_DOCTYPE, {"idempotency_key": new_key}))
