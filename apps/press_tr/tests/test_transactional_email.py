"""G-17's seven mail kinds must preserve their facts and use the Turkish brand set."""

import csv
import sys
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from press_tr.outbound_email.messages import prepare


class TransactionalEmailTest(unittest.TestCase):
	def setUp(self):
		with (APP_ROOT / "press_tr/translations/tr.csv").open(newline="") as source:
			self.translations = {(row[0], row[2]): row[1] for row in csv.reader(source)}
		self.env = Environment(loader=FileSystemLoader(APP_ROOT / "press_tr"), undefined=StrictUndefined)
		self.env.globals["_"] = self.translate

	def translate(self, message, **kwargs):
		return self.translations[(message, "press_tr.email")]

	def render(self, template, args):
		prepared = prepare(template, args, translate=self.translate)
		body = self.env.get_template("templates/emails/" + prepared["template"] + ".html").render(prepared["args"])
		return prepared, body

	def test_each_required_event_selects_its_own_turkish_template(self):
		cases = [
			("ptr_invoice", {"invoice_name": "INV-TEST", "amount": "125,00 TRY", "billing_link": "https://panel.example.test/billing"}, "Faturanız hazır", "INV-TEST"),
			("payment_failed", {"amount": "125,00 TRY", "last_4": "1234", "account_update_link": "https://panel.example.test/billing", "payment_link": "https://panel.example.test/pay", "sites": ["site.example.test"]}, "Ödemeniz alınamadı", "125,00 TRY"),
			("suspended_sites", {"sites": ["site.example.test"]}, "Siteleriniz durduruldu", "site.example.test"),
			("notify_before_site_archival", {"site_name": "site.example.test", "site_archive_notification_days": 7}, "Siteniz arşivlenecek", "7"),
			("product_trial_email", {"message": "Deneme süreniz bitti.", "title": "Example"}, "Deneme süreniz bitti", "Deneme süreniz bitti"),
			("payment_method_invalid", {"amount": "125,00 TRY", "billing_link": "https://panel.example.test/billing"}, "Kart bilginizi güncelleyin", "125,00 TRY"),
			("invite_team_member", {"invited_by": "Example Team", "link": "https://panel.example.test/invite"}, "Takıma davet edildiniz", "Example Team"),
		]
		selected = set()
		for name, args, expected_subject, fact in cases:
			with self.subTest(event=name):
				prepared, body = self.render(name, args)
				self.assertEqual(prepared["subject"], expected_subject)
				self.assertIn("Atonota", body)
				self.assertIn(fact, body)
				self.assertNotIn("Frappe Cloud", body)
				selected.add(prepared["template"])
		self.assertEqual(len(selected), 7)

	def test_press_subjects_are_replaced_with_the_turkish_subject_of_their_kind(self):
		from press_tr.outbound_email.messages import localized_subject
		# Subjects written in Press v0.154.1 code (O-69). Press passes them as plain strings, not through _().
		cases = [
			("Your sites have been suspended on Frappe Cloud", "Siteleriniz durduruldu"),
			("Alert: Your site site.example.test will be archived in 7 days", "Siteniz arşivlenecek"),
			("Invoice Payment Failed for Frappe Cloud Subscription", "Ödemeniz alınamadı"),
			("Card on Frappe Cloud could not be charged", "Kart bilginizi güncelleyin"),
			("You are invited by Example Team to join Frappe Cloud", "Takıma davet edildiniz"),
			("Your Example site is expired", "Deneme süreniz bitti"),
		]
		for original, expected in cases:
			with self.subTest(subject=original):
				self.assertEqual(localized_subject(original, translate=self.translate), expected)

	def test_other_subjects_are_left_unchanged(self):
		from press_tr.outbound_email.messages import localized_subject
		for subject in ("Your login code", "Alert: Your site will be archived soon", "", None):
			with self.subTest(subject=subject):
				self.assertIsNone(localized_subject(subject, translate=self.translate))

	def test_unknown_template_is_not_misclassified(self):
		self.assertIsNone(prepare("custom_tenant_notice", {}, translate=self.translate))

	def test_untrusted_names_are_escaped_without_losing_data(self):
		_, body = self.render("invite_team_member", {"invited_by": "<img src=x onerror=alert(1)>", "link": "https://panel.example.test/invite"})
		self.assertIn("&lt;img", body)
		self.assertNotIn("<img", body)

	def test_missing_required_data_fails_instead_of_sending_empty_email(self):
		for template in ("ptr_invoice", "payment_failed", "notify_before_site_archival", "invite_team_member"):
			with self.subTest(template=template), self.assertRaises(ValueError):
				prepare(template, {}, translate=self.translate)

	def test_unsafe_action_url_is_rejected(self):
		for url in ("javascript:alert(1)", "http://panel.example.test/invite", "https://user:password@example.test", "//example.test"):
			with self.subTest(url=url), self.assertRaises(ValueError):
				prepare("invite_team_member", {"invited_by": "Team", "link": url}, translate=self.translate)

	def test_retry_and_operational_settings_have_no_secret_or_real_domain(self):
		from press_tr.outbound_email.configuration import release_group_defaults
		defaults = release_group_defaults()
		self.assertEqual(defaults["mail_port"], 587)
		self.assertEqual(defaults["use_tls"], 1)
		self.assertEqual(defaults["email_retry_limit"], 3)
		self.assertEqual(defaults["always_use_account_email_id_as_sender"], 1)
		self.assertFalse({"mail_server", "mail_password", "auto_email_id", "mail_login"} & defaults.keys())


if __name__ == "__main__":
	unittest.main()
