# ruff: noqa: RUF001, RUF002
# Turkish month names and texts use the dotless letter on purpose.
"""Notification email in the recipient's language (AJA-1783, parent AJA-1733).

The rule is in contracts/locale-and-notifications.md, section 3 (AJA-1776):

1. The recipient's own language (`User.language`).
2. The tenant language (`System Settings.language`) when the recipient has none.
3. en-GB when both are empty (Decision 44).

A value counts only when its language is open. For example `de` is skipped.
The sender's language never chooses the email language.

One event sends one email. The caller names the event with `event_key`. The event key and the
recipient give a fixed Message-Id. When the Email Queue already holds that Message-Id, nothing is sent.
"""

import hashlib
from datetime import date

import frappe

# Copy of contracts/locales.json. The app is installed without that folder.
# contracts/tests/test_notification_locale_copy.py fails when the copy differs.
OPEN_LANGUAGES = ("en", "tr")
DEFAULT_LOCALE = "en-GB"
LOCALE_ORDER = ("recipient", "tenant", "default")

MONTHS = {
	"en": (
		"January", "February", "March", "April", "May", "June",
		"July", "August", "September", "October", "November", "December",
	),
	"tr": (
		"Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
		"Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
	),
}  # fmt: skip
# Regions that write the month before the day. Every other region writes the day first.
MONTH_FIRST_REGIONS = frozenset({"US"})
TRANSLATION_CONTEXT = "platform_core.notification"

# English source texts. The Turkish texts are in translations/tr.csv.
TASK_ASSIGNED = {
	"subject": "New task: {title}",
	"message": "You have a new task: {title}. Due date: {due_date}.",
}


def normalize_locale(value) -> str | None:
	"""Return the locale in the form tr or en-GB when its language is open, else None."""
	if not isinstance(value, str) or not value.strip():
		return None
	language, _, region = value.strip().replace("_", "-").partition("-")
	language = language.lower()
	if language not in OPEN_LANGUAGES:
		return None
	return f"{language}-{region.upper()}" if region else language


def choose_locale(recipient_language, tenant_language) -> str:
	"""Recipient language, then tenant language, then en-GB. Closed and empty values are skipped."""
	return normalize_locale(recipient_language) or normalize_locale(tenant_language) or DEFAULT_LOCALE


def format_date(value: date, locale: str) -> str:
	"""Write a calendar day the way the locale's language writes it. Example: 27 Kasım 2026."""
	language, _, region = locale.partition("-")
	month = MONTHS.get(language, MONTHS["en"])[value.month - 1]
	if region.upper() in MONTH_FIRST_REGIONS:
		return f"{month} {value.day}, {value.year}"
	return f"{value.day} {month} {value.year}"


def recipient_locale(recipient: str) -> str:
	"""The email language of a user, chosen by the contract order."""
	return choose_locale(
		frappe.db.get_value("User", recipient, "language"),
		frappe.db.get_single_value("System Settings", "language"),
	)


def message_id(event_key: str, recipient: str) -> str:
	"""Fixed Message-Id of one event for one recipient, without angle brackets.

	frappe.sendmail adds the brackets to the header. The Email Queue keeps the value without them.
	"""
	digest = hashlib.sha256(f"{event_key}\n{recipient}".encode()).hexdigest()[:32]
	return f"notification-{digest}@{frappe.local.site}"


def send_notification(*, recipient: str, event_key: str, notification: dict, args: dict) -> bool:
	"""Queue the notification email in the recipient's language. Return False when it was already sent."""
	if not event_key or not event_key.strip():
		frappe.throw(frappe._("An event key is required.", context=TRANSLATION_CONTEXT))
	email_id = message_id(event_key.strip(), recipient)
	if frappe.db.exists("Email Queue", {"message_id": email_id}):
		return False
	locale = recipient_locale(recipient)
	values = {
		key: format_date(value, locale) if isinstance(value, date) else value for key, value in args.items()
	}
	subject = frappe._(notification["subject"], lang=locale, context=TRANSLATION_CONTEXT)
	message = frappe._(notification["message"], lang=locale, context=TRANSLATION_CONTEXT)
	frappe.sendmail(
		recipients=[recipient],
		subject=subject.format(**values),
		message=frappe.utils.escape_html(message.format(**values)),
		message_id=email_id,
		email_headers={"Content-Language": locale},
	)
	return True
