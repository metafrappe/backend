"""A tenant support session is bound to one approved consent, one site and one requester (G-18, O-65)."""

import html
import json
import unittest
from datetime import timedelta
from unittest.mock import Mock

import test_support_service as base
from test_support_consent import NOW


class FakeCache:
	"""Frappe's Redis wrapper: prefixed keys, values with a lifetime and an atomic delete count."""

	def __init__(self):
		self.values = {}
		self.lifetimes = {}

	def make_key(self, key):
		return "site|" + key

	def set_value(self, key, value, expires_in_sec=None):
		self.values[self.make_key(key)] = value
		self.lifetimes[self.make_key(key)] = expires_in_sec

	def get_value(self, key):
		return self.values.get(self.make_key(key))

	def delete(self, *keys):
		return sum(1 for key in keys if self.values.pop(key, None) is not None)


class TenantSessionServiceTest(unittest.TestCase):
	setUp_service = base.SupportServiceTest.setUp
	grant = base.SupportServiceTest.grant

	def setUp(self):
		self.setUp_service()
		self.framework.cache = FakeCache()
		self.framework.get_roles = Mock(return_value=["Press Support Agent"])

	def open(self, **changes):
		doc, _site = self.grant(**changes)
		return doc, self.service.open_tenant_session("consent-1")

	def redeem(self, ticket, site="tenant.example.test", **changes):
		doc, _site = self.grant(**changes)
		self.framework.session.user = "Guest"
		return doc, self.service.redeem_tenant_session(ticket, site)

	def started(self):
		_doc, opened = self.open()
		_doc, session = self.redeem(opened["ticket"])
		return session

	def check(self, session_key, site="tenant.example.test", **changes):
		self.grant(**changes)
		return self.service.check_tenant_session(session_key, site)

	# 1 and 7: a valid consent opens a session and the opening is audited with its reason.
	def test_valid_consent_opens_a_ticket_and_audits_the_reason(self):
		doc, opened = self.open()
		self.assertEqual(opened["site"], "tenant.example.test")
		self.assertEqual(opened["expires_in"], 60)
		self.assertGreaterEqual(len(opened["ticket"]), 40)
		audit = json.loads(html.unescape(doc.add_comment.call_args.kwargs["text"]))
		self.assertEqual(audit["event"], "tenant_session_opened")
		self.assertEqual(audit["reason"], "Investigate failed backup")
		self.assertEqual(audit["actor"], "support@example.test")
		self.assertNotIn(opened["ticket"], doc.add_comment.call_args.kwargs["text"])
		self.assertNotIn(opened["ticket"], json.dumps(self.framework.cache.values))

	def test_audit_failure_issues_no_ticket(self):
		doc, _site = self.grant()
		doc.add_comment.side_effect = RuntimeError("audit unavailable")
		with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
			self.service.open_tenant_session("consent-1")
		self.assertEqual(self.framework.cache.values, {})

	# 2: no valid consent, no session.
	def test_missing_or_invalid_consent_opens_nothing(self):
		for changes in [
			{"status": "Pending", "access_allowed_till": None},
			{"status": "Revoked"},
			{"access_allowed_till": NOW},
			{"requested_by": "other@example.test"},
			{"custom_ptr_consent_version": 0},
		]:
			with self.subTest(changes=changes):
				self.grant(**changes)
				with self.assertRaises(PermissionError):
					self.service.open_tenant_session("consent-1")
				self.assertEqual(self.framework.cache.values, {})
				self.framework.get_doc.reset_mock()

	def test_only_support_agents_open_sessions(self):
		self.framework.get_roles.return_value = ["System Manager"]
		with self.assertRaises(PermissionError):
			self.service.open_tenant_session("consent-1")

	def test_ticket_is_single_use_and_rechecks_consent(self):
		_doc, opened = self.open()
		_doc, session = self.redeem(opened["ticket"])
		self.assertEqual(session["consent"], "consent-1")
		self.assertEqual(session["site"], "tenant.example.test")
		self.assertEqual(session["expires_in"], 3 * 3600)
		self.assertGreaterEqual(len(session["session_key"]), 40)
		with self.assertRaises(PermissionError):
			self.redeem(opened["ticket"])

	def test_ticket_is_rechecked_when_redeemed(self):
		_doc, opened = self.open()
		with self.assertRaises(PermissionError):
			self.redeem(opened["ticket"], status="Revoked")

	def test_unknown_or_malformed_ticket_is_denied(self):
		for ticket in ["", "short", "x" * 500, None, "a" * 43]:
			with self.subTest(ticket=ticket), self.assertRaises(PermissionError):
				self.service.redeem_tenant_session(ticket, "tenant.example.test")

	# 3: the session cannot leave the consent's site.
	def test_ticket_cannot_open_another_site(self):
		_doc, opened = self.open()
		with self.assertRaises(PermissionError):
			self.redeem(opened["ticket"], site="other.example.test")

	def test_session_key_cannot_be_checked_for_another_site(self):
		session = self.started()
		with self.assertRaises(PermissionError):
			self.check(session["session_key"], site="other.example.test")

	def test_live_session_check_passes_while_consent_is_valid(self):
		session = self.started()
		self.assertEqual(self.check(session["session_key"]), {"consent": "consent-1", "expires_in": 3 * 3600})

	def test_session_check_does_not_lock_press_rows(self):
		session = self.started()
		self.check(session["session_key"])
		self.assertEqual([call.kwargs for call in self.framework.get_doc.call_args_list[-2:]], [{}, {}])

	def test_cache_failure_is_a_refusal(self):
		_doc, opened = self.open()
		self.framework.cache.delete = Mock(side_effect=RuntimeError("redis down"))
		with self.assertRaises(PermissionError):
			self.redeem(opened["ticket"])

	# 4: expiry ends an open session on its next request.
	def test_expired_consent_ends_an_open_session(self):
		session = self.started()
		with self.assertRaises(PermissionError):
			self.check(session["session_key"], access_allowed_till=NOW)

	# 5: revocation ends an open session on its next request.
	def test_revoked_consent_ends_an_open_session(self):
		session = self.started()
		with self.assertRaises(PermissionError):
			self.check(session["session_key"], status="Revoked")

	def test_requester_who_lost_the_support_role_is_denied(self):
		session = self.started()
		self.framework.get_roles.return_value = []
		with self.assertRaises(PermissionError):
			self.check(session["session_key"])

	def test_transferred_site_ends_an_open_session(self):
		session = self.started()
		_doc, site = self.grant()
		site.team = "new-team"
		with self.assertRaises(PermissionError):
			self.service.check_tenant_session(session["session_key"], "tenant.example.test")

	# 6: an Administrator consent does not open the ordinary support session.
	def test_administrator_consent_does_not_open_a_support_session(self):
		with self.assertRaises(PermissionError):
			self.open(login_as_administrator=1)

	def test_session_lifetime_does_not_outlive_consent(self):
		session = self.started()
		lifetimes = [value for value in self.framework.cache.lifetimes.values() if value != 60]
		self.assertEqual(lifetimes, [3 * 3600])
		self.assertEqual(session["expires_in"], 3 * 3600)

	def test_short_remaining_consent_shortens_the_session(self):
		_doc, opened = self.open(access_allowed_till=NOW + timedelta(minutes=5))
		_doc, session = self.redeem(opened["ticket"], access_allowed_till=NOW + timedelta(minutes=5))
		self.assertEqual(session["expires_in"], 300)


if __name__ == "__main__":
	unittest.main()
