"""G-27: the commercial press_tr MCP server.

Acceptance (AJA-2499):
- Tools run only as the separate service account.
- Requests are accepted only from allowed networks.
- A commercial tool returns only a preview while confirm is false.
- Every tool call is written to the history (PTR MCP Call).

The test needs no Frappe install: ``frappe`` and ``frappe_mcp`` are replaced with stubs, so it
also runs outside the Press container. All names and addresses are made-up examples.
"""

import json
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

SERVICE_USER = "mcp-agent@example.test"
COMMERCIAL_TOOLS = {"install_app", "change_app_plan", "change_site_plan"}
ALL_TOOLS = {
	"list_marketplace_apps",
	"get_app_plans",
	"install_app",
	"change_app_plan",
	"change_site_plan",
	"get_invoices",
	"get_upcoming_invoice",
	"get_agent_job_status",
}


class Refused(Exception):
	pass


class Invalid(Exception):
	pass


class FakeMCP:
	def __init__(self, name):
		self.name = name
		self.handler = None
		self.tools = {}

	def register(self, **_kwargs):
		def decorate(fn):
			self.handler = fn
			return fn

		return decorate

	def tool(self, **_kwargs):
		def decorate(fn):
			self.tools[fn.__name__] = fn
			return fn

		return decorate


def fake_modules():
	frappe = ModuleType("frappe")
	frappe.AuthenticationError = Refused
	frappe.PermissionError = Refused
	frappe.ValidationError = Invalid
	frappe.DoesNotExistError = Invalid
	frappe._ = lambda text, context=None: text

	def throw(message, exc=Invalid, title=None):
		raise exc(message)

	frappe.throw = throw
	frappe.session = SimpleNamespace(user=SERVICE_USER)
	frappe.local = SimpleNamespace(request_ip="10.20.0.5")
	frappe.conf = {
		"press_tr_mcp_service_user": SERVICE_USER,
		"press_tr_mcp_allowed_networks": ["10.20.0.0/24"],
	}
	frappe.users = {
		SERVICE_USER: {"user_type": "System User", "roles": ["System Manager"]},
		"Administrator": {"user_type": "System User", "roles": ["System Manager"]},
		"member@example.test": {"user_type": "Website User", "roles": []},
	}
	frappe.settings = {"enable_mcp": 1}
	frappe.get_cached_value = lambda doctype, name, field: frappe.users.get(name, {}).get(field)
	frappe.get_roles = lambda user=None: frappe.users.get(user, {}).get("roles", [])
	frappe.get_value = lambda doctype, name, field: frappe.settings.get(field)
	frappe.logs = []
	frappe.docs = {}
	frappe.records = {}

	def get_doc(doctype, name=None):
		if isinstance(doctype, dict):
			record = dict(doctype)
			return SimpleNamespace(insert=lambda ignore_permissions=False: frappe.logs.append(record))
		return frappe.docs[(doctype, name)]

	frappe.get_doc = get_doc
	frappe.get_all = Mock(side_effect=lambda doctype, **kwargs: frappe.records.get(doctype, []))
	frappe.db = SimpleNamespace(
		commit=Mock(),
		exists=lambda doctype, name: (doctype, name) in frappe.docs,
		get_value=Mock(return_value=None),
	)

	frappe_mcp = ModuleType("frappe_mcp")
	frappe_mcp.MCP = FakeMCP
	return frappe, frappe_mcp


