"""AI tools follow the access rules of `PLT Access Rule` like every other data surface (G-85).

The access rule tests prove the rules on REST, report and export surfaces (G-121). These tests
send the same users through the MCP endpoint. The AI tools must see the same set of records.
A record outside the rules is refused, and the refusal is written to `PLT AI Action Log`
with the decision `denied`. A field of level 1 does not come back to a user without that level.
"""

import json

import frappe
from frappe.tests.test_api import make_request

from platform_core.access.tests.base import (
	DOCTYPE,
	EMPLOYEE_1,
	EXPECTED_VISIBLE,
	HR,
	MANAGER_1,
	MANAGER_2,
	NO_RULE,
	AccessRuleTestCase,
)

# The MCP endpoint of the AI layer. The test reaches it over HTTP only, like a client does.
MCP_PATH = "/api/method/platform_core.api.ai.mcp"
LEVEL_1_FIELD = "salary_amount"


class TestRecordRuleParity(AccessRuleTestCase):
	def setUp(self):
		super().setUp()
		# Redis counters survive database rollbacks. Each test gets its own request allowance.
		for endpoint in ("platform_core.api.ai.mcp", "platform_core.ai.oauth._verify_bearer"):
			frappe.cache.delete_keys(f"rl:{endpoint}:")
		self.known_logs = set(frappe.get_all("PLT AI Action Log", pluck="name"))

	def ai_login(self, user: str):
		"""Logs in and puts a CSRF token in the session, as the desk page does."""
		client = self.login(user)
		sid = client.get_cookie("sid").value
		session = frappe.cache.hget("session", sid)
		session["data"]["csrf_token"] = frappe.generate_hash()
		frappe.cache.hset("session", sid, session)
		client.csrf_token = session["data"]["csrf_token"]
		return client

	def call_tool(self, client, name: str, arguments: dict) -> dict:
		headers = {
			"Accept": "application/json",
			"Content-Type": "application/json",
			"X-Frappe-CSRF-Token": client.csrf_token,
		}
		payload = {
			"jsonrpc": "2.0",
			"id": 1,
			"method": "tools/call",
			"params": {"name": name, "arguments": arguments},
		}
		frappe.db.commit()  # nosemgrep: frappe-request-commit -- test setup, the request reads on another connection
		try:
			response = make_request(
				client.open,
				args=(),
				kwargs={"path": MCP_PATH, "method": "POST", "headers": headers, "data": json.dumps(payload)},
				site=self.site,
			)
		finally:
			frappe.db.rollback()
		self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
		self.assertIn("result", response.json, response.json)
		return response.json["result"]

	def ai_listed_names(self, client) -> set[str]:
		tool_result = self.call_tool(
			client, "plt_list_documents", {"doctype": DOCTYPE, "fields": ["name"], "limit": 100}
		)
		self.assertFalse(tool_result["isError"], tool_result)
		return {row["name"] for row in tool_result["structuredContent"]["documents"]}

	def new_log(self, **filters):
		names = [
			name
			for name in frappe.get_all("PLT AI Action Log", filters=filters, pluck="name")
			if name not in self.known_logs
		]
		if not names:
			return None
		return frappe.get_all(
			"PLT AI Action Log",
			filters={"name": ("in", names)},
			fields=["*"],
			order_by="creation desc, name desc",
			limit=1,
		)[0]

	def assert_denied(self, tool_result: dict, code: str) -> None:
		self.assertTrue(tool_result["isError"], tool_result)
		self.assertEqual(tool_result["structuredContent"]["error"]["code"], code, tool_result)

	def test_ai_list_returns_the_same_records_as_rest_for_every_user(self):
		for user, owners in EXPECTED_VISIBLE.items():
			with self.subTest(user=user):
				client = self.ai_login(user)
				self.assertEqual(self.ai_listed_names(client), self.names_of(owners))
				self.assertEqual(self.ai_listed_names(client), self.listed_names(client))

	def test_record_outside_the_rules_is_denied_and_logged(self):
		client = self.ai_login(EMPLOYEE_1)
		other = self.records[MANAGER_1]

		tool_result = self.call_tool(client, "plt_get_document", {"doctype": DOCTYPE, "name": other})

		self.assert_denied(tool_result, "permission")
		log = self.new_log(tool="plt_get_document", target_name=other)
		self.assertIsNotNone(log)
		self.assertEqual(log.decision, "denied")
		self.assertEqual(log.deny_reason, "permission")
		self.assertEqual(log.user, EMPLOYEE_1)
		self.assertEqual(log.principal, "human_session")

	def test_manager_of_another_team_is_denied_and_logged(self):
		client = self.ai_login(MANAGER_2)
		other = self.records[EMPLOYEE_1]

		tool_result = self.call_tool(client, "plt_get_document", {"doctype": DOCTYPE, "name": other})

		self.assert_denied(tool_result, "permission")
		self.assertEqual(self.new_log(tool="plt_get_document", target_name=other).decision, "denied")

	def test_user_without_a_rule_reads_no_record(self):
		client = self.ai_login(NO_RULE)
		target = self.records[EMPLOYEE_1]

		listed = self.ai_listed_names(client)
		single = self.call_tool(client, "plt_get_document", {"doctype": DOCTYPE, "name": target})

		self.assertEqual(listed, set())
		self.assert_denied(single, "permission")
		self.assertEqual(self.new_log(tool="plt_get_document", target_name=target).decision, "denied")

	def test_record_inside_the_rules_is_read_without_the_level_1_field(self):
		client = self.ai_login(EMPLOYEE_1)
		own = self.records[EMPLOYEE_1]

		tool_result = self.call_tool(client, "plt_get_document", {"doctype": DOCTYPE, "name": own})
		by_field = self.call_tool(
			client, "plt_list_documents", {"doctype": DOCTYPE, "fields": ["name", LEVEL_1_FIELD]}
		)

		self.assertFalse(tool_result["isError"], tool_result)
		self.assertNotIn(LEVEL_1_FIELD, tool_result["structuredContent"]["document"])
		self.assertEqual(self.new_log(tool="plt_get_document", target_name=own).decision, "allowed")
		self.assert_denied(by_field, "field_not_permitted")
		log = self.new_log(tool="plt_list_documents", target_doctype=DOCTYPE)
		self.assertIsNotNone(log)
		self.assertEqual(log.decision, "denied")
		self.assertEqual(log.deny_reason, "field_not_permitted")
		self.assertEqual(log.user, EMPLOYEE_1)

	def test_hr_reads_the_level_1_field_of_every_record(self):
		client = self.ai_login(HR)
		target = self.records[EMPLOYEE_1]

		tool_result = self.call_tool(client, "plt_get_document", {"doctype": DOCTYPE, "name": target})

		self.assertFalse(tool_result["isError"], tool_result)
		self.assertEqual(tool_result["structuredContent"]["document"][LEVEL_1_FIELD], 1234)
