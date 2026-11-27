"""Acceptance checks for G-47. All addresses and credentials are synthetic.

The rules live in a module that does not import Frappe, so these tests run without a site (O-69).
"""

import copy
import ssl
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from press_tr.outbound_email.delivery import DeliveryDenied, deliver


class DeliveryTest(unittest.TestCase):
	def setUp(self):
		self.account = {
			"email_id": "notice@tenant.example.test",
			"smtp_server": "relay.example.test",
			"smtp_port": 587,
			"use_tls": 1,
			"use_ssl_for_outgoing": 0,
			"login_id": "synthetic-user",
			"password": "synthetic-password",
			"always_use_account_email_id_as_sender": 1,
		}
		self.policy = {
			"enabled": True,
			"verified_senders": [
				{
					"email": self.account["email_id"],
					"smtp_server": self.account["smtp_server"],
					"spf": True,
					"dkim": True,
					"dmarc": True,
					"ptr": True,
				}
			],
			"quota": {"feature": "outbound_email_daily", "plan": "example-plan", "limit": 2},
		}
		self.message = (
			b"From: notice@tenant.example.test\r\nTo: reader@example.test\r\nSubject: Example\r\n\r\nHello"
		)
		self.reserve = Mock(return_value=True)
		self.smtp = self.enterContext(patch("press_tr.outbound_email.delivery.smtplib.SMTP"))
		self.connection = self.smtp.return_value.__enter__.return_value
		self.connection.sendmail.return_value = {}

	def send(self, **overrides):
		kwargs = dict(
			site="tenant-a",
			sender=self.account["email_id"],
			recipient="reader@example.test",
			message=self.message,
			account=self.account,
			policy=self.policy,
			reserve=self.reserve,
		)
		kwargs.update(overrides)
		return deliver(**kwargs)

	def test_unverified_domain_stops_before_connection_or_quota(self):
		self.policy["verified_senders"] = []
		with self.assertRaises(DeliveryDenied):
			self.send()
		self.smtp.assert_not_called()
		self.reserve.assert_not_called()

	def test_each_required_dns_check_must_be_verified(self):
		for check in ("spf", "dkim", "dmarc", "ptr"):
			with self.subTest(check=check):
				policy = copy.deepcopy(self.policy)
				policy["verified_senders"][0][check] = False
				with self.assertRaises(DeliveryDenied):
					self.send(policy=policy)
		self.smtp.assert_not_called()

	def test_tenant_can_use_its_own_verified_sender(self):
		self.send()
		self.connection.sendmail.assert_called_once_with(
			self.account["email_id"], ["reader@example.test"], self.message
		)

	def test_approval_cannot_be_reused_after_sender_or_relay_change(self):
		for field, value in (
			("email_id", "notice@other.example.test"),
			("smtp_server", "other.example.test"),
		):
			with self.subTest(field=field):
				account = {**self.account, field: value}
				with self.assertRaises(DeliveryDenied):
					self.send(account=account)
		self.smtp.assert_not_called()

	def test_quota_exhaustion_blocks_delivery(self):
		self.reserve.side_effect = [True, True, False]
		self.send()
		self.send()
		with self.assertRaises(DeliveryDenied):
			self.send()
		self.assertEqual(self.connection.sendmail.call_count, 2)
		self.assertTrue(all(call.kwargs["site"] == "tenant-a" for call in self.reserve.call_args_list))

	def test_missing_or_untrusted_plan_quota_blocks_delivery(self):
		for quota in (
			{},
			{"limit": -1},
			{"feature": "unknown", "plan": "plan", "limit": 2},
			{"feature": "outbound_email_daily", "plan": "plan", "limit": True},
		):
			with self.subTest(quota=quota), self.assertRaises(DeliveryDenied):
				self.send(policy={**self.policy, "quota": quota})
		self.smtp.assert_not_called()

	def test_plaintext_or_implicit_tls_configuration_is_rejected(self):
		for change in ({"use_tls": 0}, {"use_tls": "0"}, {"smtp_port": 25}, {"use_ssl_for_outgoing": 1}):
			with self.subTest(change=change), self.assertRaises(DeliveryDenied):
				self.send(account={**self.account, **change})
		self.smtp.assert_not_called()

	def test_starttls_verifies_certificate_before_login_and_send(self):
		self.send()
		context = self.connection.starttls.call_args.kwargs["context"]
		self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
		self.assertTrue(context.check_hostname)
		calls = [c[0] for c in self.connection.method_calls]
		self.assertLess(calls.index("starttls"), calls.index("login"))
		self.assertLess(calls.index("login"), calls.index("sendmail"))

	def test_tls_failure_does_not_send_credentials_or_email(self):
		self.connection.starttls.side_effect = ssl.SSLError("synthetic failure")
		with self.assertRaises(DeliveryDenied):
			self.send()
		self.connection.login.assert_not_called()
		self.connection.sendmail.assert_not_called()

	def test_header_sender_spoof_is_rejected(self):
		with self.assertRaises(DeliveryDenied):
			self.send(message=self.message.replace(b"notice@tenant.example.test", b"other@example.test"))
		self.smtp.assert_not_called()

	def test_quota_store_failure_does_not_send(self):
		self.reserve.side_effect = ConnectionError("synthetic credential in an error")
		with self.assertRaisesRegex(DeliveryDenied, "quota") as result:
			self.send()
		self.assertNotIn("credential", str(result.exception))
		self.smtp.assert_not_called()

	def test_disabled_policy_blocks_without_external_calls(self):
		with self.assertRaises(DeliveryDenied):
			self.send(policy={})
		self.smtp.assert_not_called()
		self.reserve.assert_not_called()


if __name__ == "__main__":
	unittest.main()
