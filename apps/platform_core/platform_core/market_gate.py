"""Market gate: a purchase completes only in an open market (AJA-1768, AJA-1732).

The market is separate from the language. Choosing a German interface does not open the DE
market. The server checks the market on every purchase request.

The open markets come from one setting: `config/open_markets.json`. The product owner changes
only that file. This module holds no market code of its own.

A refused request gets HTTP 422. The error type (`exc_type`) and `market_error.code` carry the
machine-readable code: `MarketRequiredError` for an empty market and `MarketNotOpenError` for a
market that is not open.
"""

import json
from pathlib import Path
from typing import Any

import frappe
from frappe import _

SETTING_FILE = Path(__file__).parent / "config" / "open_markets.json"


class MarketRequiredError(frappe.ValidationError):
	"""The purchase request has no market."""

	http_status_code = 422


class MarketNotOpenError(frappe.ValidationError):
	"""The market of the purchase request is not open."""

	http_status_code = 422


def read_setting() -> dict[str, Any]:
	return json.loads(SETTING_FILE.read_text(encoding="utf-8"))


def open_markets() -> list[str]:
	"""Market codes that are open on this platform, in the order of the setting."""
	return list(read_setting()["open_markets"])


def _refuse(error: type[frappe.ValidationError], market: str | None, markets: list[str], message: str):
	frappe.local.response["market_error"] = {
		"code": error.__name__,
		"market": market,
		"open_markets": markets,
	}
	frappe.throw(message, error)


def require_open_market(market: str | None) -> str:
	"""Refuse an empty market or a market that is not open. Return the market code."""
	markets = open_markets()
	code = (market or "").strip()
	if not code:
		_refuse(
			MarketRequiredError,
			None,
			markets,
			_("Choose a market before you buy.", context="platform_core.market_gate"),
		)
	if code not in markets:
		_refuse(
			MarketNotOpenError,
			code,
			markets,
			_("Purchases are not open in this market.", context="platform_core.market_gate"),
		)
	return code


def create_in_open_market(doctype: str, values: dict[str, Any], market: str | None):
	"""Create a purchase record only after the market check passes."""
	require_open_market(market)
	return frappe.get_doc({**values, "doctype": doctype}).insert()
