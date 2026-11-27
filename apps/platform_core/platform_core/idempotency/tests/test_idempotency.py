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
	VersionConflictError,
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


@idempotent(organization=current_organization)
def failing_note(description: str):
	frappe.get_doc({"doctype": "ToDo", "description": description}).insert()
	raise frappe.ValidationError("Test failure after the insert.")


def call(function, key: str | None, **payload):
	"""Call an endpoint as Frappe would for `/api/method/`: request headers and `form_dict`."""
	headers = {"Idempotency-Key": key} if key is not None else {}
	frappe.local.request = EnvironBuilder(method="POST", headers=headers).get_request()
	frappe.local.form_dict = frappe._dict(cmd="test.endpoint", csrf_token="x", **payload)
	frappe.local.response_headers = frappe.local.response_headers.__class__()
	return function(**payload)


class IdempotencyCase(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ORGANIZATION["value"] = "org-a.example.test"
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
		with self.assertRaises(frappe.ValidationError):
			call(failing_note, key, description=self.marker)
		self.assertEqual(self.notes(), 0)
		self.assertFalse(frappe.db.exists(KEY_DOCTYPE, {"idempotency_key": key}))

	# Contract section 6: a request that finds the first one still running gets 409 and Retry-After.
	def test_running_first_call_answers_in_progress(self):
		key = str(uuid.uuid4())
		core.reserve(
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
		name = core.reserve(
			endpoint=f"{__name__}.create_note",
			key=key,
			digest=core.digest({"description": self.marker}),
			organization="org-a.example.test",
			account="Administrator",
		)
		frappe.db.set_value(
			KEY_DOCTYPE, name, "lock_expires_at", frappe.utils.add_to_date(None, seconds=-1), update_modified=False
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

	# Contract section 7: the version condition.
	def test_version_conflict(self):
		note = frappe.get_doc({"doctype": "ToDo", "description": self.marker}).insert()
		core.check_version(note, str(note.modified))
		with self.assertRaises(VersionConflictError) as caught:
			core.check_version(note, "2000-01-01 00:00:00.000000")
		self.assertEqual(caught.exception.http_status_code, 409)
		self.assertTrue(issubclass(VersionConflictError, frappe.TimestampMismatchError))
