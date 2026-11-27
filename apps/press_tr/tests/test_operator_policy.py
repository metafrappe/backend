"""SA-1/SA-2 acceptance: individual actors, closed service roles and financial writes."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

SOURCE = Path(__file__).parents[1] / "press_tr/press_identity/operators.py"
# Fake request values; they must never reach the audit record.
API_FIXTURE = "fixture-secret"
LOGIN_FIXTURE = "fixture-password"


class OperatorPolicyTest(TestCase):
	def setUp(self):
		self.framework = Mock()
		self.framework._ = lambda text, **kwargs: text
		self.framework.PermissionError = PermissionError
		self.framework.throw.side_effect = lambda message, exception=PermissionError: (_ for _ in ()).throw(
			exception(message)
		)
		self.framework.conf = {
			"press_operator_accounts": {
				"billing@example.test": {
					"issuer": "https://login.example.test/realms/platform",
					"subject": "billing-sub",
				}
			},
			"press_service_users": ["bridge@example.test"],
		}
		self.framework.session.user = "billing@example.test"
		self.framework.get_roles.return_value = ["Press Ops Billing"]
		self.framework.db.get_value.side_effect = (
			lambda doctype, *args, **kwargs: (1, "System User")
			if doctype == "User"
			else SimpleNamespace(name="fixture-link", user="billing@example.test")
		)
		self.framework.db.exists.return_value = False
		self.framework.request.method = "POST"
		self.framework.local = SimpleNamespace()
		self.framework.form_dict = {"api_secret": API_FIXTURE, "password": LOGIN_FIXTURE}
		self.framework.get_request_header.return_value = API_FIXTURE
		spec = importlib.util.spec_from_file_location("operator_policy_under_test", SOURCE)
		self.policy = importlib.util.module_from_spec(spec)
		with patch.dict(sys.modules, {"frappe": self.framework}):
			spec.loader.exec_module(self.policy)

	def test_human_request_records_only_authenticated_actor(self):
		self.policy.guard_request()
		record = self.framework.logger.return_value.info.call_args.args[0]
		self.assertEqual(record["actor"], "billing@example.test")
		self.assertNotIn(API_FIXTURE, str(record))
		self.assertNotIn(LOGIN_FIXTURE, str(record))
		self.assertNotIn("Authorization", str(record))

	def test_service_account_cannot_hold_any_human_role(self):
		for role in ["Press Ops Billing", "Press Support Agent", "System Manager", "Press User"]:
			with self.subTest(role=role):
				self.framework.session.user = "bridge@example.test"
				self.framework.get_roles.return_value = [role]
				with self.assertRaises(PermissionError):
					self.policy.guard_request()

	def test_unregistered_support_is_denied(self):
		self.framework.session.user = "outsider@example.test"
		self.framework.get_roles.return_value = ["Press Support Agent"]
		with self.assertRaises(PermissionError):
			self.policy.guard_request()

	def test_every_support_call_is_audited_without_payload(self):
		self.framework.get_roles.return_value = ["Press Support Agent"]
		self.policy.guard_request()
		self.assertTrue(self.framework.logger.return_value.info.call_args.args[0]["privileged_support"])

	def test_service_role_validation_applies_when_saving_user(self):
		user = SimpleNamespace(
			name="bridge@example.test",
			roles=[SimpleNamespace(role="Press Ops Billing")],
			user_type="System User",
		)
		with self.assertRaises(PermissionError):
			self.policy.validate_user_roles(user)

	def test_billing_permission_matrix_is_bounded(self):
		permissions = self.policy.BILLING_PERMISSIONS
		self.assertEqual(
			set(permissions), {"Invoice", "Balance Transaction", "Payment Due Extension", "Team"}
		)
		for doctype in ["Invoice", "Balance Transaction"]:
			self.assertTrue({"read", "write", "create", "submit"} <= set(permissions[doctype]))
		self.assertNotIn("delete", permissions["Team"])

	def test_operator_with_website_user_type_is_denied(self):
		self.framework.db.get_value.side_effect = None
		self.framework.db.get_value.return_value = (1, "Website User")
		with self.assertRaises(PermissionError):
			self.policy.guard_request()

	def test_registered_operator_requires_matching_identity_link(self):
		self.framework.db.get_value.side_effect = (
			lambda doctype, *args, **kwargs: (1, "System User") if doctype == "User" else None
		)
		with self.assertRaises(PermissionError):
			self.policy.guard_request()

	def test_claim_role_requires_exact_group(self):
		claims = {"groups": ["/platform-operator-other"], "realm_access": {"roles": ["ops-support"]}}
		self.assertEqual(self.policy.verified_roles(claims), set())

	def test_bound_operator_uses_issuer_subject_and_never_email(self):
		claims = {
			"iss": "https://login.example.test/realms/platform",
			"sub": "billing-sub",
			"email": "somebody-else@example.test",
			"groups": ["/platform-operator"],
			"realm_access": {"roles": ["ops-billing"]},
		}
		doc = Mock(
			enabled=1,
			user_type="System User",
			roles=[],
			role_profiles=[],
			role_profile_name=None,
			flags=SimpleNamespace(ignore_permissions=False),
		)
		self.framework.get_doc.return_value = doc
		helper = Mock()
		with patch.dict(sys.modules, {"press_tr.press_identity.accounts": helper}):
			link = self.policy.bind_operator(claims)
		self.assertEqual(link.user, "billing@example.test")
		self.framework.get_doc.assert_called_with("User", "billing@example.test", for_update=True)
		doc.append.assert_called_once_with("roles", {"role": "Press Ops Billing"})

	def test_removed_operator_role_cannot_fall_back_to_customer_login(self):
		claims = {
			"iss": "https://login.example.test/realms/platform",
			"sub": "billing-sub",
			"groups": [],
			"realm_access": {"roles": []},
		}
		with self.assertRaises(PermissionError):
			self.policy.bind_operator(claims)

	def test_normal_customer_keeps_existing_login_flow(self):
		self.assertIsNone(
			self.policy.bind_operator(
				{"iss": "https://login.example.test/realms/platform", "sub": "customer-sub"}
			)
		)

	def test_installed_hooks_cover_every_financial_write_path(self):
		import runpy

		hooks = runpy.run_path(str(SOURCE.parents[1] / "hooks.py"))
		self.assertIn("press_tr.press_identity.operators.guard_request", hooks["auth_hooks"])
		self.assertIn("press_tr.press_identity.financial_policy.guard_request", hooks["auth_hooks"])
		self.assertNotIn("Invoice", hooks["doc_events"])
		self.assertNotIn("Balance Transaction", hooks["doc_events"])
		self.assertIn("press_tr.press_identity.operators.install_permissions", hooks["after_install"])
		self.assertIn("press_tr.press_identity.operators.install_permissions", hooks["after_migrate"])

	def test_last_role_removal_clears_grants_before_refusal(self):
		claims = {
			"iss": "https://login.example.test/realms/platform",
			"sub": "billing-sub",
			"groups": [],
			"realm_access": {"roles": []},
		}
		doc = Mock(
			enabled=1,
			user_type="System User",
			roles=[SimpleNamespace(role="Press Support Agent")],
			role_profiles=[],
			role_profile_name=None,
			flags=SimpleNamespace(ignore_permissions=False),
		)
		self.framework.get_doc.return_value = doc
		helper = Mock()
		with patch.dict(sys.modules, {"press_tr.press_identity.accounts": helper}):
			with self.assertRaises(PermissionError):
				self.policy.bind_operator(claims)
		doc.remove.assert_called_once_with(doc.roles[0])
		helper.save_authorized_document.assert_called_once_with(doc)
		self.framework.db.commit.assert_called_once()

	def test_role_profile_cannot_restore_billing_role(self):
		claims = {
			"iss": "https://login.example.test/realms/platform",
			"sub": "billing-sub",
			"groups": ["/platform-operator"],
			"realm_access": {"roles": ["ops-support"]},
		}
		doc = Mock(
			enabled=1,
			user_type="System User",
			roles=[],
			role_profiles=[SimpleNamespace(role_profile="Old Billing")],
			role_profile_name=None,
		)
		self.framework.get_doc.return_value = doc
		with patch.dict(sys.modules, {"press_tr.press_identity.accounts": Mock()}):
			with self.assertRaises(PermissionError):
				self.policy.bind_operator(claims)

	def test_upgrade_removes_extra_billing_rights_without_editing_customer_rows(self):
		permissions = Mock()
		self.framework.db.exists.return_value = True
		self.framework.get_all.return_value = ["fixture-permission"]
		row = Mock(permlevel=0, if_owner=0)
		self.framework.get_doc.return_value = row
		with patch.dict(sys.modules, {"frappe.permissions": permissions}):
			self.policy.install_permissions()
		row.set.assert_any_call("delete", 0)
		row.set.assert_any_call("write", 0)
		for call in self.framework.get_all.call_args_list:
			self.assertEqual(call.kwargs["filters"]["role"], "Press Ops Billing")
