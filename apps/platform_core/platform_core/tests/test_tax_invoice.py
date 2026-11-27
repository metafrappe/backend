"""Tax service down and old invoices (AJA-1759, AJA-1731).

Test 1: the tax service is down. The result says so, the tax is never "0.00" and the purchase
does not finish.
Test 2: the rate changes after an invoice is issued. Opening the old invoice gives back the
original date, rate and amount.

The expected amounts come from the task, not from the code. All rates and country codes are
fictional. Standard library only. Run from the repository root:

python3.14 -I -m unittest discover -s apps/platform_core/platform_core/tests -t apps/platform_core -p 'test_tax_*.py' -v
"""

from __future__ import annotations

import copy
import datetime
import unittest

from platform_core.tax_invoice import InvoiceBook, PurchaseBlockedError, purchase
from platform_core.tax_quote import quote
from platform_core.tests.test_tax_quote import LINE_A, LINE_B, RULES, SCHEMA, validate

KEY = "3f2b8c1e-6d4a-4f0b-9a7e-2c5d8e1f0a3b"
ISSUED = datetime.date(2026, 11, 27)


def buy(book, rules, number="INV-TEST-0001", **extra):
	args = {
		"billing_country": "ZZ",
		"currency": "EUR",
		"discount": "15.00",
		"rules": rules,
		"idempotency_key": KEY,
		"invoice_number": number,
		"issued_on": ISSUED,
		"book": book,
	}
	return purchase([LINE_A, LINE_B], **{**args, **extra})


class TaxServiceDownTest(unittest.TestCase):
	def test_quote_says_service_down_and_tax_is_not_zero(self):
		result = quote([LINE_A, LINE_B], billing_country="ZZ", currency="EUR", discount="15.00", rules=None)
		validate(result, SCHEMA)
		for line in result["lines"]:
			self.assertEqual(line["tax_status"], "service_unavailable")
			self.assertEqual(line["reason_code"], "TAX_SERVICE_UNAVAILABLE")
			self.assertEqual(line["label_key_short"], "tax.status.service_unavailable.short")
			self.assertIsNone(line["tax"])
			self.assertIsNone(line["gross"])
		self.assertIsNone(result["totals"]["tax"])
		self.assertIsNone(result["totals"]["gross"])
		self.assertNotIn('"0.00"', repr([line["tax"] for line in result["lines"]]))

	def test_purchase_does_not_finish_when_service_down(self):
		book = InvoiceBook()
		with self.assertRaises(PurchaseBlockedError) as caught:
			buy(book, rules=None)
		self.assertEqual(caught.exception.tax_status, "service_unavailable")
		self.assertEqual(caught.exception.reason_codes, ["TAX_SERVICE_UNAVAILABLE"])
		self.assertEqual(caught.exception.label_key_short, "tax.status.service_unavailable.short")
		self.assertEqual(len(book), 0)
		with self.assertRaises(KeyError):
			book.open("INV-TEST-0001")

	def test_purchase_does_not_finish_when_tax_not_calculated(self):
		book = InvoiceBook()
		with self.assertRaises(PurchaseBlockedError) as caught:
			purchase(
				[LINE_A],
				billing_country="XX",
				currency="EUR",
				discount="0",
				rules=RULES,
				idempotency_key=KEY,
				invoice_number="INV-TEST-0001",
				issued_on=ISSUED,
				book=book,
			)
		self.assertEqual(caught.exception.tax_status, "not_calculated")
		self.assertEqual(caught.exception.reason_codes, ["TAX_UNSUPPORTED_COUNTRY"])
		self.assertEqual(len(book), 0)

	def test_purchase_needs_an_idempotency_key(self):
		with self.assertRaises(ValueError):
			buy(InvoiceBook(), rules=RULES, idempotency_key=None)

	def test_purchase_works_when_service_is_up(self):
		book = InvoiceBook()
		result = buy(book, rules=RULES)
		validate(result, SCHEMA)
		self.assertEqual(result["operation"], "purchase")
		self.assertEqual(result["idempotency_key"], KEY)
		self.assertEqual(result["totals"]["gross"]["value"], "153.00")
		self.assertEqual(result["invoice"]["invoice_number"], "INV-TEST-0001")
		self.assertEqual(result["invoice"]["issued_on"], "2026-11-27")
		self.assertEqual(len(book), 1)


class OldInvoiceTest(unittest.TestCase):
	def test_rate_change_keeps_old_invoice(self):
		book = InvoiceBook()
		buy(book, rules=RULES)

		# The fictional rates change after the invoice was issued.
		new_rules = copy.deepcopy(RULES)
		new_rules["ZZ"]["reduced"]["rate"] = "25"
		new_rules["ZZ"]["standard"]["rate"] = "30"
		today = quote(
			[LINE_A, LINE_B], billing_country="ZZ", currency="EUR", discount="15.00", rules=new_rules
		)
		self.assertEqual([line["tax_rate"] for line in today["lines"]], ["25", "30"])

		old = book.open("INV-TEST-0001")
		validate(old, SCHEMA["$defs"]["invoiceSnapshot"])
		self.assertEqual(old["issued_on"], "2026-11-27")
		self.assertEqual([line["tax_rate"] for line in old["lines"]], ["10", "20"])
		self.assertEqual([line["tax"]["value"] for line in old["lines"]], ["9.00", "9.00"])
		self.assertEqual(old["totals"]["net"]["value"], "135.00")
		self.assertEqual(old["totals"]["tax"]["value"], "18.00")
		self.assertEqual(old["totals"]["gross"]["value"], "153.00")

	def test_changing_rule_table_after_issue_does_not_reach_invoice(self):
		book = InvoiceBook()
		rules = copy.deepcopy(RULES)
		buy(book, rules=rules)
		rules["ZZ"]["reduced"]["rate"] = "99"
		self.assertEqual(book.open("INV-TEST-0001")["lines"][0]["tax_rate"], "10")

	def test_opening_is_a_read_and_cannot_edit_the_invoice(self):
		book = InvoiceBook()
		buy(book, rules=RULES)
		first = book.open("INV-TEST-0001")
		first["totals"]["gross"]["value"] = "1.00"
		first["lines"][0]["tax_rate"] = "99"
		again = book.open("INV-TEST-0001")
		self.assertEqual(again["totals"]["gross"]["value"], "153.00")
		self.assertEqual(again["lines"][0]["tax_rate"], "10")

	def test_invoice_number_cannot_be_reissued_with_new_amounts(self):
		book = InvoiceBook()
		buy(book, rules=RULES)
		new_rules = copy.deepcopy(RULES)
		new_rules["ZZ"]["reduced"]["rate"] = "25"
		with self.assertRaises(ValueError):
			buy(book, rules=new_rules)
		self.assertEqual(book.open("INV-TEST-0001")["lines"][0]["tax_rate"], "10")


if __name__ == "__main__":
	unittest.main()