class McpServerTest(unittest.TestCase):
	def setUp(self):
		self.frappe, frappe_mcp = fake_modules()
		patcher = patch.dict(sys.modules, {"frappe": self.frappe, "frappe_mcp": frappe_mcp})
		patcher.start()
		self.addCleanup(patcher.stop)
		for name in [name for name in sys.modules if name.startswith("press_tr.mcp")]:
			sys.modules.pop(name)
		import press_tr.mcp as server

		self.server = server
		self.site = SimpleNamespace(install_app=Mock(), set_plan=Mock(), team="team-a", plan="old")
		self.subscription = SimpleNamespace(
			name="sub-1",
			team="team-a",
			document_type="Marketplace App",
			document_name="crm_tr",
			plan="crm-free",
			save=Mock(),
		)
		self.frappe.docs[("Site", "demo.example.test")] = self.site
		self.frappe.docs[("Subscription", "sub-1")] = self.subscription
		self.frappe.docs[("Marketplace App", "crm_tr")] = SimpleNamespace(name="crm_tr")
		self.frappe.docs[("Marketplace App Plan", "crm-pro")] = SimpleNamespace(name="crm-pro", app="crm_tr")
		self.frappe.docs[("Site Plan", "business")] = SimpleNamespace(name="business")

	def tools(self):
		self.server.handler()
		return self.server.mcp.tools

	# Service account

	def test_handler_is_the_registered_press_tr_server(self):
		self.assertEqual(self.server.mcp.handler, self.server.handler)
		self.assertEqual(self.server.mcp.name, "press-tr-mcp")

	def test_tools_run_only_as_the_configured_service_account(self):
		self.assertEqual(set(self.tools()), ALL_TOOLS)
		for user in ("Administrator", "member@example.test", "Guest"):
			with self.subTest(user=user):
				self.frappe.session.user = user
				with self.assertRaises(Refused):
					self.server.handler()

	def test_handler_refuses_when_no_service_account_is_configured(self):
		del self.frappe.conf["press_tr_mcp_service_user"]
		with self.assertRaises(Refused):
			self.server.handler()

	def test_service_account_must_be_a_system_manager_system_user(self):
		for change in ({"user_type": "Website User"}, {"roles": ["Press Member"]}):
			with self.subTest(change=change):
				self.frappe.users[SERVICE_USER] = {
					"user_type": "System User",
					"roles": ["System Manager"],
					**change,
				}
				with self.assertRaises(Refused):
					self.server.handler()

	def test_handler_refuses_when_press_mcp_is_disabled(self):
		self.frappe.settings["enable_mcp"] = 0
		with self.assertRaises(Refused):
			self.server.handler()

	# Allowed networks

	def test_requests_from_outside_the_allowed_networks_are_refused(self):
		for address in ("10.20.1.5", "203.0.113.9", "", None, "not-an-address"):
			with self.subTest(address=address):
				self.frappe.local.request_ip = address
				with self.assertRaises(Refused):
					self.server.handler()

	def test_an_empty_allowlist_refuses_every_request(self):
		self.frappe.conf["press_tr_mcp_allowed_networks"] = []
		with self.assertRaises(Refused):
			self.server.handler()

	def test_an_allowlist_given_as_text_is_read_as_a_list(self):
		self.frappe.conf["press_tr_mcp_allowed_networks"] = "192.0.2.0/28, 10.20.0.5"
		self.server.handler()
		self.frappe.local.request_ip = "192.0.2.20"
		with self.assertRaises(Refused):
			self.server.handler()

	def test_a_refused_request_is_written_to_the_history(self):
		self.frappe.local.request_ip = "203.0.113.9"
		with self.assertRaises(Refused):
			self.server.handler()
		self.assertEqual(self.frappe.logs[-1]["status"], "Refused")
		self.assertEqual(self.frappe.logs[-1]["request_ip"], "203.0.113.9")
		self.frappe.db.commit.assert_called()

	# Preview without confirm

	def test_commercial_tools_only_preview_without_confirm(self):
		tools = self.tools()
		previews = {
			"install_app": tools["install_app"](site="demo.example.test", app="crm_tr", plan="crm-pro"),
			"change_app_plan": tools["change_app_plan"](subscription="sub-1", new_plan="crm-pro"),
			"change_site_plan": tools["change_site_plan"](site="demo.example.test", plan="business"),
		}
		self.assertEqual(set(previews), COMMERCIAL_TOOLS)
		for name, result in previews.items():
			with self.subTest(tool=name):
				self.assertTrue(result["preview"])
				self.assertTrue(result["requires_confirm"])
				self.assertEqual(result["action"], name)
		self.site.install_app.assert_not_called()
		self.site.set_plan.assert_not_called()
		self.subscription.save.assert_not_called()
		self.assertEqual(self.subscription.plan, "crm-free")

	def test_commercial_tools_run_only_with_confirm_true(self):
		tools = self.tools()
		tools["install_app"](site="demo.example.test", app="crm_tr", plan="crm-pro", confirm="true")
		self.site.install_app.assert_not_called()
		tools["install_app"](site="demo.example.test", app="crm_tr", plan="crm-pro", confirm=True)
		self.site.install_app.assert_called_once_with("crm_tr", "crm-pro")
		tools["change_site_plan"](site="demo.example.test", plan="business", confirm=True)
		self.site.set_plan.assert_called_once_with("business")
		tools["change_app_plan"](subscription="sub-1", new_plan="crm-pro", confirm=True)
		self.assertEqual(self.subscription.plan, "crm-pro")
		self.subscription.save.assert_called_once_with(ignore_permissions=True)

	def test_app_plan_must_belong_to_the_app(self):
		tools = self.tools()
		self.frappe.docs[("Marketplace App Plan", "crm-pro")].app = "other_app"
		with self.assertRaises(Invalid):
			tools["install_app"](site="demo.example.test", app="crm_tr", plan="crm-pro", confirm=True)
		with self.assertRaises(Invalid):
			tools["change_app_plan"](subscription="sub-1", new_plan="crm-pro", confirm=True)
		self.site.install_app.assert_not_called()
		self.subscription.save.assert_not_called()

	# History

	def test_every_tool_call_is_written_to_the_history(self):
		tools = self.tools()
		self.frappe.logs.clear()
		self.frappe.db.get_value.return_value = {"status": "Success"}
		calls = [
			("list_marketplace_apps", {}),
			("get_app_plans", {"app": "crm_tr"}),
			("install_app", {"site": "demo.example.test", "app": "crm_tr", "plan": "crm-pro"}),
			("change_app_plan", {"subscription": "sub-1", "new_plan": "crm-pro", "confirm": True}),
			("change_site_plan", {"site": "demo.example.test", "plan": "business"}),
			("get_invoices", {"team": "team-a"}),
			("get_agent_job_status", {"job": "job-1"}),
		]
		for name, arguments in calls:
			tools[name](**arguments)
		self.assertEqual([log["tool"] for log in self.frappe.logs], [name for name, _ in calls])
		for log in self.frappe.logs:
			with self.subTest(tool=log["tool"]):
				self.assertEqual(log["doctype"], "PTR MCP Call")
				self.assertEqual(log["user"], SERVICE_USER)
				self.assertEqual(log["request_ip"], "10.20.0.5")
				self.assertIsInstance(json.loads(log["arguments"]), dict)
		statuses = {log["tool"]: log["status"] for log in self.frappe.logs}
		self.assertEqual(statuses["install_app"], "Preview")
		self.assertEqual(statuses["change_app_plan"], "Done")
		self.assertEqual(statuses["list_marketplace_apps"], "Done")

	def test_a_failed_tool_call_is_committed_to_the_history_before_the_error(self):
		tools = self.tools()
		self.site.install_app.side_effect = Invalid("install failed")
		with self.assertRaises(Invalid):
			tools["install_app"](site="demo.example.test", app="crm_tr", plan="crm-pro", confirm=True)
		self.assertEqual(self.frappe.logs[-1]["status"], "Failed")
		self.assertIn("Invalid", self.frappe.logs[-1]["error"])
		self.frappe.db.commit.assert_called()

	def test_history_doctype_is_described_and_closed_to_edits(self):
		path = APP / "press_tr/press_tr_mcp/doctype/ptr_mcp_call/ptr_mcp_call.json"
		doc = json.loads(path.read_text())
		self.assertEqual(doc["name"], "PTR MCP Call")
		self.assertTrue(all(field.get("description") for field in doc["fields"]))
		for permission in doc["permissions"]:
			with self.subTest(role=permission["role"]):
				self.assertFalse(
					permission.get("write") or permission.get("delete") or permission.get("create")
				)
		self.assertIn("Press TR MCP", (APP / "press_tr/modules.txt").read_text().splitlines())


if __name__ == "__main__":
	unittest.main()
