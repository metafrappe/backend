"""A site administrator signs in only with a strong key (G-163, item 1, Frappe side).

Expected behaviour comes from the G-163 technical design (AJA-403) and docs/contracts.md (D-1):
- the callback reads the `acr` claim of the verified ID token,
- a user with the System Manager role must bring `acr=admin` (passkey or hardware key at Keycloak),
- otherwise no session opens and the sign-in restarts with `acr_values=admin`,
- a restarted attempt that still does not bring `acr=admin` is refused,
- `acr` and `auth_time` are written into the Frappe session record for the step-up check (item 2).
"""

import time
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.tests.test_api import FrappeAPITestCase

from platform_core.identity import provider_setup
from platform_core.identity.tests import helpers as h

ADMIN = "yonetici.ornek@example.test"


def _query(location: str) -> dict:
	return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


class TestStrongAuthentication(FrappeAPITestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.settings = h.SiteSettings().__enter__()
		cls.addClassCleanup(cls.settings.__exit__, None, None, None)
		provider_setup.ensure_social_login_key()
		h.ensure_user(h.AYSE)
		h.ensure_user(ADMIN, user_type="System User", roles=["System Manager"])
		h.refresh()
		cls.patcher = h.jwks_patch()
		cls.patcher.start()
		cls.addClassCleanup(cls.patcher.stop)

	@classmethod
	def tearDownClass(cls):
		h.clear_links(ADMIN)
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		h.clear_links(ADMIN)
		self.client = h.new_client()

	def _session_data(self, user: str) -> dict:
		h.refresh()
		sessions = frappe.qb.DocType("Sessions")
		rows = frappe.qb.from_(sessions).select(sessions.sessiondata).where(sessions.user == user).run()
		self.assertEqual(len(rows), 1, rows)
		return frappe.parse_json(rows[0][0] or "{}")

	def test_system_manager_with_employee_acr_gets_no_session_and_restarts_with_admin(self):
		_started, query = h.start_login(self.client, "/panel")
		response = h.finish_login(
			self.client, query, h.id_token(query, h.userinfo("sub-admin", ADMIN), acr="employee")
		)
		self.assertEqual(response.status_code, 302, response.data[:300])
		location = response.headers["Location"]
		self.assertTrue(
			location.startswith(
				"http://identity.localhost:8660/realms/platform/protocol/openid-connect/auth?"
			),
			location,
		)
		self.assertEqual(_query(location).get("acr_values"), "admin")
		self.assertEqual(h.session_count(ADMIN), 0)
		self.assertEqual(h.logged_user(self.client), "Guest")

	def test_restarted_attempt_without_admin_acr_is_refused(self):
		_started, query = h.start_login(self.client, "/panel")
		first = h.finish_login(
			self.client, query, h.id_token(query, h.userinfo("sub-admin", ADMIN), acr="employee")
		)
		restart = _query(first.headers["Location"])
		second = h.finish_login(
			self.client, restart, h.id_token(restart, h.userinfo("sub-admin", ADMIN), acr="employee")
		)
		self.assertEqual(second.status_code, 403, second.data[:300])
		self.assertEqual(h.session_count(ADMIN), 0)
		self.assertEqual(h.logged_user(self.client), "Guest")

	def test_system_manager_without_acr_claim_is_not_signed_in(self):
		_started, query = h.start_login(self.client)
		response = h.finish_login(self.client, query, h.id_token(query, h.userinfo("sub-admin", ADMIN)))
		self.assertEqual(response.status_code, 302)
		self.assertEqual(_query(response.headers["Location"]).get("acr_values"), "admin")
		self.assertEqual(h.session_count(ADMIN), 0)

	def test_system_manager_with_admin_acr_signs_in_and_session_keeps_acr_and_auth_time(self):
		auth_time = int(time.time())
		_started, query = h.start_login(self.client, "/panel")
		response = h.finish_login(
			self.client,
			query,
			h.id_token(query, h.userinfo("sub-admin", ADMIN), acr="admin", auth_time=auth_time),
		)
		self.assertEqual(response.status_code, 302, response.data[:300])
		self.assertTrue(response.headers["Location"].endswith("/panel"))
		self.assertEqual(h.logged_user(self.client), ADMIN)
		data = self._session_data(ADMIN)
		self.assertEqual(data.get("keycloak_acr"), "admin")
		self.assertEqual(data.get("keycloak_auth_time"), auth_time)

	def test_employee_with_employee_acr_signs_in_and_session_keeps_acr(self):
		auth_time = int(time.time())
		_started, query = h.start_login(self.client)
		response = h.finish_login(
			self.client,
			query,
			h.id_token(query, h.userinfo("sub-ayse", h.AYSE), acr="employee", auth_time=auth_time),
		)
		self.assertEqual(response.status_code, 302, response.data[:300])
		self.assertEqual(h.logged_user(self.client), h.AYSE)
		data = self._session_data(h.AYSE)
		self.assertEqual(data.get("keycloak_acr"), "employee")
		self.assertEqual(data.get("keycloak_auth_time"), auth_time)
