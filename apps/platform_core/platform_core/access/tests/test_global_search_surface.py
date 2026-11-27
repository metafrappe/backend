"""Global search: a hidden record is not a search result (G-121).

Frappe's global search reads the `__global_search` table and keeps a row only when
`frappe.has_permission` passes on the record (`frappe/utils/global_search.py:538`). The record
hook of the engine answers that check. The test writes the index rows the way Frappe's sync does
(`sync_value`), so it does not wait for the scheduler.
"""

import frappe
from frappe.utils.global_search import sync_value

from platform_core.access.tests.base import (
	DOCTYPE,
	EMPLOYEE_1,
	EXPECTED_VISIBLE,
	HR,
	MANAGER_1,
	NO_RULE,
	RECORD_OWNERS,
	AccessRuleTestCase,
)

SEARCH = "/api/method/frappe.utils.global_search.search"
SETTINGS = "Global Search Settings"
# One made-up word in every indexed row. Full text search needs a word of three letters or more.
WORD = "gizlitalepg121"


class TestGlobalSearchSurface(AccessRuleTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single(SETTINGS)
		cls.added_to_settings = not any(
			row.document_type == DOCTYPE for row in settings.allowed_in_global_search
		)
		if cls.added_to_settings:
			settings.append("allowed_in_global_search", {"document_type": DOCTYPE})
			settings.save(ignore_permissions=True)
		frappe.cache.hdel("global_search", "search_priorities")
		for owner, name in cls.records.items():
			sync_value(
				{
					"doctype": DOCTYPE,
					"name": name,
					"content": f"Title : {WORD} {owner}",
					"published": 0,
					"title": f"Talep {owner}",
					"route": "",
				}
			)
		# Committed on purpose: the request uses another connection, and full text sees committed rows only.
		frappe.db.commit()  # nosemgrep: frappe-request-commit

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.db.delete("__global_search", {"doctype": DOCTYPE})
		if cls.added_to_settings:
			settings = frappe.get_single(SETTINGS)
			settings.allowed_in_global_search = [
				row for row in settings.allowed_in_global_search if row.document_type != DOCTYPE
			]
			settings.save(ignore_permissions=True)
		frappe.cache.hdel("global_search", "search_priorities")
		# Committed on purpose: other connections must see this.
		frappe.db.commit()  # nosemgrep: frappe-request-commit
		super().tearDownClass()

	def found(self, client, doctype: str = "") -> set[str]:
		query = {"text": WORD, "limit": 100}
		if doctype:
			query["doctype"] = doctype
		response = self.send(client, "GET", SEARCH, query=query)
		self.assertEqual(response.status_code, 200)
		return {row["name"] for row in response.json["message"] if row["doctype"] == DOCTYPE}

	def test_search_does_not_return_a_hidden_record(self):
		client = self.login(EMPLOYEE_1)

		found = self.found(client)

		self.assertNotIn(self.records[MANAGER_1], found)
		self.assertEqual(found, self.names_of(EXPECTED_VISIBLE[EMPLOYEE_1]))

	def test_search_in_one_document_type_does_not_return_a_hidden_record(self):
		client = self.login(EMPLOYEE_1)

		self.assertEqual(self.found(client, DOCTYPE), self.names_of(EXPECTED_VISIBLE[EMPLOYEE_1]))

	def test_user_without_a_rule_finds_nothing(self):
		client = self.login(NO_RULE)

		self.assertEqual(self.found(client), set())

	def test_all_scope_user_finds_every_record(self):
		"""The control case: the index rows are there, so an empty result above is a refusal."""
		client = self.login(HR)

		self.assertEqual(self.found(client), self.names_of(RECORD_OWNERS))
