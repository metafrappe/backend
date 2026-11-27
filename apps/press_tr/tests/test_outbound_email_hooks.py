"""The Frappe hooks connect Email Queue delivery and subjects to the G-17 and G-47 rules.

A small stand-in replaces `frappe`, so the test runs without a site. Values are synthetic.
"""

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeCache:
	def __init__(self):
		self.values, self.expiry = {}, {}

	def make_key(self, key):
		return f"db-a|{key}".encode()

	def incr(self, key):
		self.values[key] = self.values.get(key, 0) + 1
		return self.values[key]

	def expire(self, key, seconds):
		self.expiry[key] = seconds


def fake_frappe(conf=None, in_test=False, testing_email=False):
	module = types.ModuleType("frappe")
	module.conf = conf or {}
	module.local = types.SimpleNamespace(site="tenant-a.example.test")
	module.flags = types.SimpleNamespace(in_test=in_test, testing_email=testing_email)
	module.cache = FakeCache()
	module._ = lambda message, context=None: {"Your sites have been suspended on Frappe Cloud": message}.get(
		message, "Siteleriniz durduruldu"
	)
	return module


class FakeAccount:
	email_id = "notice@tenant.example.test"
	smtp_server = "relay.example.test"
	smtp_port = 587
	use_tls = 1
	use_ssl_for_outgoing = 0
	login_id = ""
	login_id_is_different = 0
	no_smtp_authentication = 0
	always_use_account_email_id_as_sender = 1
	_password = "synthetic-password"


class HooksTest(unittest.TestCase):
	def load(self, frappe):
		self.enterContext(patch.dict(sys.modules, {"frappe": frappe}))
		sys.modules.pop("press_tr.outbound_email.hooks", None)
		# import_module reads sys.modules, so each test gets a fresh module bound to its own stand-in.
		hooks = importlib.import_module("press_tr.outbound_email.hooks")
		self.addCleanup(sys.modules.pop, "press_tr.outbound_email.hooks", None)
		return hooks

	def queue(self):
		return Mock(get_email_account=Mock(return_value=FakeAccount()))

	def test_queue_delivery_passes_account_policy_and_site_to_the_rules(self):
		policy = {"enabled": True, "quota": {"feature": "outbound_email_daily", "plan": "p", "limit": 5}}
		hooks = self.load(fake_frappe({"outbound_email_policy": policy}))
		with patch.object(hooks.delivery, "deliver") as deliver:
			hooks.send_queued(
				self.queue(), "Atonota <notice@tenant.example.test>", "reader@example.test", b"m"
			)
		kwargs = deliver.call_args.kwargs
		self.assertEqual(kwargs["site"], "tenant-a.example.test")
		self.assertEqual(kwargs["sender"], "notice@tenant.example.test")
		self.assertEqual(kwargs["policy"], policy)
		self.assertEqual(kwargs["account"]["login_id"], "notice@tenant.example.test")
		self.assertEqual(kwargs["account"]["password"], "synthetic-password")
		self.assertEqual(kwargs["account"]["smtp_port"], 587)

	def test_missing_policy_denies_delivery(self):
		hooks = self.load(fake_frappe())
		with (
			patch.object(hooks.delivery.smtplib, "SMTP") as smtp,
			self.assertRaises(hooks.delivery.DeliveryDenied),
		):
			hooks.send_queued(self.queue(), "notice@tenant.example.test", "reader@example.test", b"m")
		smtp.assert_not_called()

	def test_test_runs_keep_frappe_test_behaviour(self):
		hooks = self.load(fake_frappe(in_test=True))
		with patch.object(hooks.delivery, "deliver") as deliver:
			hooks.send_queued(self.queue(), "notice@tenant.example.test", "reader@example.test", b"m")
		deliver.assert_not_called()

	def test_daily_quota_counter_is_per_site_and_stops_after_the_limit(self):
		frappe = fake_frappe()
		hooks = self.load(frappe)
		results = [hooks.reserve_daily(site="tenant-a", plan="p", limit=2) for _ in range(3)]
		self.assertEqual(results, [True, True, False])
		(key,) = frappe.cache.values
		self.assertTrue(key.startswith(b"db-a|outbound_email_daily:"))
		self.assertEqual(frappe.cache.expiry[key], 2 * 24 * 60 * 60)

	def test_known_press_subject_is_rewritten_on_the_message(self):
		hooks = self.load(fake_frappe())
		email = Mock(subject="Your sites have been suspended on Frappe Cloud")
		hooks.localize_subject(email)
		self.assertEqual(email.subject, "Siteleriniz durduruldu")
		email.set_header.assert_called_once_with("Subject", "Siteleriniz durduruldu")

	def test_unknown_subject_is_not_touched(self):
		hooks = self.load(fake_frappe())
		email = Mock(subject="Your login code")
		hooks.localize_subject(email)
		self.assertEqual(email.subject, "Your login code")
		email.set_header.assert_not_called()

	def test_hooks_are_registered_once(self):
		source = (Path(__file__).resolve().parents[1] / "press_tr/hooks.py").read_text()
		self.assertEqual(source.count("\noverride_email_send ="), 1)
		self.assertEqual(source.count("\nmake_email_body_message ="), 1)
		self.assertIn('"press_tr.outbound_email.hooks.send_queued"', source)
		self.assertIn('"press_tr.outbound_email.hooks.localize_subject"', source)


if __name__ == "__main__":
	unittest.main()
