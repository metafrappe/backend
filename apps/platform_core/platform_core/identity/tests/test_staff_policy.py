"""SA-3: the operations site admits only prelinked staff and syncs verified roles."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

SOURCE = Path(__file__).parents[1] / "staff.py"
ISSUER = "https://login.example.test/realms/platform"


class StaffPolicyTest(TestCase):
	def setUp(self):
		self.framework = Mock()
		self.framework._ = lambda text, **kwargs: text
		self.framework.PermissionError = PermissionError
		self.framework.throw.side_effect = lambda message, exception=PermissionError: (_ for _ in ()).throw(
			exception(message)
		)
		self.framework.conf = {
			"platform_staff_login": True,
			"platform_staff_helpdesk_revision": "1" * 40,
			"platform_staff_accounts": {"support@example.test": {"issuer": ISSUER, "subject": "support-sub"}},
		}
		self.framework.db.get_value.side_effect = (
			lambda doctype, *args, **kwargs: "support@example.test"
			if doctype == "PLT Identity Link"
			else (1, "System User")
		)
		self.framework.db.exists.side_effect = lambda doctype, *args, **kwargs: doctype in {"DocType", "Role"}
		self.framework.get_installed_apps.return_value = ["frappe", "platform_core", "helpdesk"]
		self.claims = {
			"iss": ISSUER,
			"sub": "support-sub",
			"groups": ["/platform-operator"],
			"realm_access": {"roles": ["ops-support"]},
		}
		self.user = Mock(
			name="support@example.test",
			full_name="Example Support",
			roles=[],
			role_profiles=[],
			role_profile_name=None,
			flags=SimpleNamespace(ignore_permissions=False),
		)
		self.framework.get_doc.return_value = self.user
		spec = importlib.util.spec_from_file_location("staff_policy_under_test", SOURCE)
		self.policy = importlib.util.module_from_spec(spec)
		with patch.dict(sys.modules, {"frappe": self.framework}):
			spec.loader.exec_module(self.policy)

	def test_prelinked_person_with_verified_group_is_resolved(self):
		self.assertEqual(self.policy.resolve_staff_user(ISSUER, self.claims), "support@example.test")

	def test_group_lookalike_and_service_identity_are_denied(self):
		for changes in [
			{"groups": ["/platform-operator-fake"]},
			{"groups": []},
			{"preferred_username": "service-account-worker"},
			{"sub": "unregistered"},
		]:
			with self.subTest(changes=changes):
				with self.assertRaises(PermissionError):
					self.policy.synchronize_staff("support@example.test", self.claims | changes)

	def test_missing_identity_link_cannot_be_created_by_email(self):
		self.framework.db.get_value.side_effect = None
		self.framework.db.get_value.return_value = None
		with self.assertRaises(PermissionError):
			self.policy.resolve_staff_user(
				ISSUER, self.claims | {"email": "support@example.test", "email_verified": True}
			)
		self.framework.get_doc.assert_not_called()

	def test_first_support_login_creates_one_agent(self):
		self.policy.synchronize_staff("support@example.test", self.claims)
		creates = [
			call.args[0]
			for call in self.framework.get_doc.call_args_list
			if call.args and isinstance(call.args[0], dict)
		]
		self.assertEqual(
			creates,
			[
				{
					"doctype": "HD Agent",
					"user": "support@example.test",
					"agent_name": "Example Support",
					"is_active": 1,
				}
			],
		)
		self.framework.db.exists.side_effect = (
			lambda doctype, *args, **kwargs: "support@example.test" if doctype == "HD Agent" else True
		)
		self.framework.get_doc.reset_mock()
		self.policy.synchronize_staff("support@example.test", self.claims)
		self.assertFalse(
			any(isinstance(call.args[0], dict) for call in self.framework.get_doc.call_args_list if call.args)
		)

	def test_roles_are_reconciled_without_system_manager(self):
		self.user.roles = [SimpleNamespace(role="Accounts Manager"), SimpleNamespace(role="Unrelated Role")]
		self.policy.synchronize_staff("support@example.test", self.claims)
		self.user.remove.assert_called_once_with(self.user.roles[0])
		self.user.append.assert_not_called()
		self.assertNotIn("System Manager", self.policy.MANAGED_ROLES)
		self.assertFalse(self.user.flags.ignore_permissions)

	def test_missing_helpdesk_pin_denies_before_writes(self):
		self.framework.conf.pop("platform_staff_helpdesk_revision")
		with self.assertRaises(PermissionError):
			self.policy.resolve_staff_user(ISSUER, self.claims)
		self.framework.get_doc.assert_not_called()

	def test_removed_support_role_deactivates_agent(self):
		self.user.roles = [SimpleNamespace(role="Agent")]
		self.framework.db.exists.side_effect = (
			lambda doctype, *args, **kwargs: "support@example.test" if doctype == "HD Agent" else True
		)
		agent = Mock(is_active=1, flags=SimpleNamespace(ignore_permissions=False))
		self.framework.get_doc.side_effect = (
			lambda doctype, *args, **kwargs: agent if doctype == "HD Agent" else self.user
		)
		claims = self.claims | {"realm_access": {"roles": ["ops-billing"]}}
		self.policy.synchronize_staff("support@example.test", claims)
		self.assertEqual(agent.is_active, 0)
		self.user.remove.assert_called_once_with(self.user.roles[0])

	def test_last_support_role_removal_is_persisted_before_refusal(self):
		self.user.roles = [SimpleNamespace(role="Agent")]
		self.framework.db.exists.side_effect = (
			lambda doctype, *args, **kwargs: "support@example.test" if doctype == "HD Agent" else True
		)
		agent = Mock(is_active=1, flags=SimpleNamespace(ignore_permissions=False))
		self.framework.get_doc.side_effect = (
			lambda doctype, *args, **kwargs: agent if doctype == "HD Agent" else self.user
		)
		claims = self.claims | {"groups": [], "realm_access": {"roles": []}}
		with self.assertRaises(PermissionError):
			self.policy.synchronize_staff("support@example.test", claims)
		self.assertEqual(agent.is_active, 0)
		self.user.remove.assert_called_once()
		self.framework.db.commit.assert_called_once()

	def test_role_profiles_are_refused_before_saving(self):
		self.user.role_profiles = [SimpleNamespace(role_profile="Old Billing")]
		with self.assertRaises(PermissionError):
			self.policy.synchronize_staff("support@example.test", self.claims)
		self.user.save.assert_not_called()
