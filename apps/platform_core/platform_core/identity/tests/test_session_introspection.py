"""A Keycloak session that ended closes the Frappe session even without a logout notice (G-163, item 3).

Expected behaviour comes from the G-163 technical design (AJA-403) and docs/contracts.md (D-1):
- the refresh token of the sign-in is kept encrypted, never as plain text in the session record,
- a cookie request asks Keycloak's `introspect` endpoint with that token, as the `site-tenant1` client,
- the answer is cached for 60 seconds, so a second request inside that time does not call Keycloak,
- `active: false` closes the session at once, like the idle timeout (401 `SessionExpired`),
- when Keycloak cannot be reached, the last positive answer stays valid for 300 seconds, then the session closes,
- background requests are checked too.
Only Keycloak itself is faked: `requests.post` answers like the introspection endpoint.
"""

import time
from unittest.mock import patch

import frappe
import requests
from frappe.tests.test_api import FrappeAPITestCase

from platform_core.identity import keycloak_session, provider_setup, session_policy
from platform_core.identity.tests import helpers as h

REFRESH_TOKEN = "plain-refresh-token-0123456789abcdef"
INTROSPECT_URL = "http://identity.localhost:8660/realms/platform/protocol/openid-connect/token/introspect"
SID = "22222222-2222-4222-8222-222222222222"


class FakeResponse:
	def __init__(self, status_code: int, body: dict):
		self.status_code = status_code
		self._body = body

	def json(self):
		return self._body


class FakeKeycloak:
	"""Records introspection calls and answers with a fixed result."""

	def __init__(self, active: bool | None = True, error: Exception | None = None):
		self.active = active
		self.error = error
		self.calls: list[dict] = []

	def __call__(self, url, data=None, **kwargs):
		self.calls.append({"url": url, "data": dict(data or {}), "kwargs": kwargs})
		if self.error is not None:
			raise self.error
		body = {"active": self.active}
		if self.active:
			body.update({"exp": int(time.time()) + 3000, "sid": SID, "typ": "Refresh"})
		return FakeResponse(200, body)


