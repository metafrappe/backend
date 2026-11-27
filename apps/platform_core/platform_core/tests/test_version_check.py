"""A versioned edit refuses a stale version and leaves the record unchanged (AJA-1751, G-125).

The contract is `contracts/idempotency.md`, section 7. The version is the record's `modified`
value. A stale version gets HTTP 409 and `VersionConflictError`.
"""

import frappe
from frappe.tests import IntegrationTestCase

from platform_core.version_check import VersionConflictError, update_with_version

DOCTYPE = "ToDo"


class VersionCheckTest(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.local.response = frappe._dict()
		self.doc = frappe.get_doc({"doctype": DOCTYPE, "description": "first"}).insert()
		self.version = str(self.doc.modified)
		# A second tab saves the record. The version of the first tab is now stale.
		self.doc.description = "second tab"
		self.doc.save()
		self.latest = str(frappe.db.get_value(DOCTYPE, self.doc.name, "modified"))

	def test_stale_version_is_refused_and_record_does_not_change(self):
		with self.assertRaises(VersionConflictError):
			update_with_version(DOCTYPE, self.doc.name, self.version, {"description": "stale tab"})
		row = frappe.db.get_value(DOCTYPE, self.doc.name, ["description", "modified"], as_dict=True)
		self.assertEqual(row.description, "second tab")
		self.assertEqual(str(row.modified), self.latest)

	def test_current_version_is_accepted_and_version_advances(self):
		result = update_with_version(DOCTYPE, self.doc.name, self.latest, {"description": "third"})
		row = frappe.db.get_value(DOCTYPE, self.doc.name, ["description", "modified"], as_dict=True)
		self.assertEqual(row.description, "third")
		self.assertEqual(result, {"name": self.doc.name, "version": str(row.modified)})
		self.assertGreater(row.modified, frappe.utils.get_datetime(self.latest))
		# The new version is accepted once. Repeating the old one is now a conflict.
		with self.assertRaises(VersionConflictError):
			update_with_version(DOCTYPE, self.doc.name, self.latest, {"description": "again"})

	def test_conflict_reply_carries_code_and_latest_version(self):
		with self.assertRaises(VersionConflictError) as error:
			update_with_version(DOCTYPE, self.doc.name, self.version, {"description": "stale tab"})
		self.assertEqual(error.exception.http_status_code, 409)
		self.assertIsInstance(error.exception, frappe.TimestampMismatchError)
		self.assertEqual(
			frappe.local.response.get("conflict"),
			{
				"code": "VersionConflictError",
				"doctype": DOCTYPE,
				"name": self.doc.name,
				"current_version": self.latest,
			},
		)

	def test_user_without_write_permission_gets_no_version(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				update_with_version(DOCTYPE, self.doc.name, self.version, {"description": "guest"})
		finally:
			frappe.set_user("Administrator")
		self.assertNotIn("conflict", frappe.local.response)
		self.assertEqual(frappe.db.get_value(DOCTYPE, self.doc.name, "description"), "second tab")
