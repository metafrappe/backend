"""GILT: the bootstrap fills the locale fields of the contract (AJA-1767, AJA-1732).

The user setting comes first, then the tenant setting, then en-GB (Decision 44).
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_system_timezone

from platform_core.shell import session_locale
from platform_core.shell.bootstrap import _bootstrap_cache_key, compact_bootstrap, get_bootstrap
from platform_core.shell.cache import bump_permission_version
from platform_core.tests.test_shell_contract import SCHEMA_FILE, matches

LOCALE_FIELDS = {
	"language_tag",
	"language",
	"region",
	"time_zone",
	"transaction_currency",
	"billing_country",
	"measurement_system",
	"selected_market",
	"open_markets",
}


class TestSessionLocale(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.components = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
		self.user = frappe.session.user
		self.keep_user_value("language")
		self.keep_user_value("time_zone")
		self.keep_tenant_language()
		for key in ("market", "measurement_system"):
			self.keep_default(key, self.user)
		for key in ("market", "transaction_currency", "billing_country"):
			self.keep_default(key, "__default")
		bump_permission_version()

	def keep_user_value(self, field):
		previous = frappe.db.get_value("User", self.user, field)
		self.addCleanup(frappe.db.set_value, "User", self.user, field, previous)

	def keep_tenant_language(self):
		previous = frappe.db.get_single_value("System Settings", "language")
		self.addCleanup(frappe.db.set_single_value, "System Settings", "language", previous)

	def keep_default(self, key, parent):
		previous = frappe.db.get_default(key, parent)
		self.addCleanup(self.restore_default, key, parent, previous)
		frappe.db.set_default(key, None, parent)

	@staticmethod
	def restore_default(key, parent, value):
		frappe.db.set_default(key, value, parent)

	def set_languages(self, user_language, tenant_language):
		frappe.db.set_value("User", self.user, "language", user_language)
		frappe.db.set_single_value("System Settings", "language", tenant_language)

	def locale(self):
		bump_permission_version()
		return get_bootstrap(self.user)["locale"]

	def test_empty_user_and_tenant_settings_give_en_gb(self):
		self.set_languages(None, None)
		locale = self.locale()
		self.assertEqual(locale["language_tag"], "en-GB")
		self.assertEqual(locale["language"], "en")
		self.assertEqual(locale["region"], "GB")

	def test_user_setting_comes_before_tenant_setting(self):
		self.set_languages(None, "tr")
		self.assertEqual(self.locale()["language_tag"], "tr")
		self.set_languages("de-DE", "tr")
		self.assertEqual(self.locale()["language_tag"], "de-DE")

	def test_each_locale_value_is_a_separate_field(self):
		# German interface, Turkish billing address and euro prices in the same session.
		self.set_languages("de-DE", None)
		frappe.db.set_value("User", self.user, "time_zone", "Europe/Istanbul")
		frappe.db.set_default("billing_country", "TR")
		frappe.db.set_default("transaction_currency", "EUR")
		payload = get_bootstrap(self.user)
		locale = payload["locale"]
		self.assertEqual(set(locale), LOCALE_FIELDS)
		self.assertEqual(
			locale,
			{
				"language_tag": "de-DE",
				"language": "de",
				"region": "DE",
				"time_zone": "Europe/Istanbul",
				"transaction_currency": "EUR",
				"billing_country": "TR",
				"measurement_system": "metric",
				"selected_market": "TR",
				"open_markets": ["TR"],
			},
		)
		self.assertTrue(matches(locale, self.components["Locale"], self.components), locale)

	def test_invalid_stored_time_zone_falls_back_to_the_site_time_zone(self):
		frappe.db.set_value("User", self.user, "time_zone", "Mars/Olympus_Mons")
		self.assertEqual(self.locale()["time_zone"], get_system_timezone())

	def test_region_selects_the_measurement_system(self):
		self.set_languages("en-GB", None)
		self.assertEqual(self.locale()["measurement_system"], "imperial")
		self.set_languages("tr-TR", None)
		self.assertEqual(self.locale()["measurement_system"], "metric")

	def test_user_choice_of_metric_wins_over_region_gb(self):
		self.set_languages("en-GB", None)
		session_locale.set_measurement_system(self.user, "metric")
		self.assertEqual(frappe.db.get_default("measurement_system", self.user), "metric")
		self.assertEqual(self.locale()["measurement_system"], "metric")

	def test_unknown_measurement_choice_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			session_locale.set_measurement_system(self.user, "us")

	def test_market_that_is_not_open_is_null(self):
		frappe.db.set_default("market", "DE", self.user)
		locale = self.locale()
		self.assertIsNone(locale["selected_market"])
		self.assertEqual(locale["open_markets"], ["TR"])

	def test_cache_key_contains_language_market_and_currency(self):
		with patch.object(session_locale, "OPEN_MARKETS", ("TR", "DE")):
			frappe.db.set_default("market", "TR", self.user)
			turkey = get_bootstrap(self.user)
			frappe.db.set_default("market", "DE", self.user)
			germany = get_bootstrap(self.user)
		# No permission bump between the calls: a shared cache entry would return TR again.
		self.assertEqual(turkey["locale"]["selected_market"], "TR")
		self.assertEqual(germany["locale"]["selected_market"], "DE")
		self.assertEqual(turkey["locale"]["transaction_currency"], "TRY")
		self.assertEqual(germany["locale"]["transaction_currency"], "EUR")
		self.assertNotEqual(turkey["meta_hash"], germany["meta_hash"])

		version, roles = "1", ["System Manager"]
		base = {**turkey["locale"]}
		keys = {
			_bootstrap_cache_key(version, "en", roles, base),
			_bootstrap_cache_key(version, "en", roles, {**base, "language_tag": "de-DE"}),
			_bootstrap_cache_key(version, "en", roles, {**base, "selected_market": "DE"}),
			_bootstrap_cache_key(version, "en", roles, {**base, "transaction_currency": "EUR"}),
		}
		self.assertEqual(len(keys), 4)

	def test_compact_bootstrap_keeps_the_locale(self):
		payload = get_bootstrap(self.user)
		self.assertEqual(compact_bootstrap(payload)["locale"], payload["locale"])
