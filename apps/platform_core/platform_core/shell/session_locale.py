"""Locale fields of the bootstrap: language, region, time zone, currency and market (AJA-1767).

Each value is read on its own. The user setting comes first, then the tenant setting, then the
default. Choosing a language does not open a market or change the currency.

Settings live in Frappe defaults. They need no new DocType field:

- The user writes `market` and `measurement_system` with the user as parent.
- The tenant writes `market`, `transaction_currency` and `billing_country` as global defaults.
- The interface language comes from `User.language`, then from `System Settings.language`.
- The time zone comes from `User.time_zone`, then from the site time zone.
"""

import re
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_system_timezone

# Decision 44: British English when the user and the tenant have no language.
DEFAULT_LANGUAGE_TAG = "en-GB"
# Until the product owner announces the list, only TR is open (AJA-1732).
OPEN_MARKETS = ("TR",)
# Currency of a market. A market without a row gives no currency.
MARKET_CURRENCIES = {"TR": "TRY", "DE": "EUR", "GB": "GBP"}
# Regions whose road distances use miles. Every other region uses the metric system.
IMPERIAL_REGIONS = frozenset({"GB", "US"})
MEASUREMENT_SYSTEMS = ("metric", "imperial")

TENANT = "__default"
LANGUAGE_TAG = re.compile(r"^([a-z]{2,3})(?:-([A-Z][a-z]{3}))?(?:-([A-Z]{2}|[0-9]{3}))?$")
TIME_ZONE = re.compile(r"^(UTC|[A-Za-z_]+(/[A-Za-z0-9_+-]+)+)$")
CURRENCY = re.compile(r"^[A-Z]{3}$")
COUNTRY = re.compile(r"^[A-Z]{2}$")


def get_locale(user: str) -> dict:
	"""Locale of the session as the contract's Locale component. Reads only."""
	language_tag, language, region = _language(user)
	markets = list(OPEN_MARKETS)
	market = _market(user, markets)
	return {
		"language_tag": language_tag,
		"language": language,
		"region": region,
		"time_zone": _time_zone(user),
		"transaction_currency": _code(frappe.db.get_default("transaction_currency"), CURRENCY)
		or MARKET_CURRENCIES.get(market),
		"billing_country": _code(frappe.db.get_default("billing_country"), COUNTRY),
		"measurement_system": _measurement_system(user, region),
		"selected_market": market,
		"open_markets": markets,
	}


def set_measurement_system(user: str, value: str) -> None:
	"""Write the user's own choice of measurement system to the user setting."""
	if value not in MEASUREMENT_SYSTEMS:
		frappe.throw(
			frappe._("Choose metric or imperial.", context="platform_core.locale"), frappe.ValidationError
		)
	frappe.db.set_default("measurement_system", value, user)


def parse_language_tag(value) -> tuple[str, str, str | None] | None:
	"""Split a language tag such as en-GB or en-gb into the tag, language and region."""
	if not isinstance(value, str) or not value.strip():
		return None
	parts = value.strip().replace("_", "-").split("-")
	normal = [parts[0].lower()]
	for part in parts[1:]:
		normal.append(part.title() if len(part) == 4 else part.upper())
	tag = "-".join(normal)
	match = LANGUAGE_TAG.match(tag)
	if not match:
		return None
	return tag, match.group(1), match.group(3) if match.group(3) and match.group(3).isalpha() else None


def _language(user: str) -> tuple[str, str, str | None]:
	for value in (
		frappe.db.get_value("User", user, "language"),
		frappe.db.get_single_value("System Settings", "language"),
	):
		if parsed := parse_language_tag(value):
			return parsed
	return parse_language_tag(DEFAULT_LANGUAGE_TAG)


def _time_zone(user: str) -> str:
	site = get_system_timezone()
	for value in (frappe.db.get_value("User", user, "time_zone"), site):
		if _valid_time_zone(value):
			return value
	return "UTC"


def _valid_time_zone(value) -> bool:
	if not isinstance(value, str) or not TIME_ZONE.match(value):
		return False
	try:
		ZoneInfo(value)
	except (ValueError, KeyError, OSError):
		return False
	return True


def _market(user: str, markets: list[str]) -> str | None:
	stored = _code(frappe.db.get_default("market", user), COUNTRY) or _code(
		frappe.db.get_default("market", TENANT), COUNTRY
	)
	if stored is None:
		return markets[0] if markets else None
	return stored if stored in markets else None


def _measurement_system(user: str, region: str | None) -> str:
	choice = frappe.db.get_default("measurement_system", user)
	if choice in MEASUREMENT_SYSTEMS:
		return choice
	return "imperial" if region in IMPERIAL_REGIONS else "metric"


def _code(value, pattern: re.Pattern) -> str | None:
	if not isinstance(value, str):
		return None
	code = value.strip().upper()
	return code if pattern.match(code) else None
