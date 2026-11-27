"""Server-side cleanup of session data on sign-out (O-64).

A closed session leaves no activity key and no shell bootstrap cache behind. The user activity key
stays, because other sessions of the same user read it. Keys of other users and other sites stay.
"""

import time

import frappe
from frappe.tests.test_api import FrappeAPITestCase

from platform_core.identity import provider_setup, session_policy
from platform_core.identity.tests import helpers as h
from platform_core.shell.api import BOOTSTRAP_KEY_PREFIX

BACKCHANNEL = "/api/method/platform_core.api.keycloak_backchannel_logout"
LOGOUT = "/api/method/platform_core.api.auth.logout"
SID = "77777777-7777-4777-8777-777777777777"
BOOTSTRAP_KEY = f"{BOOTSTRAP_KEY_PREFIX}generation:scope"


def read(key: str, user: str | None = None):
	return frappe.cache.get_value(key, user=user, expires=True, use_local_cache=False)


def store_bootstrap(user: str) -> None:
	frappe.cache.set_value(BOOTSTRAP_KEY, {"user": user}, user=user, expires_in_sec=60)


class TestSessionCleanup(FrappeAPITestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.settings = h.SiteSettings().__enter__()
		cls.addClassCleanup(cls.settings.__exit__, None, None, None)
		provider_setup.ensure_social_login_key()
		for email in h.SAMPLE_USERS:
			h.ensure_user(email)
		h.refresh()
		cls.key = h.key()
		cls.patcher = h.jwks_patch(cls.key)
		cls.patcher.start()
		cls.addClassCleanup(cls.patcher.stop)

	@classmethod
	def tearDownClass(cls):
		h.clear_links()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		h.clear_links()
		self.client = h.new_client()
		self.addCleanup(frappe.cache.delete_value, BOOTSTRAP_KEY, user=h.AYSE)
		self.addCleanup(frappe.cache.delete_value, BOOTSTRAP_KEY, user=h.MEHMET)

	def sign_in(self, client, sid: str | None = SID) -> str:
		h.login_with_keycloak(client, h.userinfo("sub-ayse", h.AYSE, sid=sid))
		frappe_sid = client.get_cookie("sid").value
		self.assertIsNotNone(read(session_policy._session_key(frappe_sid)))
		store_bootstrap(h.AYSE)
		return frappe_sid

	def assert_cleaned(self, frappe_sid: str) -> None:
		self.assertIsNone(read(session_policy._session_key(frappe_sid)))
		self.assertIsNone(read(BOOTSTRAP_KEY, user=h.AYSE))
		# Other sessions of the user still read the user activity key.
		self.assertIsNotNone(read(session_policy._user_key(h.AYSE)))

	def back_channel(self, payload: dict):
		return h.request(
			h.new_client().post,
			BACKCHANNEL,
			data={"logout_token": self.key.sign(payload)},
			content_type="application/x-www-form-urlencoded",
		)

	def test_logout_clears_session_activity_and_bootstrap_cache(self):
		frappe_sid = self.sign_in(self.client)
		response = h.request(self.client.post, LOGOUT, headers=h.csrf_headers(self.client))
		self.assertEqual(response.status_code, 200, response.data[:300])
		self.assert_cleaned(frappe_sid)

	def test_back_channel_logout_by_sid_clears_the_same_keys(self):
		frappe_sid = self.sign_in(self.client)
		response = self.back_channel(h.logout_payload(sub="sub-ayse", sid=SID))
		self.assertEqual(response.json["message"], {"closed_sessions": 1}, response.data[:300])
		self.assert_cleaned(frappe_sid)

	def test_back_channel_logout_by_subject_clears_the_same_keys(self):
		frappe_sid = self.sign_in(self.client, sid=None)
		response = self.back_channel(
			h.logout_payload(sub="sub-ayse", sid="88888888-8888-4888-8888-888888888888")
		)
		self.assertEqual(response.json["message"], {"closed_sessions": 1}, response.data[:300])
		self.assert_cleaned(frappe_sid)

	def test_logout_keeps_the_bootstrap_cache_of_other_users(self):
		self.sign_in(self.client)
		store_bootstrap(h.MEHMET)
		h.request(self.client.post, LOGOUT, headers=h.csrf_headers(self.client))
		self.assertEqual(read(BOOTSTRAP_KEY, user=h.MEHMET), {"user": h.MEHMET})


class TestForgetSession(FrappeAPITestCase):
	"""Unit checks of the single cleanup function on the local Redis."""

	def test_cleanup_stays_inside_the_site_prefix(self):
		user = "cleanup@example.com"
		sid = "cleanup-sid"
		other_site = [
			f"other_site_db|{session_policy._session_key(sid)}",
			f"other_site_db|user:{user}:{BOOTSTRAP_KEY}",
		]
		for key in other_site:
			frappe.cache.set(key, "1", ex=60)
			self.addCleanup(frappe.cache.delete, key)
		frappe.cache.set_value(session_policy._session_key(sid), int(time.time()), expires_in_sec=60)
		frappe.cache.set_value(session_policy._user_key(user), int(time.time()), expires_in_sec=60)
		self.addCleanup(frappe.cache.delete_value, session_policy._user_key(user))
		store_bootstrap(user)

		session_policy.forget_session(sid, user)

		self.assertIsNone(read(session_policy._session_key(sid)))
		self.assertIsNone(read(BOOTSTRAP_KEY, user=user))
		self.assertIsNotNone(read(session_policy._user_key(user)))
		for key in other_site:
			self.assertEqual(frappe.cache.get(key), b"1", key)

	def test_glob_characters_in_the_user_name_match_only_that_user(self):
		wildcard = "a*@example.com"
		neighbour = "ab@example.com"
		store_bootstrap(wildcard)
		store_bootstrap(neighbour)
		self.addCleanup(frappe.cache.delete_value, BOOTSTRAP_KEY, user=neighbour)

		session_policy.forget_session(None, wildcard)

		self.assertIsNone(read(BOOTSTRAP_KEY, user=wildcard))
		self.assertEqual(read(BOOTSTRAP_KEY, user=neighbour), {"user": neighbour})
