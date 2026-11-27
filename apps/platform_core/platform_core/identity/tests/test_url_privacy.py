"""G-132 address privacy at the identity URL boundary, without a site or database.

These tests call the real URL builders. Cache, session, settings and token verification
are test doubles. They do not prove HTTP authorization or token verification.
The caller supplies the final post-login path. Personal-data-free record aliases and
the UI that creates those paths remain separate work, as recorded in AJA-81.
"""

import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, unquote, urlsplit

from platform_core.identity import helpers, sign_in, sign_out
from platform_core.identity.exceptions import InvalidRedirect

EMAIL = "privacy@example.test"
PHONE = "+905550000000"
IDENTITY_NUMBER = "10000000000"  # Invalid checksum: made-up data only.
TAX_NUMBER = "0000000000"
OPAQUE_JWT = "synthetic-jwt"  # Not a credential: the verifier is patched in tests.
PERSONAL_VALUES = (EMAIL, PHONE, IDENTITY_NUMBER, TAX_NUMBER)
PRIVATE_TARGET = f"/app/user/{EMAIL}?phone=%2B905550000000&identity={IDENTITY_NUMBER}&tax={TAX_NUMBER}"
AUTH_PARAMETERS = {
	"client_id",
	"redirect_uri",
	"response_type",
	"scope",
	"state",
	"nonce",
	"code_challenge",
	"code_challenge_method",
}


def refuse(message, exception):
	raise exception(message)


class TestIdentityUrlPrivacy(TestCase):
	def setUp(self):
		self.settings = SimpleNamespace(
			public_url="https://identity.example.test",
			realm="platform",
			client_id="site-tenant1",
			panel_url="https://tenant.example.test/panel",
			brand_name="Sample Brand",
			issuer="https://identity.example.test/realms/platform",
			jwks_url="https://identity.example.test/realms/platform/protocol/openid-connect/certs",
		)
		self.saved = {}
		self.cookies = {}
		request = SimpleNamespace(content_length=0, scheme="https", cookies=self.cookies)
		self.frappe = SimpleNamespace(
			local=SimpleNamespace(request=request, cookie_manager=Mock(), login_manager=Mock()),
			request=request,
			cache=Mock(
				make_key=lambda key: key,
				set=lambda key, value, **_options: self.saved.update({key: value}),
				getdel=lambda key: self.saved.pop(key, None),
			),
			session=SimpleNamespace(
				user=EMAIL,
				sid="synthetic-session",
				data={
					"email": EMAIL,
					"phone_number": PHONE,
					"identity_number": IDENTITY_NUMBER,
					"tax_number": TAX_NUMBER,
					"keycloak_sid": "synthetic-keycloak-session",
				},
			),
			throw=refuse,
		)
		for target, name, replacement in (
			(sign_in, "frappe", self.frappe),
			(sign_out, "frappe", self.frappe),
			(sign_in, "_", lambda value, **_options: value),
			(sign_in.site_settings, "get", lambda: self.settings),
			(sign_in, "get_url", lambda path: "https://tenant.example.test" + path),
		):
			self.enterContext(patch.object(target, name, replacement))

	def assert_private_address(self, address):
		decoded = unquote(unquote(address))
		for value in PERSONAL_VALUES:
			self.assertNotIn(value, decoded)
		self.assertNotIn("@", decoded)
		self.assertNotRegex(decoded, r"(?<![A-Za-z0-9])\+?\d[\d -]{8,}\d(?![A-Za-z0-9])")

	def assert_authorization_address(self, address, *, forced=False):
		query = parse_qs(urlsplit(address).query, keep_blank_values=True)
		self.assertEqual(set(query), AUTH_PARAMETERS | ({"prompt"} if forced else set()))
		self.assertTrue(all(len(values) == 1 for values in query.values()))
		self.assertEqual(
			query["redirect_uri"],
			["https://tenant.example.test/api/method/platform_core.api.auth.keycloak_callback"],
		)
		self.assertEqual(query["scope"], ["openid"])
		if forced:
			self.assertEqual(query["prompt"], ["login"])
		self.assert_private_address(address)
		return query

	def test_personal_return_path_stays_in_server_state(self):
		self.assertTrue(helpers.is_safe_redirect(PRIVATE_TARGET))
		for forced in (False, True):
			with self.subTest(forced=forced):
				url = sign_in.build_login_url(PRIVATE_TARGET, force_login=forced)["login_url"]
				query = self.assert_authorization_address(url, forced=forced)
				record = sign_in._pop_state(query["state"][0])
				self.assertEqual(record["redirect_to"], PRIVATE_TARGET)
				self.assertEqual(record["force_login"], forced)

	def test_callback_forced_reauthentication_does_not_disclose_claims_or_return_path(self):
		url = sign_in.build_login_url(PRIVATE_TARGET)["login_url"]
		state = parse_qs(urlsplit(url).query)["state"][0]
		cookie = self.frappe.local.cookie_manager.set_cookie.call_args.args
		self.cookies[cookie[0]] = cookie[1]
		claims = dict(self.frappe.session.data, sub="synthetic-subject", sid="synthetic-keycloak-session")
		with (
			patch.object(sign_in, "exchange_code", return_value={"id_token": OPAQUE_JWT}),
			patch("oidc_verify.verify_id_token", return_value=claims),
			patch.object(sign_in.jwks, "jwks_cache", return_value=object()),
			patch.object(sign_in, "resolve_user", return_value=EMAIL),
			patch.object(sign_in.session_policy, "check_fresh_authentication", return_value="force"),
		):
			address = sign_in.complete_callback("synthetic-code", state)
		query = self.assert_authorization_address(address, forced=True)
		self.assertNotEqual(query["state"], [state])
		self.assertEqual(len(self.saved), 1)
		record = json.loads(next(iter(self.saved.values())))
		self.assertEqual(record["redirect_to"], PRIVATE_TARGET)
		self.assertTrue(record["force_login"])
		self.frappe.local.login_manager.login_as.assert_not_called()

	def test_logout_address_has_only_client_and_configured_panel(self):
		address = sign_out.logout_current_session()["logout_url"]
		query = parse_qs(urlsplit(address).query, keep_blank_values=True)
		self.assertEqual(
			query,
			{
				"client_id": ["site-tenant1"],
				"post_logout_redirect_uri": [self.settings.panel_url],
			},
		)
		self.assert_private_address(address)
		self.frappe.local.login_manager.logout.assert_called_once_with()

	def test_invalid_return_path_is_not_echoed_in_the_error(self):
		for target in (f"https://external.example.test/{EMAIL}", f"//{PHONE}/", f"/{IDENTITY_NUMBER}\n"):
			with self.subTest(target=target):
				with self.assertRaises(InvalidRedirect) as caught:
					sign_in.build_login_url(target)
				self.assertEqual(
					str(caught.exception), "Redirect target must be a relative path on this site."
				)
				for value in PERSONAL_VALUES:
					self.assertNotIn(value, str(caught.exception))
		self.assertEqual(self.saved, {})
		self.frappe.local.cookie_manager.set_cookie.assert_not_called()
