"""Sign-in product account links through Frappe's HTTP dispatch (AJA-473).

Expected values come from the panel contract (`atonota-web`, `src/auth/README.md`, G-159 and G-160)
and from the AJA-458 security review (D-1):

- `start_login?provider=<alias>` adds `kc_idp_hint=<alias>`. Only an open platform of this site is accepted.
- `start_link?provider=<alias>&redirect_to=<path>` needs a session and starts Keycloak's
  `kc_action=idp_link:<alias>` flow. The link must be finished by the same person.
- `unlink_account` takes `{"provider": "<alias>"}` and returns the new list in the
  `list_linked_accounts` shape. The last way to sign in gives 409 `LastSignInMethod`.

The identity-sync service is replaced at the transport function. Its replies follow
`contracts/identity_sync.openapi.yaml`. The real service runs in the backend trial (D-6).
"""

import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.tests.test_api import FrappeAPITestCase

from platform_core.api.test_login_reads import (
	BEARER,
	LEAKY_REPLY,
	OTHER_SUBJECT,
	SERVICE_URL,
	SUBJECT,
	FakeIdentitySync,
	clear_sample_links,
)
from platform_core.identity import login_accounts, provider_setup
from platform_core.identity.tests import helpers as h

PREFIX = "/api/method/platform_core.api.auth."
START_LOGIN = PREFIX + "start_login"
START_LINK = PREFIX + "start_link"
UNLINK = PREFIX + "unlink_account"
UNLINK_PATH = "/v1/linked-accounts/unlink"

OPEN_PROVIDERS = {
	"providers": [
		{"alias": "google", "display_name": "Google"},
		{"alias": "facebook", "display_name": "Facebook"},
	]
}
AFTER_UNLINK = {
	"providers": [
		{"alias": "google", "display_name": "Google", "linked": False},
		{"alias": "facebook", "display_name": "Facebook", "linked": True},
	],
	"local_sign_in_methods": 0,
}


def replies(**extra):
	return {
		"/v1/login-providers": (200, OPEN_PROVIDERS),
		"/v1/linked-accounts": (200, AFTER_UNLINK),
		UNLINK_PATH: (200, AFTER_UNLINK),
		**extra,
	}


def location_query(response) -> dict:
	return {key: value[0] for key, value in parse_qs(urlparse(response.headers["Location"]).query).items()}


class AccountLinkCase(FrappeAPITestCase):
	def setUp(self):
		super().setUp()
		settings = h.SiteSettings({"mobile_identity_sync_url": SERVICE_URL})
		settings.__enter__()
		self.addCleanup(settings.__exit__, None, None, None)
		clear_sample_links()
		h.clear_links()
		self.addCleanup(h.clear_links)
		self.addCleanup(clear_sample_links)
		provider_setup.ensure_social_login_key()
		for user in (h.AYSE, h.MEHMET):
			h.ensure_user(user)
		h.refresh()
		h.reset_rate_limits()
		bearer = patch.object(login_accounts, "identity_sync_bearer", return_value=BEARER)
		bearer.start()
		self.addCleanup(bearer.stop)

	def login(self, user=h.AYSE, subject=SUBJECT):
		client = h.new_client()
		with h.jwks_patch():
			self.assertEqual(h.login_with_keycloak(client, h.userinfo(subject, user)).status_code, 302)
		self.assertEqual(h.logged_user(client), user)
		return client

	def serve(self, fake: FakeIdentitySync):
		transport = patch.object(login_accounts, "_send", fake)
		transport.start()
		self.addCleanup(transport.stop)
		return fake

	def unlink(self, client, body, headers=None):
		return h.request(
			client.post, UNLINK, json=body, headers=h.csrf_headers(client) if headers is None else headers
		)


class TestPanelMethods(AccountLinkCase):
	def test_panel_users_may_call_the_link_methods(self):
		"""The panel account is a Website User. Frappe refuses every method outside this list with 403."""
		allowed = set(frappe.get_hooks("website_user_allowed_methods"))
		for method in ("start_link", "keycloak_callback", "unlink_account"):
			with self.subTest(method=method):
				self.assertIn("platform_core.api.auth." + method, allowed)


