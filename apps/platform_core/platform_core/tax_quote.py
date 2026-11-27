"""Price quote: split the discount over the lines, then work out the tax per line (AJA-1757).

The result follows contracts/tax_result.schema.json (AJA-1756). A quote is a read: it writes
no record, so it needs no idempotency key and has no invoice copy.

The billing country decides the tax. The interface language never does. Callers may pass the
language, but it does not reach the calculation or the result.

This module holds no tax rate. The caller passes a rule table:

    {"<country>": {"<tax class>": {"status": ..., "reason": ..., "rate": "<percent>"}}}

`rules=None` means the tax rule service could not be reached.

Amounts are Decimal and leave as decimal text. A float never takes part.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")

KNOWN_TAX = {"calculated", "zero_rated", "exempt", "reverse_charge"}
REASONS = {
	"calculated": {"TAX_STANDARD_RATE", "TAX_REDUCED_RATE"},
	"zero_rated": {"TAX_ZERO_RATE_EXPORT", "TAX_ZERO_RATE_GOODS"},
	"exempt": {"TAX_EXEMPT_BY_LAW", "TAX_EXEMPT_CUSTOMER"},
	"reverse_charge": {"TAX_REVERSE_CHARGE_B2B"},
}


def _money(value: Decimal, currency: str) -> dict[str, str]:
	return {"value": str(value.quantize(CENT)), "currency": currency}


def _cents(value: Any) -> Decimal:
	if isinstance(value, float):
		raise TypeError("amounts must be decimal text, not float")
	amount = Decimal(str(value))
	if amount != amount.quantize(CENT):
		raise ValueError(f"amount has more than two decimals: {value}")
	return amount


def split_discount(nets: Sequence[Decimal], discount: Decimal) -> list[Decimal]:
	"""Share the discount by line net. The shares add up to the discount to the cent.

	Each line first gets its share rounded down. The cents left go one by one to the lines
	with the largest cut remainder. On a tie the earlier line wins.
	"""
	total = sum(nets, Decimal(0))
	if discount < 0:
		raise ValueError("discount cannot be negative")
	if discount > total:
		raise ValueError("discount cannot be larger than the total")
	if discount == 0:
		return [Decimal("0.00") for _ in nets]
	exact = [net * discount / total for net in nets]
	shares = [part.quantize(CENT, rounding=ROUND_DOWN) for part in exact]
	left = int((discount - sum(shares, Decimal(0))) / CENT)
	order = sorted(range(len(nets)), key=lambda i: (-(exact[i] - shares[i]), i))
	for index in order[:left]:
		shares[index] += CENT
	return shares


def _status(status: str, reason: str) -> dict[str, str]:
	return {
		"tax_status": status,
		"reason_code": reason,
		"label_key_short": f"tax.status.{status}.short",
		"label_key_long": f"tax.status.{status}.long",
	}


def _tax_line(
	line: Mapping[str, Any],
	net: Decimal,
	currency: str,
	country_rules: Mapping[str, Any] | None,
	service_down: bool,
	buyer_tax_id: str | None,
) -> dict[str, Any]:
	out: dict[str, Any] = {
		"line_id": str(line["line_id"]),
		"description": str(line.get("description", "")),
		"net": _money(net, currency),
		"tax_rate": None,
		"tax": None,
		"gross": None,
	}
	if service_down:
		return {**out, **_status("service_unavailable", "TAX_SERVICE_UNAVAILABLE")}
	if country_rules is None:
		return {**out, **_status("not_calculated", "TAX_UNSUPPORTED_COUNTRY")}

	rule = country_rules.get(line["tax_class"])
	if rule is None:
		raise ValueError(f"no tax rule for class {line['tax_class']!r}")
	status, reason = rule["status"], rule["reason"]
	if status not in KNOWN_TAX or reason not in REASONS[status]:
		raise ValueError(f"rule has a wrong status or reason: {status} {reason}")
	if status == "reverse_charge" and not buyer_tax_id:
		return {**out, **_status("not_calculated", "TAX_MISSING_TAX_ID")}

	tax = Decimal("0.00")
	if status in {"calculated", "zero_rated"}:
		rate = Decimal(str(rule["rate"]))
		out["tax_rate"] = str(rule["rate"])
		tax = (net * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
	if status != "calculated" and tax != 0:
		raise ValueError(f"{status} must have zero tax")
	out["tax"] = _money(tax, currency)
	out["gross"] = _money(net + tax, currency)
	return {**out, **_status(status, reason)}


def quote(
	lines: Sequence[Mapping[str, Any]],
	*,
	billing_country: str,
	currency: str,
	discount: Any,
	rules: Mapping[str, Mapping[str, Any]] | None,
	buyer_tax_id: str | None = None,
	language: str | None = None,
) -> dict[str, Any]:
	"""Return a quote result that follows the tax result contract. Writes nothing."""
	del language  # The language never decides the tax (contracts/tax-result.md).
	country = (billing_country or "").strip().upper()
	if len(country) != 2 or not country.isalpha():
		# The contract needs a billing country on every result.
		raise ValueError("billing country is required")
	if not lines:
		raise ValueError("a quote needs at least one line")

	nets = [_cents(line["net"]) for line in lines]
	shares = split_discount(nets, _cents(discount))
	country_rules = None if rules is None else rules.get(country)
	out_lines = [
		_tax_line(line, net - share, currency, country_rules, rules is None, buyer_tax_id)
		for line, net, share in zip(lines, nets, shares, strict=True)
	]

	net_total = sum((Decimal(line["net"]["value"]) for line in out_lines), Decimal(0))
	known = all(line["tax"] is not None for line in out_lines)
	tax_total = sum((Decimal(line["tax"]["value"]) for line in out_lines), Decimal(0)) if known else None
	return {
		"operation": "quote",
		"idempotency_key": None,
		"billing_country": country,
		"currency": currency,
		"lines": out_lines,
		"totals": {
			"net": _money(net_total, currency),
			"tax": None if tax_total is None else _money(tax_total, currency),
			"gross": None if tax_total is None else _money(net_total + tax_total, currency),
		},
		"invoice": None,
	}
