"""G-97 part 1 (AJA-2551): Tenant Settings single DocType controller.

Exposes only the allow-listed regional, format and session fields from System Settings
to the Tenant Admin role, plus read-only outgoing mail domain and account identifiers.
"""

import re
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.core.doctype.system_settings.system_settings import clear_system_settings_cache
from frappe.model.document import Document
from frappe.translate import set_default_language

from platform_core.shell.cache import invalidate_permissions

SYNCED_FIELDS = (
	"language",
	"time_zone",
	"date_format",
	"time_format",
	"number_format",
	"session_expiry",
)
ALLOWED_LANGUAGES = frozenset({"tr", "en-GB", "en"})
ALLOWED_TIME_ZONES = frozenset(
	{
		"Europe/Istanbul",
		"Europe/London",
		"UTC",
		"Europe/Berlin",
		"Europe/Paris",
		"Europe/Amsterdam",
		"America/New_York",
		"Asia/Dubai",
	}
)
ALLOWED_DATE_FORMATS = frozenset(
	{"dd.mm.yyyy", "dd/mm/yyyy", "dd-mm-yyyy", "yyyy-mm-dd", "mm/dd/yyyy", "mm-dd-yyyy"}
)
ALLOWED_TIME_FORMATS = frozenset({"HH:mm", "HH:mm:ss"})
ALLOWED_NUMBER_FORMATS = frozenset(
	{
		"#.###,##",
		"#,###.##",
		"# ###.##",
		"# ###,##",
		"#'###.##",
		"#, ###.##",
		"#,##,###.##",
		"#,###.###",
		"#.###",
		"#,###",
	}
)
SESSION_EXPIRY_PATTERN = re.compile(r"\d{1,3}:\d{2}")
MAX_SESSION_EXPIRY_MINUTES = 170 * 60


def read_only_email_values() -> tuple[str, str]:
	"""Read only the public outgoing mail domain and sender address, never credentials."""
	# System email identifiers shown read-only to the tenant admin (exception to G-3).
	account = frappe.db.get_value(
		"Email Account",
		{"default_outgoing": 1, "enable_outgoing": 1},
		["email_id", "domain"],
		as_dict=True,
	) or frappe.db.get_value(
		"Email Account",
		{"enable_outgoing": 1},
		["email_id", "domain"],
		as_dict=True,
	)
	email_account = (account.get("email_id") or "") if account else ""
	domain_ref = (account.get("domain") or "") if account else ""
	if domain_ref:
		email_domain = frappe.db.get_value("Email Domain", domain_ref, "domain_name") or domain_ref
	else:
		email_domain = frappe.db.get_value("Email Domain", {}, "domain_name") or ""
	return str(email_domain), str(email_account)


def validate_session_expiry(value: object) -> None:
	if not isinstance(value, str) or not SESSION_EXPIRY_PATTERN.fullmatch(value):
		frappe.throw(
			_("Session Expiry must use hours:minutes format such as 04:00."),
			frappe.ValidationError,
		)
	hours_str, minutes_str = value.split(":")
	hours, minutes = int(hours_str), int(minutes_str)
	total_minutes = hours * 60 + minutes
	if minutes >= 60 or total_minutes < 1 or total_minutes > MAX_SESSION_EXPIRY_MINUTES:
		frappe.throw(
			_("Session Expiry must be between 00:01 and 170:00."),
			frappe.ValidationError,
		)


def validate_time_zone(value: object) -> None:
	if not isinstance(value, str) or value not in ALLOWED_TIME_ZONES:
		frappe.throw(_("Select a supported time zone."), frappe.ValidationError)
	try:
		ZoneInfo(value)
	except (ValueError, KeyError, OSError):
		frappe.throw(_("Select a supported time zone."), frappe.ValidationError)


class TenantSettings(Document):
	def load_from_db(self):
		super().load_from_db()
		system_values = frappe.db.get_singles_dict("System Settings")
		for field in SYNCED_FIELDS:
			if system_values.get(field):
				self.set(field, system_values[field])
		email_domain, email_account = read_only_email_values()
		self.set("email_domain", email_domain)
		self.set("email_account", email_account)
		return self

	def validate(self):
		expected_domain, expected_account = read_only_email_values()
		if (self.email_domain or "") != expected_domain or (self.email_account or "") != expected_account:
			frappe.throw(
				_("Email Domain and Outgoing Email Account are read-only."),
				frappe.PermissionError,
			)
		self.email_domain = expected_domain
		self.email_account = expected_account

		if self.language not in ALLOWED_LANGUAGES or not frappe.db.exists("Language", self.language):
			frappe.throw(_("Select a supported language."), frappe.ValidationError)
		validate_time_zone(self.time_zone)
		if self.date_format not in ALLOWED_DATE_FORMATS:
			frappe.throw(_("Select a supported date format."), frappe.ValidationError)
		if self.time_format not in ALLOWED_TIME_FORMATS:
			frappe.throw(_("Select a supported time format."), frappe.ValidationError)
		if self.number_format not in ALLOWED_NUMBER_FORMATS:
			frappe.throw(_("Select a supported number format."), frappe.ValidationError)
		validate_session_expiry(self.session_expiry)

	def on_update(self):
		changes = {field: self.get(field) for field in SYNCED_FIELDS}
		# Only the six allow-listed fields sync to System Settings; security settings stay untouched.
		frappe.db.set_single_value("System Settings", changes)
		for field, value in changes.items():
			frappe.db.set_default(field, value)
		if self.language:
			set_default_language(self.language)
		clear_system_settings_cache()
		invalidate_permissions()
