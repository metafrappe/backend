# ruff: noqa: RUF001, RUF002
# Turkish month names and texts use the dotless letter on purpose.
"""A notification email goes out in the recipient's language (AJA-1783, parent AJA-1733).

Expected behaviour comes from the language and notification contract (AJA-1776,
contracts/locale-and-notifications.md, section 3) and from the task text:

1. A Turkish user gets a Turkish email. The date is written the Turkish way: "27 Kasım 2026".
2. An English administrator opens a task for a Turkish user. The email is still Turkish.
3. The recipient has no language: the tenant language is used. The tenant has none either: en-GB.
   A language that is not open (for example de) counts as empty.
4. One event sends one email. Sending the same event again sends nothing.

The test runs on a separate test site through `bin/test`.
"""

from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from platform_core import notification_email
from platform_core.notification_email import TASK_ASSIGNED, choose_locale, format_date, send_notification

TURKISH_USER = "aja1783-tr@example.test"
ENGLISH_ADMIN = "aja1783-admin-en@example.test"
NO_LANGUAGE_USER = "aja1783-none@example.test"
GERMAN_USER = "aja1783-de@example.test"
DUE = date(2026, 11, 27)
# A long company title must reach the email whole. It is not cut.
LONG_TITLE = "Anadolu Uzun Unvanlı Gıda Tarım Hayvancılık İnşaat Sanayi ve Ticaret Anonim Şirketi"


def _user(email: str, language: str | None, roles=()):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@", 1)[0],
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
	# The language field is a link to Language. db.set_value writes even a closed code such as de.
	frappe.db.set_value("User", email, "language", language or "")


class NotificationEmailTest(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.lang = frappe.local.lang
		self.tenant_language = frappe.db.get_single_value("System Settings", "language")
		_user(TURKISH_USER, "tr")
		_user(ENGLISH_ADMIN, "en", roles=("System Manager",))
		_user(NO_LANGUAGE_USER, None)
		_user(GERMAN_USER, "de")
		frappe.db.delete("Email Queue", {"message_id": ("like", "notification-%")})

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.lang = self.lang
		frappe.db.set_single_value("System Settings", "language", self.tenant_language)

	def _send(self, recipient: str, event_key: str):
		"""Send the task notification and return the keyword arguments given to frappe.sendmail."""
		with patch.object(frappe, "sendmail", wraps=frappe.sendmail) as sendmail:
			send_notification(
				recipient=recipient,
				event_key=event_key,
				notification=TASK_ASSIGNED,
				args={"title": LONG_TITLE, "due_date": DUE},
			)
		return sendmail

	def _set_tenant_language(self, language: str | None):
		frappe.db.set_single_value("System Settings", "language", language or "")

	# Test 1 in the task.
	def test_turkish_user_gets_turkish_email_with_turkish_date(self):
		self._set_tenant_language("en")
		sendmail = self._send(TURKISH_USER, "aja1783-test-1")
		sendmail.assert_called_once()
		email = sendmail.call_args.kwargs
		self.assertEqual(email["recipients"], [TURKISH_USER])
		self.assertEqual(email["email_headers"]["Content-Language"], "tr")
		self.assertEqual(email["subject"], f"Yeni iş: {LONG_TITLE}")
		self.assertIn("27 Kasım 2026", email["message"])
		self.assertIn(LONG_TITLE, email["message"])
		self.assertNotIn("November", email["message"])
		self.assertNotIn("New task", email["subject"])

	# Test 2 in the task.
	def test_english_admin_opens_task_and_turkish_user_still_gets_turkish(self):
		self._set_tenant_language("en")
		frappe.set_user(ENGLISH_ADMIN)
		frappe.local.lang = "en"
		sendmail = self._send(TURKISH_USER, "aja1783-test-2")
		email = sendmail.call_args.kwargs
		self.assertEqual(email["email_headers"]["Content-Language"], "tr")
		self.assertTrue(email["subject"].startswith("Yeni iş: "))
		self.assertIn("27 Kasım 2026", email["message"])
		# The sender's language stays as it was.
		self.assertEqual(frappe.local.lang, "en")

	# Test 3 in the task, first half.
	def test_recipient_without_language_gets_tenant_language(self):
		self._set_tenant_language("tr")
		email = self._send(NO_LANGUAGE_USER, "aja1783-test-3a").call_args.kwargs
		self.assertEqual(email["email_headers"]["Content-Language"], "tr")
		self.assertIn("27 Kasım 2026", email["message"])

	# Test 3 in the task, second half.
	def test_recipient_and_tenant_without_language_get_en_gb(self):
		self._set_tenant_language(None)
		email = self._send(NO_LANGUAGE_USER, "aja1783-test-3b").call_args.kwargs
		self.assertEqual(email["email_headers"]["Content-Language"], "en-GB")
		self.assertEqual(email["subject"], f"New task: {LONG_TITLE}")
		self.assertIn("27 November 2026", email["message"])

	def test_language_that_is_not_open_counts_as_empty(self):
		self._set_tenant_language("tr")
		email = self._send(GERMAN_USER, "aja1783-test-closed").call_args.kwargs
		self.assertEqual(email["email_headers"]["Content-Language"], "tr")

	def test_same_event_sends_one_email(self):
		self._set_tenant_language("en")
		first = self._send(TURKISH_USER, "aja1783-test-once")
		second = self._send(TURKISH_USER, "aja1783-test-once")
		first.assert_called_once()
		second.assert_not_called()
		message_id = first.call_args.kwargs["message_id"]
		self.assertEqual(frappe.db.count("Email Queue", {"message_id": message_id}), 1)

	def test_same_event_for_two_recipients_sends_two_emails(self):
		self._set_tenant_language("en")
		self._send(TURKISH_USER, "aja1783-test-two").assert_called_once()
		self._send(NO_LANGUAGE_USER, "aja1783-test-two").assert_called_once()


class ChooseLocaleTest(IntegrationTestCase):
	def test_order_is_recipient_then_tenant_then_default(self):
		cases = [
			(("tr", "en"), "tr"),
			(("en", "tr"), "en"),
			((None, "tr"), "tr"),
			(("", ""), "en-GB"),
			((None, None), "en-GB"),
			(("de", "tr"), "tr"),
			(("de", "fr"), "en-GB"),
			(("tr-TR", None), "tr-TR"),
			(("en-gb", None), "en-GB"),
			(("  ", "tr"), "tr"),
		]
		for (recipient, tenant), expected in cases:
			with self.subTest(recipient=recipient, tenant=tenant):
				self.assertEqual(choose_locale(recipient, tenant), expected)

	def test_open_languages_and_default_match_the_contract(self):
		self.assertEqual(notification_email.OPEN_LANGUAGES, ("en", "tr"))
		self.assertEqual(notification_email.DEFAULT_LOCALE, "en-GB")


class FormatDateTest(IntegrationTestCase):
	def test_date_uses_the_language_of_the_locale(self):
		cases = [
			("tr", "27 Kasım 2026"),
			("tr-TR", "27 Kasım 2026"),
			("en-GB", "27 November 2026"),
			("en", "27 November 2026"),
			("en-US", "November 27, 2026"),
		]
		for locale, expected in cases:
			with self.subTest(locale=locale):
				self.assertEqual(format_date(DUE, locale), expected)

	def test_every_turkish_month_name(self):
		months = [
			"Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
			"Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
		]  # fmt: skip
		for number, name in enumerate(months, start=1):
			with self.subTest(month=number):
				self.assertEqual(format_date(date(2026, number, 1), "tr"), f"1 {name} 2026")
