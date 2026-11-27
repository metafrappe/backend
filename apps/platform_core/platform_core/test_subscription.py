import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4


class PermissionDeniedError(Exception):
	http_status_code = 403


class SubscriptionTest(unittest.TestCase):
	def setUp(self):
		self.clock = 1000
		self.press_key = uuid4().hex
		self.entries = {}
		self.config = {
			"press_subscription_url": "https://press.example.test",
			"sk_example": self.press_key,
			"platform_subscriptions": {
				"example": {
					"enabled": True,
					"permission_doctype": "Example Record",
					"trial_ends_at": 1060,
					"trial_plan": "pro",
					"plans": {
						"pro": {"features": ["export_report"]},
						"basic": {"features": ["overview"], "read_only": True},
					},
				}
			},
		}
		self.cache = SimpleNamespace(
			get_value=self.cache_get,
			set_value=self.cache_set,
			delete_value=lambda key: self.entries.pop((self.frappe.local.site, key), None),
		)
		self.frappe = SimpleNamespace(
			conf=self.config,
			local=SimpleNamespace(site="tenant.example.test", response_headers={}),
			session=SimpleNamespace(user="account@example.test"),
			cache=self.cache,
			get_installed_apps=Mock(return_value=["example"]),
			PermissionError=PermissionDeniedError,
			has_permission=Mock(return_value=True),
			throw=self.raise_permission,
			_=str,
			whitelist=lambda **options: lambda function: function,
		)
		source = Path(__file__).with_name("subscription.py")
		spec = importlib.util.spec_from_file_location("subscription_under_test", source)
		self.gate = importlib.util.module_from_spec(spec)
		self.response = {
			"site": "tenant.example.test",
			"document_name": "example",
			"plan": "pro",
			"enabled": 1,
		}
		self.post = Mock(
			return_value=SimpleNamespace(status_code=200, json=lambda: {"message": self.response})
		)
		with patch.dict(
			sys.modules,
			{
				"frappe": self.frappe,
				"requests": SimpleNamespace(post=self.post, RequestException=OSError),
			},
		):
			spec.loader.exec_module(self.gate)
		self.gate.time = lambda: self.clock

	def raise_permission(self, message, exception):
		raise exception(message)

	def cache_get(self, key, **options):
		snapshot, expires = self.entries.get((self.frappe.local.site, key), (None, 0))
		return snapshot if self.clock < expires else None

	def cache_set(self, key, snapshot, expires_in_sec=None):
		self.entries[self.frappe.local.site, key] = (snapshot, self.clock + (expires_in_sec or 10000))

	def test_press_plan_is_site_bound_and_refetched_after_expiry(self):
		self.assertTrue(self.gate.has_feature("example", "export_report"))
		self.assertEqual(self.gate.feature_decision("example", "export_report")["plan"], "pro")
		self.post.assert_called_once_with(
			"https://press.example.test/api/method/press.api.developer.marketplace.get_subscription_info",
			json={"secret_key": self.press_key},
			timeout=3,
			allow_redirects=False,
		)
		self.frappe.local.site = "another.example.test"
		self.assertFalse(self.gate.has_feature("example", "export_report"))
		self.frappe.local.site = "tenant.example.test"
		self.response["plan"] = "basic"
		self.clock += self.gate.CACHE_SECONDS
		self.assertEqual(self.gate.feature_decision("example", "export_report")["plan"], "basic")
		self.assertFalse(self.gate.has_feature("example", "export_report"))
		self.assertEqual(self.post.call_count, 3)
		self.assertTrue(self.gate.has_feature("example", "overview", operation="read"))
		self.assertFalse(self.gate.has_feature("example", "overview"))

	def test_ui_and_server_agree_after_trial_ends(self):
		self.assertTrue(self.gate.feature_decision("example", "export_report")["allowed"])
		self.clock = 1060
		decision = self.gate.feature_decision("example", "export_report")
		self.assertFalse(decision["allowed"])
		self.assertTrue(decision["state"]["read_only"])
		self.assertTrue(self.gate.has_feature("example", "export_report", operation="read"))
		self.assertTrue(self.gate.feature_decision("example", "export_report", "read")["allowed"])
		self.assertEqual(decision["allowed"], self.gate.has_feature("example", "export_report"))

	def test_suspension_invalidates_plan_and_keeps_export_open(self):
		@self.gate.require_feature("example", "export_report")
		def save():
			return "saved"

		@self.gate.require_feature("example", "export_report", operation="export")
		def export():
			return "data"

		self.assertEqual(save(), "saved")
		self.post.return_value.status_code = 401
		self.gate.subscription_update_hook()
		with self.assertRaises(PermissionDeniedError) as denied:
			save()
		self.assertEqual(denied.exception.http_status_code, 403)
		self.assertTrue(self.gate.feature_decision("example", "export_report")["state"]["suspended"])
		self.assertEqual(export(), "data")
		self.assertEqual(self.post.call_count, 2)

	def test_local_disable_and_uninstalled_app(self):
		settings = self.config["platform_subscriptions"]["example"]
		settings["enabled"] = False
		self.assertFalse(self.gate.has_feature("example", "export_report"))
		self.frappe.get_installed_apps.return_value = []
		self.assertFalse(self.gate.has_feature("example", "export_report", operation="export"))
		self.frappe.get_installed_apps.assert_called_with(_ensure_on_bench=True)

	def test_feature_decision_guest_denied(self):
		self.frappe.session.user = "Guest"
		with self.assertRaises(PermissionDeniedError):
			self.gate.feature_decision("example", "export_report")
		self.post.assert_not_called()

	def test_native_press_expiry_belongs_to_trial_subscription(self):
		settings = self.config["platform_subscriptions"]["example"]
		del settings["trial_ends_at"]
		self.response.pop("site")
		self.config["subscription"] = {"secret_key": uuid4().hex, "expiry": "1970-01-01T00:00:00Z"}
		self.assertTrue(self.gate.has_feature("example", "export_report"))
		self.config["subscription"]["secret_key"] = self.config["sk_example"]
		self.assertFalse(self.gate.has_feature("example", "export_report"))
		settings["plans"]["paid"] = {"features": ["export_report"]}
		self.response["plan"] = "paid"
		self.gate.subscription_update_hook()
		self.assertTrue(self.gate.has_feature("example", "export_report"))

	def test_metadata_invalidates_after_commit_and_removes_old_plan(self):
		self.assertTrue(self.gate.has_feature("example", "export_report"))
		previous_key = next(iter(self.entries))
		self.frappe.db = SimpleNamespace(after_commit=Mock())
		self.gate.meta_changed()
		self.response["plan"] = "basic"
		self.assertTrue(self.gate.has_feature("example", "export_report"))
		self.frappe.db.after_commit.add.call_args.args[0]()
		self.assertNotIn(previous_key, self.entries)
		self.assertFalse(self.gate.has_feature("example", "export_report"))

	def test_feature_decision_foreign_data_denied(self):
		self.frappe.has_permission.return_value = False
		with self.assertRaises(PermissionDeniedError):
			self.gate.feature_decision("example", "export_report")
		self.frappe.has_permission.assert_called_once_with("Example Record", ptype="read", print_logs=False)
		self.post.assert_not_called()

	def test_press_reply_for_another_app_is_denied(self):
		self.response["document_name"] = "different-app"
		self.assertFalse(self.gate.has_feature("example", "export_report"))

	def test_in_flight_press_read_cannot_restore_invalidated_plan(self):
		previous_response = self.post.return_value

		def cross_update(*args, **kwargs):
			self.gate.subscription_update_hook()
			return previous_response

		self.post.side_effect = cross_update
		self.assertFalse(self.gate.has_feature("example", "export_report"))
		self.post.side_effect = None
		self.response["plan"] = "basic"
		self.assertFalse(self.gate.has_feature("example", "export_report"))
		self.assertEqual(self.post.call_count, 2)