class IntrospectionCase(FrappeAPITestCase):
	"""Shared setup: a fake Keycloak sign-in with a refresh token."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.settings = h.SiteSettings().__enter__()
		cls.addClassCleanup(cls.settings.__exit__, None, None, None)
		provider_setup.ensure_social_login_key()
		h.ensure_user(h.AYSE)
		h.refresh()
		cls.patcher = h.jwks_patch()
		cls.patcher.start()
		cls.addClassCleanup(cls.patcher.stop)

	@classmethod
	def tearDownClass(cls):
		h.clear_links()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		h.clear_links()
		frappe.cache.delete_keys(session_policy.ACTIVITY_PREFIX)
		self.client = h.new_client()

	def _sign_in(self) -> str:
		started, query = h.start_login(self.client)
		self.assertEqual(started.status_code, 200)
		token = h.id_token(query, h.userinfo("sub-ayse", h.AYSE, sid=SID))
		with h.fake_exchange(token, refresh_token=REFRESH_TOKEN):
			response = h.request(
				self.client.get, h.CALLBACK, query_string={"code": "test-code", "state": query["state"]}
			)
		self.assertEqual(response.status_code, 302, response.data[:300])
		self.assertEqual(h.logged_user(self.client), h.AYSE)
		return self.client.get_cookie("sid").value

	def _age_check(self, sid: str, checked_ago: int, ok_ago: int) -> None:
		now = int(time.time())
		keycloak_session.save_state(sid, checked_at=now - checked_ago, ok_at=now - ok_ago)

	def _request(self, headers: dict | None = None):
		return h.request(self.client.get, "/api/method/frappe.auth.get_logged_user", headers=headers or {})


class TestSessionIntrospection(IntrospectionCase):
	def test_constants_are_60_and_300_seconds(self):
		self.assertEqual(keycloak_session.CACHE_SECONDS, 60)
		self.assertEqual(keycloak_session.UNREACHABLE_GRACE_SECONDS, 300)

	def test_refresh_token_is_not_stored_as_plain_text(self):
		self._sign_in()
		self.assertEqual(h.sessions_containing(REFRESH_TOKEN), [])
		h.refresh()
		sessions = frappe.qb.DocType("Sessions")
		raw = (
			frappe.qb.from_(sessions).select(sessions.sessiondata).where(sessions.user == h.AYSE).run()[0][0]
		)
		data = frappe.parse_json(raw)
		stored = data.get("keycloak_refresh_token")
		self.assertTrue(stored)
		self.assertNotEqual(stored, REFRESH_TOKEN)
		self.assertEqual(keycloak_session.decrypt_token(stored), REFRESH_TOKEN)

	def test_inactive_keycloak_session_closes_the_next_cookie_request(self):
		sid = self._sign_in()
		self._age_check(sid, checked_ago=61, ok_ago=61)
		keycloak = FakeKeycloak(active=False)
		with patch.object(requests, "post", side_effect=keycloak):
			response = self._request()
		self.assertEqual(response.status_code, 401, response.data[:300])
		self.assertEqual(response.json.get("exc_type"), "SessionExpired")
		self.assertEqual(h.session_count(h.AYSE), 0)
		self.assertEqual(len(keycloak.calls), 1)
		call = keycloak.calls[0]
		self.assertEqual(call["url"], INTROSPECT_URL)
		self.assertEqual(call["data"].get("token"), REFRESH_TOKEN)
		self.assertEqual(call["data"].get("token_type_hint"), "refresh_token")
		self.assertEqual(call["data"].get("client_id"), "site-tenant1")
		self.assertEqual(call["data"].get("client_secret"), "test-client-secret-fake")
		self.assertNotEqual(call["data"].get("grant_type"), "refresh_token")
		self.assertTrue(call["kwargs"].get("timeout"))

	def test_background_request_is_checked_too(self):
		sid = self._sign_in()
		self._age_check(sid, checked_ago=61, ok_ago=61)
		keycloak = FakeKeycloak(active=False)
		with patch.object(requests, "post", side_effect=keycloak):
			response = self._request({session_policy.BACKGROUND_HEADER: "1"})
		self.assertEqual(response.status_code, 401, response.data[:300])
		self.assertEqual(h.session_count(h.AYSE), 0)
		self.assertEqual(len(keycloak.calls), 1)

	def test_answer_is_cached_for_60_seconds(self):
		sid = self._sign_in()
		self._age_check(sid, checked_ago=61, ok_ago=61)
		keycloak = FakeKeycloak(active=True)
		with patch.object(requests, "post", side_effect=keycloak):
			self.assertEqual(self._request().status_code, 200)
			self.assertEqual(self._request().status_code, 200)
		self.assertEqual(len(keycloak.calls), 1)
		self.assertEqual(h.logged_user(self.client), h.AYSE)

	def test_fresh_sign_in_does_not_call_keycloak_inside_the_cache_time(self):
		self._sign_in()
		keycloak = FakeKeycloak(active=False)
		with patch.object(requests, "post", side_effect=keycloak):
			self.assertEqual(self._request().status_code, 200)
		self.assertEqual(keycloak.calls, [])

	def test_unreachable_keycloak_keeps_the_session_for_300_seconds_then_closes_it(self):
		sid = self._sign_in()
		keycloak = FakeKeycloak(error=requests.ConnectionError("unreachable"))
		self._age_check(sid, checked_ago=61, ok_ago=299)
		with patch.object(requests, "post", side_effect=keycloak):
			self.assertEqual(self._request().status_code, 200)
		self.assertEqual(h.session_count(h.AYSE), 1)
		self._age_check(sid, checked_ago=61, ok_ago=301)
		with patch.object(requests, "post", side_effect=keycloak):
			response = self._request()
		self.assertEqual(response.status_code, 401, response.data[:300])
		self.assertEqual(h.session_count(h.AYSE), 0)
		self.assertEqual(len(keycloak.calls), 2)

	def test_keycloak_error_status_counts_as_unreachable(self):
		sid = self._sign_in()
		self._age_check(sid, checked_ago=61, ok_ago=301)

		def server_error(url, data=None, **kwargs):
			return FakeResponse(503, {})

		with patch.object(requests, "post", side_effect=server_error):
			response = self._request()
		self.assertEqual(response.status_code, 401, response.data[:300])
		self.assertEqual(h.session_count(h.AYSE), 0)

	def test_keycloak_session_without_stored_refresh_token_is_closed(self):
		self._sign_in()
		h.refresh()
		sid = self.client.get_cookie("sid").value
		sessions = frappe.qb.DocType("Sessions")
		raw = frappe.qb.from_(sessions).select(sessions.sessiondata).where(sessions.sid == sid).run()[0][0]
		data = frappe.parse_json(raw)
		data.pop("keycloak_refresh_token", None)
		frappe.qb.update(sessions).set(sessions.sessiondata, frappe.as_json(data, indent=None)).where(
			sessions.sid == sid
		).run()
		frappe.cache.hdel("session", sid)
		keycloak_session.forget(sid)
		h.refresh()
		self._age_check(sid, checked_ago=61, ok_ago=61)
		with patch.object(requests, "post", side_effect=FakeKeycloak(active=True)):
			response = self._request()
		self.assertEqual(response.status_code, 401, response.data[:300])
		self.assertEqual(h.session_count(h.AYSE), 0)


RENEWED_TOKEN = "renewed-refresh-token-fedcba9876543210"


class RotatingKeycloak:
	"""Introspection and token endpoints with per-token answers. The token endpoint rotates the token."""

	def __init__(self, active_tokens: set, expires_in: int = 600, on_introspect=None):
		self.active_tokens = set(active_tokens)
		self.expires_in = expires_in
		self.on_introspect = on_introspect
		self.introspected: list[str] = []
		self.renewed: list[str] = []

	def __call__(self, url, data=None, **kwargs):
		data = dict(data or {})
		if url.endswith("/token/introspect"):
			self.introspected.append(data.get("token"))
			if self.on_introspect:
				self.on_introspect(data.get("token"))
			if data.get("token") in self.active_tokens:
				exp = int(time.time()) + self.expires_in
				return FakeResponse(200, {"active": True, "exp": exp, "sid": SID, "typ": "Refresh"})
			return FakeResponse(200, {"active": False})
		if url.endswith("/token") and data.get("grant_type") == "refresh_token":
			self.renewed.append(data.get("refresh_token"))
			self.active_tokens.discard(data.get("refresh_token"))
			self.active_tokens.add(RENEWED_TOKEN)
			return FakeResponse(
				200, {"refresh_token": RENEWED_TOKEN, "access_token": "fake", "token_type": "Bearer"}
			)
		return FakeResponse(404, {})


class TestSessionIntrospectionReview(IntrospectionCase):
	"""Findings of the independent review (AJA-405): renewal, races, form `sid`, grace on cache hits."""

	def _user_request(self):
		"""A request that counts as user activity. `get_logged_user` is a background method."""
		return h.request(self.client.get, "/api/method/platform_core.api.auth.get_csrf_token")

	def _stored_session_token(self, sid: str) -> str | None:
		h.refresh()
		sessions = frappe.qb.DocType("Sessions")
		raw = frappe.qb.from_(sessions).select(sessions.sessiondata).where(sessions.sid == sid).run()[0][0]
		return keycloak_session.decrypt_token(frappe.parse_json(raw).get("keycloak_refresh_token"))

	def test_session_id_in_the_form_is_checked_too(self):
		sid = self._sign_in()
		self._age_check(sid, checked_ago=61, ok_ago=61)
		keycloak = FakeKeycloak(active=False)
		stranger = h.new_client()
		with patch.object(requests, "post", side_effect=keycloak):
			response = h.request(
				stranger.get, "/api/method/frappe.auth.get_logged_user", query_string={"sid": sid}
			)
		self.assertNotEqual(response.status_code, 200, response.data[:300])
		self.assertEqual(len(keycloak.calls), 1)
		self.assertEqual(h.session_count(h.AYSE), 0)

	def test_expiring_token_is_renewed_and_kept_in_the_session_record(self):
		sid = self._sign_in()
		self._age_check(sid, checked_ago=61, ok_ago=61)
		keycloak = RotatingKeycloak({REFRESH_TOKEN})
		with patch.object(requests, "post", side_effect=keycloak):
			self.assertEqual(self._user_request().status_code, 200)
		self.assertEqual(keycloak.renewed, [REFRESH_TOKEN])
		self.assertEqual(self._stored_session_token(sid), RENEWED_TOKEN)
		self.assertEqual(h.sessions_containing(RENEWED_TOKEN), [])

	def test_renewed_token_survives_a_full_cache_clear(self):
		sid = self._sign_in()
		self._age_check(sid, checked_ago=61, ok_ago=61)
		keycloak = RotatingKeycloak({REFRESH_TOKEN}, expires_in=600)
		with patch.object(requests, "post", side_effect=keycloak):
			self.assertEqual(self._user_request().status_code, 200)
		self.assertEqual(keycloak.renewed, [REFRESH_TOKEN])
		frappe.clear_cache()
		h.refresh()
		self._age_check(sid, checked_ago=61, ok_ago=61)
		keycloak.expires_in = 3000
		with patch.object(requests, "post", side_effect=keycloak):
			self.assertEqual(self._user_request().status_code, 200, "the renewed token must still be found")
		self.assertEqual(keycloak.introspected[-1], RENEWED_TOKEN)
		self.assertEqual(h.session_count(h.AYSE), 1)

	def test_background_request_does_not_renew(self):
		sid = self._sign_in()
		self._age_check(sid, checked_ago=61, ok_ago=61)
		keycloak = RotatingKeycloak({REFRESH_TOKEN})
		with patch.object(requests, "post", side_effect=keycloak):
			response = h.request(
				self.client.get,
				"/api/method/platform_core.api.auth.get_csrf_token",
				headers={session_policy.BACKGROUND_HEADER: "1"},
			)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(keycloak.introspected, [REFRESH_TOKEN])
		self.assertEqual(keycloak.renewed, [])

	def test_inactive_answer_for_a_token_another_request_just_rotated_does_not_close(self):
		sid = self._sign_in()
		self._age_check(sid, checked_ago=61, ok_ago=61)

		def other_request_rotates(token):
			if token == REFRESH_TOKEN:
				# Another worker renewed between our read and Keycloak's answer.
				keycloak.active_tokens = {RENEWED_TOKEN}
				frappe.cache.set_value(
					keycloak_session._token_key(sid),
					keycloak_session.encrypt_token(RENEWED_TOKEN),
					expires_in_sec=keycloak_session.KEY_TTL,
				)

		keycloak = RotatingKeycloak({REFRESH_TOKEN}, expires_in=3000, on_introspect=other_request_rotates)
		with patch.object(requests, "post", side_effect=keycloak):
			response = self._request()
		self.assertEqual(response.status_code, 200, response.data[:300])
		self.assertEqual(keycloak.introspected, [REFRESH_TOKEN, RENEWED_TOKEN])
		self.assertEqual(h.session_count(h.AYSE), 1)

	def test_sign_out_removes_the_renewed_refresh_token(self):
		sid = self._sign_in()
		self._age_check(sid, checked_ago=61, ok_ago=61)
		keycloak = RotatingKeycloak({REFRESH_TOKEN})
		with patch.object(requests, "post", side_effect=keycloak):
			self.assertEqual(self._user_request().status_code, 200)
		token_key = keycloak_session._token_key(sid)
		self.assertIsNotNone(frappe.cache.get_value(token_key, expires=True, use_local_cache=False))
		with patch.object(requests, "post", side_effect=keycloak):
			out = h.request(
				self.client.post,
				"/api/method/platform_core.api.auth.logout",
				headers=h.csrf_headers(self.client),
			)
		self.assertEqual(out.status_code, 200, out.data[:300])
		self.assertIsNone(
			frappe.cache.get_value(token_key, expires=True, use_local_cache=False),
			"kimlik_kc_refresh:<sid> must not outlive the sign-out",
		)
		self.assertIsNone(keycloak_session.load_state(sid))

	def test_cached_answer_does_not_outlive_the_unreachable_grace(self):
		sid = self._sign_in()
		# Keycloak was unreachable at the last check, 10 seconds ago. Its last positive answer is 301 seconds old.
		self._age_check(sid, checked_ago=10, ok_ago=301)
		keycloak = FakeKeycloak(error=requests.ConnectionError("unreachable"))
		with patch.object(requests, "post", side_effect=keycloak):
			response = self._request()
		self.assertEqual(response.status_code, 401, response.data[:300])
		self.assertEqual(h.session_count(h.AYSE), 0)
