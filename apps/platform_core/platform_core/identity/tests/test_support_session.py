"""Tenant side of the consented support session (G-18, O-65), with isolated framework doubles.

Run: python3 -B -m unittest discover -s backend/apps/platform_core/platform_core/identity/tests
-p test_support_session.py
"""

import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

MODULE = Path(__file__).resolve().parents[1] / "support_session.py"
SITE = "tenant.example.test"
SUPPORT_USER = "support-session@platform.invalid"
SESSION_KEY = "k" * 43
TICKET = "t" * 43


class FakeCache:
	def __init__(self):
		self.values = {}
		self.lifetimes = {}

	def set_value(self, key, value, expires_in_sec=None):
		self.values[key] = value
		self.lifetimes[key] = expires_in_sec

	def get_value(self, key):
		return self.values.get(key)

	def delete_value(self, key):
		self.values.pop(key, None)


class FakeResponse(io.BytesIO):
	def __init__(self, payload, status=200):
		super().__init__(json.dumps(payload).encode())
		self.status = status

	def __enter__(self):
		return self

	def __exit__(self, *args):
		self.close()


class TenantSupportSessionTest(unittest.TestCase):
	def setUp(self):
		self.clock = [1_000_000.0]
		framework = ModuleType("frappe")
		framework._ = lambda text, context=None: text
		framework.PermissionError = PermissionError
		framework.conf = {
			"support_press_url": "https://press.internal.test",
			"support_session_user": SUPPORT_USER,
		}
		framework.cache = FakeCache()
		framework.session = SimpleNamespace(user="Guest", sid="Guest")
		framework.local = SimpleNamespace(site=SITE, request=SimpleNamespace(path="/app", method="GET"))

		def login_as(user):
			framework.session.user = user
			framework.session.sid = "sid-1"

		framework.local.login_manager = SimpleNamespace(login_as=Mock(side_effect=login_as))
		framework.get_roles = Mock(return_value=["PLT Support Session"])
		framework.get_request_header = Mock(return_value=None)
		framework.db = SimpleNamespace(get_value=Mock(return_value=1))

		def throw(message, exception):
			raise exception(message)

		framework.throw = throw
		sessions = ModuleType("frappe.sessions")
		sessions.delete_session = Mock()
		self.framework, self.sessions = framework, sessions
		self.press = Mock(side_effect=self.press_reply)
		self.replies = {}
		modules = patch.dict(sys.modules, {"frappe": framework, "frappe.sessions": sessions})
		modules.start()
		self.addCleanup(modules.stop)
		spec = importlib.util.spec_from_file_location("isolated_support_session", MODULE)
		self.module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(self.module)
		self.module._OPENER = SimpleNamespace(open=self.press)
		self.module.time = SimpleNamespace(time=lambda: self.clock[0])

	def press_reply(self, request, timeout=None):
		method = request.full_url.rsplit("/", 1)[-1]
		self.requests = [*getattr(self, "requests", []), (method, json.loads(request.data))]
		reply = self.replies.get(method)
		if isinstance(reply, Exception):
			raise reply
		return FakeResponse({"message": reply})

	def allow_redeem(self, **changes):
		reply = {"consent": "consent-1", "site": SITE, "expires_in": 3600, "session_key": SESSION_KEY}
		reply.update(changes)
		self.replies["press_tr.api.support.redeem_tenant_session"] = reply

	def allow_check(self, **changes):
		reply = {"consent": "consent-1", "expires_in": 1800}
		reply.update(changes)
		self.replies["press_tr.api.support.check_tenant_session"] = reply

	def deny(self, method):
		self.replies["press_tr.api.support." + method] = HTTPError(
			"https://press.internal.test", 403, "Forbidden", {}, io.BytesIO(b"{}")
		)

	def start(self):
		self.allow_redeem()
		return self.module.start(TICKET)

	def next_request(self):
		self.framework.local.request = SimpleNamespace(path="/app/todo", method="GET")
		return self.module.check_request()

	# 1: a valid consent opens a limited session for this site.
	def test_valid_ticket_opens_a_session_for_the_support_user(self):
		result = self.start()
		self.assertEqual(result, {"user": SUPPORT_USER, "expires_in": 3600})
		self.framework.local.login_manager.login_as.assert_called_once_with(SUPPORT_USER)
		self.assertEqual(
			self.requests, [("press_tr.api.support.redeem_tenant_session", {"ticket": TICKET, "site": SITE})]
		)
		stored = self.framework.cache.values["plt_support_session:sid:sid-1"]
		self.assertEqual(stored["consent"], "consent-1")
		self.assertEqual(self.framework.cache.lifetimes["plt_support_session:sid:sid-1"], 3600)

	# 2: no consent, no session.
	def test_press_refusal_opens_no_session(self):
		self.deny("redeem_tenant_session")
		with self.assertRaises(PermissionError):
			self.module.start(TICKET)
		self.framework.local.login_manager.login_as.assert_not_called()

	def test_unreachable_press_opens_no_session(self):
		self.replies["press_tr.api.support.redeem_tenant_session"] = URLError("down")
		with self.assertRaises(PermissionError):
			self.module.start(TICKET)
		self.framework.local.login_manager.login_as.assert_not_called()

	def test_signed_in_user_cannot_switch_into_a_support_session(self):
		self.framework.session.user = "customer@example.test"
		with self.assertRaises(PermissionError):
			self.start()
		self.press.assert_not_called()

	def test_missing_configuration_opens_no_session(self):
		for key in ["support_press_url", "support_session_user"]:
			with self.subTest(key=key):
				conf = dict(self.framework.conf)
				conf.pop(key)
				with patch.object(self.framework, "conf", conf), self.assertRaises(PermissionError):
					self.start()
		self.framework.local.login_manager.login_as.assert_not_called()

	def test_press_url_must_be_plain_https(self):
		for url in ["http://press.internal.test", "https://user@press.internal.test", "https://p.test/?a=1"]:
			with self.subTest(url=url):
				with (
					patch.dict(self.framework.conf, {"support_press_url": url}),
					self.assertRaises(PermissionError),
				):
					self.start()
		self.press.assert_not_called()

	# 3: the session cannot leave its site.
	def test_grant_for_another_site_is_refused(self):
		self.allow_redeem(site="other.example.test")
		with self.assertRaises(PermissionError):
			self.module.start(TICKET)
		self.framework.local.login_manager.login_as.assert_not_called()

	def test_malformed_press_reply_is_refused(self):
		for changes in [{"expires_in": 0}, {"expires_in": "3600"}, {"session_key": ""}, {"consent": None}]:
			with self.subTest(changes=changes):
				self.allow_redeem(**changes)
				with self.assertRaises(PermissionError):
					self.module.start(TICKET)
		self.framework.local.login_manager.login_as.assert_not_called()

	def test_each_request_is_rechecked_with_press(self):
		self.start()
		self.allow_check()
		self.next_request()
		self.assertEqual(
			self.requests[-1],
			("press_tr.api.support.check_tenant_session", {"session_key": SESSION_KEY, "site": SITE}),
		)
		self.sessions.delete_session.assert_not_called()

	# 4: expiry ends the open session at the next request.
	def test_expired_consent_ends_the_open_session(self):
		self.start()
		self.deny("check_tenant_session")
		with self.assertRaises(PermissionError):
			self.next_request()
		self.sessions.delete_session.assert_called_once()
		self.assertNotIn("plt_support_session:sid:sid-1", self.framework.cache.values)

	def test_local_expiry_ends_the_session_without_asking_press(self):
		self.start()
		self.clock[0] += 3600
		calls = self.press.call_count
		with self.assertRaises(PermissionError):
			self.next_request()
		self.assertEqual(self.press.call_count, calls)
		self.sessions.delete_session.assert_called_once()

	# 5: revocation ends the open session at the next request.
	def test_revoked_consent_ends_the_open_session(self):
		self.start()
		self.allow_check()
		self.next_request()
		self.deny("check_tenant_session")
		with self.assertRaises(PermissionError):
			self.next_request()
		self.sessions.delete_session.assert_called_once()

	def test_unreachable_press_ends_the_open_session(self):
		self.start()
		self.replies["press_tr.api.support.check_tenant_session"] = URLError("down")
		with self.assertRaises(PermissionError):
			self.next_request()
		self.sessions.delete_session.assert_called_once()

	def test_check_for_another_consent_ends_the_session(self):
		self.start()
		self.allow_check(consent="consent-2")
		with self.assertRaises(PermissionError):
			self.next_request()

	def test_support_user_without_a_bound_session_is_refused(self):
		self.framework.session.user = SUPPORT_USER
		self.framework.session.sid = "sid-from-elsewhere"
		with self.assertRaises(PermissionError):
			self.next_request()
		self.sessions.delete_session.assert_called_once()
		self.press.assert_not_called()

	def test_other_users_are_not_affected(self):
		self.framework.session.user = "customer@example.test"
		self.framework.session.sid = "sid-2"
		self.assertIsNone(self.next_request())
		self.press.assert_not_called()

	# 6: the support session is never an administrator session.
	def test_support_user_with_administrator_roles_is_refused(self):
		for roles in [["System Manager"], ["Administrator"], ["PLT Support Session", "System Manager"]]:
			with self.subTest(roles=roles):
				self.framework.get_roles.return_value = roles
				with self.assertRaises(PermissionError):
					self.start()
		self.framework.local.login_manager.login_as.assert_not_called()

	def test_administrator_or_disabled_user_cannot_be_the_support_user(self):
		with (
			patch.dict(self.framework.conf, {"support_session_user": "Administrator"}),
			self.assertRaises(PermissionError),
		):
			self.start()
		self.framework.db.get_value.return_value = 0
		with self.assertRaises(PermissionError):
			self.start()
		self.framework.local.login_manager.login_as.assert_not_called()

	def test_header_authenticated_support_requests_are_refused(self):
		self.start()
		self.allow_check()
		calls = self.press.call_count
		self.framework.get_request_header = Mock(return_value="token agent-token")
		with self.assertRaises(PermissionError):
			self.next_request()
		self.assertEqual(self.press.call_count, calls)

	def test_realtime_connections_are_refused_for_the_support_user(self):
		self.start()
		self.allow_check()
		for path in [
			"/api/method/frappe.realtime.get_user_info",
			"/api/v2/method/frappe.realtime.get_user_info",
		]:
			with self.subTest(path=path):
				self.framework.local.request = SimpleNamespace(path=path, method="GET")
				with self.assertRaises(PermissionError):
					self.module.check_request()

	def test_administrator_role_granted_later_ends_the_session(self):
		self.start()
		self.allow_check()
		self.framework.get_roles.return_value = ["PLT Support Session", "System Manager"]
		with self.assertRaises(PermissionError):
			self.next_request()
		self.sessions.delete_session.assert_called_once()

	def test_truncated_press_reply_ends_the_session(self):
		import http.client

		self.start()
		self.replies["press_tr.api.support.check_tenant_session"] = http.client.IncompleteRead(b"")
		with self.assertRaises(PermissionError):
			self.next_request()
		self.sessions.delete_session.assert_called_once()

	def test_session_key_is_never_returned_to_the_browser(self):
		result = self.start()
		self.assertNotIn(SESSION_KEY, json.dumps(result))


if __name__ == "__main__":
	unittest.main()