class TestStartLoginProvider(AccountLinkCase):
	def test_open_platform_goes_straight_to_its_page(self):
		fake = self.serve(FakeIdentitySync(replies()))
		response = h.request(h.new_client().get, START_LOGIN, query_string={"provider": "google"})
		self.assertEqual(response.status_code, 302, response.data[:300])
		query = location_query(response)
		self.assertEqual(query["kc_idp_hint"], "google")
		self.assertEqual(query["client_id"], h.TEST_SETTINGS["keycloak_client_id"])
		self.assertTrue(response.headers["Location"].startswith(h.ISSUER + "/protocol/openid-connect/auth?"))
		# The site checks the alias against its own open platforms. The check names no person.
		self.assertEqual(fake.calls, [("GET", SERVICE_URL + "/v1/login-providers", None, BEARER)])

	def test_without_provider_no_hint_and_no_call(self):
		fake = self.serve(FakeIdentitySync(replies()))
		response = h.request(h.new_client().get, START_LOGIN)
		self.assertEqual(response.status_code, 302, response.data[:300])
		self.assertNotIn("kc_idp_hint", location_query(response))
		self.assertEqual(fake.calls, [])

	def test_platform_that_is_not_open_is_refused(self):
		self.serve(FakeIdentitySync(replies()))
		for alias in ("linkedin", "tenant2-sso"):
			with self.subTest(alias=alias):
				response = h.request(h.new_client().get, START_LOGIN, query_string={"provider": alias})
				self.assertEqual(response.status_code, 400, response.data[:300])
				self.assertNotIn("Location", response.headers)

	def test_badly_formed_provider_is_refused_without_a_call(self):
		fake = self.serve(FakeIdentitySync(replies()))
		for alias in ("Google", "a/b", "google&kc_action=delete_account", "x" * 65, " "):
			with self.subTest(alias=alias):
				response = h.request(h.new_client().get, START_LOGIN, query_string={"provider": alias})
				self.assertEqual(response.status_code, 400, response.data[:300])
				self.assertNotIn("Location", response.headers)
		self.assertEqual(fake.calls, [])

	def test_platform_check_outage_is_a_plain_503(self):
		self.serve(FakeIdentitySync(error=OSError(f"refused {SERVICE_URL} {BEARER}")))
		response = h.request(h.new_client().get, START_LOGIN, query_string={"provider": "google"})
		self.assertEqual(response.status_code, 503, response.data[:300])
		text = response.data.decode("utf-8")
		for secret in (BEARER, SERVICE_URL, "Traceback"):
			self.assertNotIn(secret, text)


