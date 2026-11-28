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
# Strict ASCII digits only: rejects Unicode digits such as Arabic-Indic numerals.
SESSION_EXPIRY_PATTERN = re.compile(r"[0-9]{1,3}:[0-9]{2}")
# O-25 (Decision 19): tenant idle timeout ceiling is 1 hour (01:00).
MAX_SESSION_EXPIRY_MINUTES = 60
DEFAULT_SESSION_EXPIRY = "01:00"


def read_only_email_values() -> tuple[str, str]:
	"""Read only the public outgoing mail domain and sender address, never credentials."""
	# System email identifiers shown read-only to the tenant admin (exception to G-3).
	accounts = frappe.get_all(
		"Email Account",
		filters={"default_outgoing": 1, "enable_outgoing": 1},
		fields=["email_id", "domain"],
		order_by="name asc",
		limit=1,
	) or frappe.get_all(
		"Email Account",
		filters={"enable_outgoing": 1},
		fields=["email_id", "domain"],
		order_by="name asc",
		limit=1,
	)
	account = accounts[0] if accounts else None
	email_account = (account.get("email_id") or "") if account else ""
	domain_ref = (account.get("domain") or "") if account else ""
	if domain_ref:
		email_domain = frappe.db.get_value("Email Domain", domain_ref, "domain_name") or domain_ref
	else:
		domains = frappe.get_all(
			"Email Domain",
			fields=["domain_name"],
			order_by="domain_name asc, name asc",
			limit=1,
		)
		email_domain = (domains[0].get("domain_name") or "") if domains else ""
	return str(email_domain), str(email_account)


def parse_session_expiry_minutes(value: object) -> int | None:
	"""Return total minutes for a valid ASCII hh:mm duration within the O-25 ceiling, else None."""
	if not isinstance(value, str) or not SESSION_EXPIRY_PATTERN.fullmatch(value):
		return None
	hours_str, minutes_str = value.split(":")
	hours, minutes = int(hours_str), int(minutes_str)
	total_minutes = hours * 60 + minutes
	if minutes >= 60 or total_minutes < 1 or total_minutes > MAX_SESSION_EXPIRY_MINUTES:
		return None
	return total_minutes


def validate_session_expiry(value: object) -> None:
	if not isinstance(value, str) or not SESSION_EXPIRY_PATTERN.fullmatch(value):
		frappe.throw(
			_("Session Expiry must use hours:minutes format such as 00:30."),
			frappe.ValidationError,
		)
	if parse_session_expiry_minutes(value) is None:
		frappe.throw(
			_("Session Expiry must be between 00:01 and 01:00."),
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
		domain_value = "" if self.email_domain is None else self.email_domain
		account_value = "" if self.email_account is None else self.email_account
		if (
			not isinstance(domain_value, str)
			or not isinstance(account_value, str)
			or domain_value != expected_domain
			or account_value != expected_account
		):
			frappe.throw(
				_("Email Domain and Outgoing Email Account are read-only."),
				frappe.PermissionError,
			)
		self.email_domain = expected_domain
		self.email_account = expected_account

		if (
			not isinstance(self.language, str)
			or self.language not in ALLOWED_LANGUAGES
			or not frappe.db.exists("Language", self.language)
		):
			frappe.throw(_("Select a supported language."), frappe.ValidationError)
		validate_time_zone(self.time_zone)
		if not isinstance(self.date_format, str) or self.date_format not in ALLOWED_DATE_FORMATS:
			frappe.throw(_("Select a supported date format."), frappe.ValidationError)
		if not isinstance(self.time_format, str) or self.time_format not in ALLOWED_TIME_FORMATS:
			frappe.throw(_("Select a supported time format."), frappe.ValidationError)
		if not isinstance(self.number_format, str) or self.number_format not in ALLOWED_NUMBER_FORMATS:
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
		frappe.local.system_settings = None
		invalidate_permissions()
