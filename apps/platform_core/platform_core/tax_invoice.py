"""Purchase with a frozen invoice copy, and reading old invoices (AJA-1759).

A purchase finishes only when every line has a known tax. When the tax service is down or the
tax cannot be worked out, the purchase stops with `PurchaseBlockedError`. No invoice is written and
the tax is never shown as "0.00".

An issued invoice is a frozen copy (contracts/tax_result.schema.json, `invoiceSnapshot`).
Opening it is a read. It never looks at today's rule table, so a later rate change cannot
change the original date, rate or amount.

`InvoiceBook` keeps the copies in memory. It stands in for the invoice record until the
DocType exists. Duplicate purchase calls are handled by the idempotency layer (AJA-1750).
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from platform_core.tax_quote import quote

UNKNOWN_TAX = ("service_unavailable", "not_calculated")
KEY_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class PurchaseBlockedError(Exception):
	"""The tax is not known, so the purchase cannot finish.

	`tax_status` is the first unknown status found, with "service_unavailable" before
	"not_calculated". `reason_codes` lists that status's reason codes in line order, once each.
	"""

	def __init__(self, tax_status: str, reason_codes: list[str]):
		super().__init__(f"purchase blocked: {tax_status} {reason_codes}")
		self.tax_status = tax_status
		self.reason_codes = reason_codes
		self.label_key_short = f"tax.status.{tax_status}.short"
		self.label_key_long = f"tax.status.{tax_status}.long"


class InvoiceBook:
	"""Stores issued invoices as frozen JSON text. Every open returns a fresh copy."""

	def __init__(self) -> None:
		self._frozen: dict[str, str] = {}

	def __len__(self) -> int:
		return len(self._frozen)

	def issue(self, invoice: Mapping[str, Any]) -> None:
		number = invoice["invoice_number"]
		text = json.dumps(invoice, sort_keys=True, ensure_ascii=False)
		known = self._frozen.get(number)
		if known is not None and known != text:
			raise ValueError(f"invoice {number} is already issued with other values")
		self._frozen[number] = text

	def open(self, invoice_number: str) -> dict[str, Any]:
		"""Read an issued invoice. Raises KeyError when the number is unknown."""
		return json.loads(self._frozen[invoice_number])


def _blocked(lines: Sequence[Mapping[str, Any]]) -> PurchaseBlockedError | None:
	for status in UNKNOWN_TAX:
		reasons = [line["reason_code"] for line in lines if line["tax_status"] == status]
		if reasons:
			return PurchaseBlockedError(status, list(dict.fromkeys(reasons)))
	return None


def purchase(
	lines: Sequence[Mapping[str, Any]],
	*,
	billing_country: str,
	currency: str,
	discount: Any,
	rules: Mapping[str, Mapping[str, Any]] | None,
	idempotency_key: str | None,
	invoice_number: str,
	issued_on: datetime.date,
	book: InvoiceBook,
	buyer_tax_id: str | None = None,
) -> dict[str, Any]:
	"""Price the lines, then issue the invoice. Raises PurchaseBlockedError when the tax is unknown."""
	if not isinstance(idempotency_key, str) or not KEY_PATTERN.match(idempotency_key):
		raise ValueError("a purchase needs an idempotency key (contracts/idempotency.md)")
	if not invoice_number:
		raise ValueError("a purchase needs an invoice number")
	if not isinstance(issued_on, datetime.date) or isinstance(issued_on, datetime.datetime):
		raise TypeError("issued_on must be a date")

	priced = quote(
		lines,
		billing_country=billing_country,
		currency=currency,
		discount=discount,
		rules=rules,
		buyer_tax_id=buyer_tax_id,
	)
	blocked = _blocked(priced["lines"])
	if blocked is not None:
		raise blocked

	invoice = {
		"invoice_number": invoice_number,
		"issued_on": issued_on.isoformat(),
		"currency": priced["currency"],
		"lines": priced["lines"],
		"totals": priced["totals"],
	}
	book.issue(invoice)
	return {
		**priced,
		"operation": "purchase",
		"idempotency_key": idempotency_key,
		"invoice": book.open(invoice_number),
	}