class TestStartLink(AccountLinkCase):
	def start(self, client, **query):
		return h.request(client.get, START_LINK, query_string=query)

	def test_signed_in_user_gets_the_link_address(self):
		fake = self.serve(FakeIdentitySync(replies()))
		client = self.login()
		response = self.start(client, provider="facebook", redirect_to="/account")
		self.assertEqual(response.status_code, 302, response.data[:300])
		query = location_query(response)
		self.assertEqual(query["kc_action"], "idp_link:facebook")
		self.assertNotIn("kc_idp_hint", query)
		self.assertEqual(query["code_challenge_method"], "S256")
		self.assertTrue(query["state"])
		self.assertEqual(fake.calls, [("GET", SERVICE_URL + "/v1/login-providers", None, BEARER)])

	def test_finished_link_returns_to_the_panel_path(self):
		self.serve(FakeIdentitySync(replies()))
		client = self.login()
		sid = client.get_cookie("sid").value
		sessions = h.session_count(h.AYSE)
		query = location_query(self.start(client, provider="facebook", redirect_to="/account"))
		with h.jwks_patch():
			finished = h.finish_login(client, query, h.id_token(query, h.userinfo(SUBJECT, h.AYSE)))
		self.assertEqual(finished.status_code, 302, finished.data[:300])
		self.assertEqual(urlparse(finished.headers["Location"]).path, "/account")
		self.assertEqual(h.logged_user(client), h.AYSE)
		# The open panel session stays. The link opens no second session.
		self.assertEqual(client.get_cookie("sid").value, sid)
		self.assertEqual(h.session_count(h.AYSE), sessions)

	def test_link_finished_by_another_person_is_refused(self):
		"""Keycloak must link the account of the person who started it. Another subject opens no session."""
		self.serve(FakeIdentitySync(replies()))
		h.make_link(OTHER_SUBJECT, h.MEHMET)
		client = self.login()
		query = location_query(self.start(client, provider="facebook", redirect_to="/account"))
		with h.jwks_patch():
			finished = h.finish_login(client, query, h.id_token(query, h.userinfo(OTHER_SUBJECT, h.MEHMET)))
		self.assertEqual(finished.status_code, 403, finished.data[:300])
		self.assertNotEqual(h.logged_user(client), h.MEHMET)

	def test_guest_gets_403_and_no_call(self):
		fake = self.serve(FakeIdentitySync(replies()))
		response = self.start(h.new_client(), provider="facebook")
		self.assertEqual(response.status_code, 403, response.data[:300])
		self.assertNotIn("Location", response.headers)
		self.assertEqual(fake.calls, [])

	def test_platform_that_is_not_open_is_refused(self):
		self.serve(FakeIdentitySync(replies()))
		client = self.login()
		response = self.start(client, provider="tenant2-sso")
		self.assertEqual(response.status_code, 400, response.data[:300])
		self.assertNotIn("Location", response.headers)

	def test_missing_or_badly_formed_provider_is_refused_without_a_call(self):
		fake = self.serve(FakeIdentitySync(replies()))
		client = self.login()
		for query in ({}, {"provider": ""}, {"provider": "Facebook"}, {"provider": "a:b"}):
			with self.subTest(query=query):
				response = self.start(client, **query)
				self.assertEqual(response.status_code, 400, response.data[:300])
				self.assertNotIn("Location", response.headers)
		self.assertEqual(fake.calls, [])

	def test_unsafe_redirect_is_refused(self):
		self.serve(FakeIdentitySync(replies()))
		client = self.login()
		for target in ("https://evil.example.test/", "//evil.example.test/"):
			with self.subTest(target=target):
				response = self.start(client, provider="facebook", redirect_to=target)
				self.assertEqual(response.status_code, 400, response.data[:300])
				self.assertNotIn("Location", response.headers)

	def test_subject_or_user_parameter_is_refused(self):
		fake = self.serve(FakeIdentitySync(replies()))
		client = self.login()
		for name in ("subject", "user"):
			with self.subTest(name=name):
				response = self.start(client, provider="facebook", **{name: OTHER_SUBJECT})
				self.assertEqual(response.status_code, 400, response.data[:300])
		self.assertEqual(fake.calls, [])

	def test_session_without_a_matching_identity_link_is_refused(self):
		fake = self.serve(FakeIdentitySync(replies()))
		client = self.login()
		frappe.db.set_value("PLT Identity Link", {"user": h.AYSE}, "subject", OTHER_SUBJECT)
		h.refresh()
		response = self.start(client, provider="facebook")
		self.assertEqual(response.status_code, 403, response.data[:300])
		self.assertNotIn("Location", response.headers)
		self.assertEqual(fake.calls, [])

	def test_post_is_refused(self):
		self.serve(FakeIdentitySync(replies()))
		client = self.login()
		response = h.request(
			client.post, START_LINK, json={"provider": "facebook"}, headers=h.csrf_headers(client)
		)
		self.assertEqual(response.status_code, 403)


