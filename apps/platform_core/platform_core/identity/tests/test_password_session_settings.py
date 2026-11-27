"""G-43: Frappe password and session settings on install and migrate (AJA-2278).

Expected values come from the G-43 requirement:
- password policy on, minimum score 3,
- 5 failed sign-ins in a row, then a 300 second lock,
- sign-out on password reset, reset link valid for 900 seconds, at most 3 reset mails,
- document share keys valid for 7 days,
- a cookie session ends after 1 hour idle and after 24 hours in total.
"""

from datetime import timedelta

import frappe
from frappe.tests.test_api import FrappeAPITestCase
from frappe.utils import get_datetime, now_datetime

from platform_core.identity import provider_setup, session_policy
from platform_core.identity.tests import helpers as h

EXPECTED = {
	"session_expiry": "01:00",
	"enable_password_policy": 1,
	"minimum_password_score": "3",
	"allow_consecutive_login_attempts": 5,
	"allow_login_after_fail": 300,
	"logout_on_password_reset": 1,
	"reset_password_link_expiry_duration": 900,
	"password_reset_limit": 3,
	"document_share_key_expiry": 7,
}
# Values that differ from G-43. Frappe's own defaults are used where they differ.
WRONG = {
	"session_expiry": "170:00",
	"enable_password_policy": 0,
	"minimum_password_score": "2",
	"allow_consecutive_login_attempts": 10,
	"allow_login_after_fail": 60,
	"logout_on_password_reset": 0,
	"reset_password_link_expiry_duration": 1200,
	"password_reset_limit": 10,
	"document_share_key_expiry": 30,
}


def _current() -> dict:
	return {field: frappe.db.get_single_value("System Settings", field) for field in EXPECTED}


def _normalized(values: dict) -> dict:
	return {field: type(EXPECTED[field])(value) for field, value in values.items()}


class TestPasswordSessionSettings(FrappeAPITestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		previous = _current()
		cls.addClassCleanup(frappe.db.set_single_value, "System Settings", previous)

	def setUp(self):
		super().setUp()
		# Frappe adds `modified` and `modified_by` to the dict it gets, so pass a copy.
		frappe.db.set_single_value("System Settings", dict(WRONG))
		h.refresh()

	def test_policy_lists_every_g43_setting(self):
		self.assertEqual(session_policy.SYSTEM_SETTINGS, EXPECTED)

	def test_install_and_migrate_run_the_policy(self):
		self.assertIn("platform_core.identity.session_policy.apply", frappe.get_hooks("after_install"))
		self.assertIn("platform_core.identity.session_policy.apply", frappe.get_hooks("after_migrate"))

	def test_apply_writes_each_setting(self):
		session_policy.apply()
		h.refresh()
		current = _current()
		for field, value in EXPECTED.items():
			with self.subTest(field=field):
				self.assertEqual(type(value)(current[field]), value)

	def test_second_apply_gives_the_same_result(self):
		session_policy.apply()
		h.refresh()
		first = _normalized(_current())
		session_policy.apply()
		h.refresh()
		self.assertEqual(_normalized(_current()), first)
		self.assertEqual(first, EXPECTED)

	def test_apply_restores_a_single_changed_setting(self):
		session_policy.apply()
		for field, wrong in WRONG.items():
			with self.subTest(field=field):
				frappe.db.set_single_value("System Settings", field, wrong)
				session_policy.apply()
				h.refresh()
				value = frappe.db.get_single_value("System Settings", field)
				self.assertEqual(type(EXPECTED[field])(value), EXPECTED[field])

	def test_frappe_reads_the_written_values(self):
		session_policy.apply()
		h.refresh()
		self.assertEqual(frappe.sessions.get_expiry_in_seconds(), session_policy.IDLE_SECONDS)
		settings = frappe.get_cached_doc("System Settings")
		self.assertEqual(settings.minimum_password_score, "3")
		self.assertEqual(settings.allow_login_after_fail, 300)


class TestSessionMaxLifespan(FrappeAPITestCase):
	"""A cookie session ends 24 hours after sign-in, even with recent real activity."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = h.SiteSettings()
		settings.__enter__()
		cls.addClassCleanup(settings.__exit__, None, None, None)
		provider_setup.ensure_social_login_key()
		h.ensure_user(h.AYSE)
		h.refresh()
		verification = h.jwks_patch()
		verification.start()
		cls.addClassCleanup(verification.stop)

	def setUp(self):
		super().setUp()
		h.clear_links()
		h.reset_rate_limits()
		self.addCleanup(h.clear_links)
		self.client = h.new_client()
		response = h.login_with_keycloak(self.client, h.userinfo("sub-ayse", h.AYSE))
		self.assertEqual(response.status_code, 302)
		self.sid = self.client.get_cookie("sid").value

	def request_at_session_age(self, seconds):
		data = frappe.cache.hget("session", self.sid)
		data["data"]["creation"] = str(get_datetime(now_datetime()) - timedelta(seconds=seconds))
		frappe.cache.hset("session", self.sid, data)
		# Real activity just now: only the total lifespan can end the session.
		session_policy.mark_activity(self.sid, h.AYSE)
		return h.request(self.client.get, "/api/method/frappe.auth.get_logged_user")

	def test_policy_lifespan_is_24_hours(self):
		self.assertEqual(session_policy.MAX_LIFESPAN_SECONDS, 24 * 3600)

	def test_session_younger_than_24_hours_stays(self):
		response = self.request_at_session_age(24 * 3600 - 60)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json["message"], h.AYSE)
		h.refresh()
		self.assertEqual(frappe.db.count("Sessions", {"sid": self.sid}), 1)

	def test_session_older_than_24_hours_ends_despite_activity(self):
		response = self.request_at_session_age(24 * 3600)
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.json["exc_type"], "SessionExpired")
		h.refresh()
		self.assertEqual(frappe.db.count("Sessions", {"sid": self.sid}), 0)
