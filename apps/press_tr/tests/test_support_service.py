"""Exercise the Frappe adapter with isolated framework doubles, without a live database."""

import copy
import html
import importlib.util
import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from test_support_consent import NOW, accepted, request

APP = Path(__file__).resolve().parents[1] / "press_tr"


class FakeDocument:
	def __init__(self, values, previous=None):
		self.__dict__.update(copy.deepcopy(values))
		self.resources = [SimpleNamespace(**row) for row in values.get("resources", [])]
		self.previous = previous
		self.add_comment = Mock()
		self.save = Mock()
		self.insert = Mock()

	def get(self, field):
		return getattr(self, field, None)

	def as_dict(self):
		result = {
			key: value
			for key, value in vars(self).items()
			if key not in {"previous", "add_comment", "save", "insert"}
		}
		result["resources"] = [vars(row).copy() for row in self.resources]
		return result

	def get_doc_before_save(self):
		return self.previous


class SupportServiceTest(unittest.TestCase):
	def setUp(self):
		self.framework = ModuleType("frappe")
		self.framework._ = lambda text: text
		self.framework.PermissionError = PermissionError
		self.framework.session = SimpleNamespace(user="support@example.test")
		self.framework.local = SimpleNamespace(request=SimpleNamespace(path="/app", method="GET"), job=None)
		self.framework.get_roles = Mock(return_value=["Press Support Agent"])
		self.framework.get_doc = Mock()
		self.framework.db = SimpleNamespace(
			get_value=Mock(return_value="owner@example.test"), exists=Mock(return_value=False)
		)
		self.targets = {
			name: object()
			for name in [
				"request_access",
				"approve_access",
				"revoke_access",
				"site_status",
				"open_tenant_session",
			]
		}
		self.framework.get_attr = lambda path: self.targets[path.rsplit(".", 1)[-1]]

		def throw(message, exception):
			raise exception(message)

		self.framework.throw = throw
		utils = ModuleType("frappe.utils")
		utils.get_datetime = lambda value: value
		utils.now_datetime = lambda: NOW
		handler = ModuleType("frappe.handler")
		handler.logout = object()
		press_utils = ModuleType("press.utils")
		press_utils.get_current_team = lambda: "support-team"
		self.modules = patch.dict(
			sys.modules,
			{
				"frappe": self.framework,
				"frappe.utils": utils,
				"frappe.handler": handler,
				"press": ModuleType("press"),
				"press.utils": press_utils,
			},
		)
		self.modules.start()
		self.addCleanup(self.modules.stop)
		spec = importlib.util.spec_from_file_location(
			"isolated_support_service", APP / "support" / "service.py"
		)
		self.service = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(self.service)

	def grant(self, **changes):
		values = accepted(
			custom_ptr_approved_by="owner@example.test",
			custom_ptr_approved_at=NOW,
			custom_ptr_consent_version=1,
		)
		values.update(changes)
		doc = FakeDocument(values)
		site = SimpleNamespace(
			name="tenant.example.test", team="customer-team", status="Active", config="must not be returned"
		)
		self.framework.get_doc.side_effect = [doc, site]
		return doc, site

	def test_each_read_locks_the_grant_and_returns_only_bounded_status(self):
		doc, _site = self.grant()
		self.assertEqual(
			self.service.site_status("consent-1"), {"site": "tenant.example.test", "status": "Active"}
		)
		self.assertEqual(self.framework.get_doc.call_args_list[0].kwargs, {"for_update": True})
		audit = json.loads(html.unescape(doc.add_comment.call_args.kwargs["text"]))
		self.assertEqual(audit["event"], "site_status_read")
		self.assertEqual(audit["reason"], "Investigate failed backup")
		self.assertEqual(audit["consent"], "consent-1")
		self.assertEqual(audit["actor"], "support@example.test")

	def test_native_legacy_approval_cannot_be_used(self):
		for changes in [
			{"custom_ptr_consent_version": 0},
			{"custom_ptr_approved_by": None},
			{"custom_ptr_approved_at": None},
		]:
			with self.subTest(changes=changes):
				self.grant(**changes)
				with self.assertRaises(PermissionError):
					self.service.site_status("consent-1")
				self.assertEqual(self.framework.get_doc.call_count, 1)
				self.framework.get_doc.reset_mock()

	def test_expiry_revocation_requester_and_admin_scope_are_checked_before_read(self):
		for changes in [
			{"access_allowed_till": NOW},
			{"status": "Revoked"},
			{"requested_by": "other@example.test"},
			{"login_as_administrator": 1},
		]:
			with self.subTest(changes=changes):
				self.grant(**changes)
				with self.assertRaises(PermissionError):
					self.service.site_status("consent-1")
				self.assertEqual(self.framework.get_doc.call_count, 1)
				self.framework.get_doc.reset_mock()

	def test_transferred_site_cannot_reuse_old_owner_consent(self):
		doc, site = self.grant()
		site.team = "new-team"
		with self.assertRaises(PermissionError):
			self.service.site_status("consent-1")
		doc.add_comment.assert_not_called()

	def test_audit_failure_does_not_return_support_data(self):
		doc, _site = self.grant()
		doc.add_comment.side_effect = RuntimeError("audit unavailable")
		with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
			self.service.site_status("consent-1")

	def test_approval_is_stamped_by_server_after_customer_validation(self):
		self.framework.session.user = "owner@example.test"
		doc = FakeDocument(accepted(), FakeDocument(request()))
		self.service.validate_support_access(doc)
		self.assertEqual(doc.custom_ptr_approved_by, "owner@example.test")
		self.assertEqual(doc.custom_ptr_approved_at, NOW)
		self.assertEqual(doc.custom_ptr_consent_version, 1)

	def test_ignore_permissions_cannot_bypass_customer_approval(self):
		self.framework.session.user = "Administrator"
		doc = FakeDocument(accepted(), FakeDocument(request()))
		doc.flags = SimpleNamespace(ignore_permissions=True)
		with self.assertRaises(PermissionError):
			self.service.validate_support_access(doc)

	def test_forged_approval_marker_is_rejected(self):
		doc = FakeDocument(request(custom_ptr_consent_version=1, custom_ptr_approved_by="owner@example.test"))
		with self.assertRaises(PermissionError):
			self.service.validate_support_access(doc)

	def test_native_support_shortcuts_are_closed_even_for_system_user(self):
		self.framework.session.user = "Administrator"
		with self.assertRaises(PermissionError):
			self.service.enforce_support_routes(object())
		for target in self.targets.values():
			self.service.enforce_support_routes(target)

	def test_support_native_login_sid_and_agent_sid_are_closed(self):
		site = self.service.SiteSupportPolicy()
		site.team = "customer-team"
		for method in [site.get_login_sid, lambda: site.get_sid_from_agent("Administrator")]:
			with self.subTest(method=method), self.assertRaises(PermissionError):
				method()

	def test_customer_owner_native_login_is_preserved(self):
		class NativeSite:
			team = "customer-team"

			def get_login_sid(self, user="Administrator"):
				return ("customer_login", user)

			def get_sid_from_agent(self, user):
				return ("customer_agent_login", user)

		class Site(self.service.SiteSupportPolicy, NativeSite):
			pass

		self.framework.get_roles.return_value = ["Press User"]
		self.framework.session.user = "owner@example.test"
		self.assertEqual(Site().get_login_sid(), ("customer_login", "Administrator"))
		self.assertEqual(
			Site().get_sid_from_agent("owner@example.test"), ("customer_agent_login", "owner@example.test")
		)
		for user in ["Guest", "Administrator", "other@example.test"]:
			self.framework.session.user = user
			with self.subTest(user=user), self.assertRaises(PermissionError):
				Site().get_login_sid()

	def native_site(self):
		class NativeSite:
			team = "customer-team"

			def get_login_sid(self, user="Administrator"):
				return self.get_sid_from_agent(user)

			def get_sid_from_agent(self, user):
				return ("native_sid", user)

		class Site(self.service.SiteSupportPolicy, NativeSite):
			pass

		return Site()

	def test_support_session_page_allows_csrf_bootstrap_only_for_safe_page_requests(self):
		self.framework.local.request.path = "/account-deletion"
		for method in ("GET", "HEAD"):
			self.framework.local.request.method = method
			self.service.enforce_support_routes(None)
		for path, method, target in (
			("/app", "GET", None),
			("/account-deletion", "POST", None),
			("/account-deletion/other", "GET", None),
			("/account-deletion", "GET", object()),
		):
			self.framework.local.request = SimpleNamespace(path=path, method=method)
			with self.subTest(path=path, method=method), self.assertRaises(PermissionError):
				self.service.enforce_support_routes(target)

	def test_customer_member_keeps_native_sid_without_becoming_team_owner(self):
		self.framework.session.user = "member@example.test"
		self.framework.get_roles.return_value = ["Press User"]
		self.framework.db.exists.return_value = True
		self.assertEqual(self.native_site().get_login_sid(), ("native_sid", "Administrator"))
		self.framework.db.exists.assert_called_with(
			"Team Member",
			{
				"parent": "customer-team",
				"parenttype": "Team",
				"parentfield": "team_members",
				"user": "member@example.test",
			},
		)

	def test_support_role_cannot_use_customer_membership_for_native_sid(self):
		self.framework.db.exists.return_value = True
		with self.assertRaises(PermissionError):
			self.native_site().get_login_sid()

	def test_administrator_background_job_can_use_native_sid(self):
		self.framework.session.user = "Administrator"
		self.framework.local.request = None
		self.framework.local.job = SimpleNamespace(
			method="press.press.doctype.site.sync.sync_setup_wizard_status"
		)
		self.assertEqual(self.native_site().get_login_sid(), ("native_sid", "Administrator"))

	def test_administrator_http_request_cannot_use_job_context_for_native_sid(self):
		self.framework.session.user = "Administrator"
		self.framework.local.job = SimpleNamespace(
			method="press.press.doctype.site.sync.sync_setup_wizard_status"
		)
		with self.assertRaises(PermissionError):
			self.native_site().get_login_sid()

	def test_administrator_without_worker_context_cannot_use_native_sid(self):
		self.framework.session.user = "Administrator"
		self.framework.local.request = None
		with self.assertRaises(PermissionError):
			self.native_site().get_login_sid()

	def test_customer_actions_lock_record_and_do_not_trust_supplied_actor(self):
		doc = FakeDocument(request())
		self.framework.get_doc.side_effect = None
		self.framework.get_doc.return_value = doc
		with self.assertRaises(PermissionError):
			self.service.approve_access(doc.name)
		doc.save.assert_not_called()
		self.framework.session.user = "owner@example.test"
		self.service.approve_access(doc.name, "6")
		self.assertEqual(doc.status, "Accepted")
		self.assertEqual(doc.allowed_for, "6")
		doc.save.assert_called_once_with()
		self.framework.get_doc.assert_called_with("Support Access", doc.name, for_update=True)

	def test_request_uses_server_identity_and_safe_initial_state(self):
		doc = FakeDocument(request())
		self.framework.get_doc.side_effect = None
		self.framework.get_doc.return_value = doc
		self.service.request_access("tenant.example.test", "Investigate failed backup", True)
		values = self.framework.get_doc.call_args.args[0]
		self.assertEqual(values["requested_by"], "support@example.test")
		self.assertEqual(values["status"], "Pending")
		self.assertEqual(values["login_as_administrator"], 1)
		doc.insert.assert_called_once_with()

	def test_state_audit_keeps_reason_and_escapes_markup(self):
		doc = FakeDocument(request(reason="<script>bad</script>"))
		self.service.audit_support_access(doc)
		payload = doc.add_comment.call_args.kwargs["text"]
		self.assertNotIn("<script>", payload)
		self.assertEqual(json.loads(html.unescape(payload))["reason"], "<script>bad</script>")