class TestUnlinkAccount(AccountLinkCase):
	def test_user_removes_the_own_link_and_gets_the_new_list(self):
		fake = self.serve(FakeIdentitySync(replies()))
		client = self.login()
		response = self.unlink(client, {"provider": "google"})
		self.assertEqual(response.status_code, 200, response.data[:300])
		self.assertEqual(response.json["message"], AFTER_UNLINK)
		# The subject comes from the session and its identity link, never from the request.
		self.assertEqual(
			fake.calls,
			[("POST", SERVICE_URL + UNLINK_PATH, {"subject": SUBJECT, "provider": "google"}, BEARER)],
		)
		directives = {part.strip() for part in response.headers.get("Cache-Control", "").split(",")}
		self.assertIn("no-store", directives)

	def test_last_way_to_sign_in_gives_409(self):
		self.serve(FakeIdentitySync(replies(**{UNLINK_PATH: (409, {"error": "last_sign_in_method"})})))
		response = self.unlink(self.login(), {"provider": "facebook"})
		self.assertEqual(response.status_code, 409, response.data[:300])
		self.assertEqual(response.json["exc_type"], "LastSignInMethod")

	def test_platform_outside_the_site_list_gives_400(self):
		self.serve(FakeIdentitySync(replies(**{UNLINK_PATH: (400, {"error": "bad_request"})})))
		response = self.unlink(self.login(), {"provider": "tenant2-sso"})
		self.assertEqual(response.status_code, 400, response.data[:300])
		self.assertEqual(response.json["exc_type"], "InvalidInput")

	def test_member_of_another_tenant_gets_403(self):
		self.serve(FakeIdentitySync(replies(**{UNLINK_PATH: (403, {"error": "forbidden"})})))
		response = self.unlink(self.login(), {"provider": "google"})
		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.json["exc_type"], "LoginReadForbidden")

	def test_reply_is_built_from_an_allow_list(self):
		self.serve(FakeIdentitySync(replies(**{UNLINK_PATH: (200, LEAKY_REPLY)})))
		response = self.unlink(self.login(), {"provider": "google"})
		self.assertEqual(response.status_code, 200, response.data[:300])
		message = response.json["message"]
		self.assertEqual(set(message), {"providers", "local_sign_in_methods"})
		text = json.dumps(response.json)
		for leak in ("config", "clientSecret", "fixture-secret-value", "userName", "credentialData"):
			self.assertNotIn(leak, text)

	def test_guest_gets_403_and_no_call(self):
		fake = self.serve(FakeIdentitySync(replies()))
		response = h.request(h.new_client().post, UNLINK, json={"provider": "google"})
		self.assertEqual(response.status_code, 403, response.data[:300])
		self.assertEqual(fake.calls, [])

	def test_missing_csrf_token_makes_no_call(self):
		fake = self.serve(FakeIdentitySync(replies()))
		response = self.unlink(self.login(), {"provider": "google"}, headers={})
		self.assertNotEqual(response.status_code, 200)
		self.assertEqual(fake.calls, [])

	def test_bad_bodies_make_no_call(self):
		fake = self.serve(FakeIdentitySync(replies()))
		client = self.login()
		for body in (
			{},
			{"provider": ""},
			{"provider": "Google"},
			{"provider": "a/b"},
			{"provider": "google", "subject": OTHER_SUBJECT},
			{"provider": "google", "user": h.MEHMET},
		):
			with self.subTest(body=body):
				response = self.unlink(client, body)
				self.assertEqual(response.status_code, 400, response.data[:300])
				self.assertEqual(response.json["exc_type"], "InvalidInput")
		self.assertEqual(fake.calls, [])

	def test_session_without_a_matching_identity_link_makes_no_call(self):
		fake = self.serve(FakeIdentitySync(replies()))
		client = self.login()
		frappe.db.set_value("PLT Identity Link", {"user": h.AYSE}, "subject", OTHER_SUBJECT)
		h.refresh()
		response = self.unlink(client, {"provider": "google"})
		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.json["exc_type"], "IdentityLinkMissing")
		self.assertEqual(fake.calls, [])

	def test_service_outage_gives_a_plain_503(self):
		self.serve(FakeIdentitySync(replies(**{UNLINK_PATH: (502, {"error": "upstream_failed"})})))
		response = self.unlink(self.login(), {"provider": "google"})
		self.assertEqual(response.status_code, 503, response.data[:300])
		self.assertEqual(response.json["exc_type"], "IdentityServiceUnavailable")
		text = response.data.decode("utf-8")
		for secret in (BEARER, SERVICE_URL, "Traceback"):
			self.assertNotIn(secret, text)

	def test_get_is_refused(self):
		self.serve(FakeIdentitySync(replies()))
		response = h.request(self.login().get, UNLINK, query_string={"provider": "google"})
		self.assertEqual(response.status_code, 403)
