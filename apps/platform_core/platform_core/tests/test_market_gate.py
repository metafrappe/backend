"""A purchase completes only in an open market (AJA-1768, AJA-1732).

Choosing a language does not open a market. Until the product owner announces the list,
only TR is open. The list lives in one setting: `platform_core/config/open_markets.json`.
"""

import ast
import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from platform_core import market_gate
from platform_core.market_gate import (
	MarketNotOpenError,
	MarketRequiredError,
	create_in_open_market,
	open_markets,
)

# ToDo stands in for the purchase record, so the test can count the records.
DOCTYPE = "ToDo"
MARKER = "market gate purchase"
SETTING_FILE = Path(market_gate.__file__).parent / "config" / "open_markets.json"


class MarketGateTest(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.local.response = frappe._dict()
		self.lang = frappe.local.lang
		frappe.db.delete(DOCTYPE, {"description": MARKER})

	def tearDown(self):
		frappe.local.lang = self.lang

	def count(self):
		return frappe.db.count(DOCTYPE, {"description": MARKER})

	def purchase(self, market):
		return create_in_open_market(DOCTYPE, {"description": MARKER}, market)

	def test_purchase_in_tr_market_completes(self):
		doc = self.purchase("TR")
		self.assertEqual(doc.doctype, DOCTYPE)
		self.assertEqual(self.count(), 1)
		self.assertNotIn("market_error", frappe.local.response)

	def test_purchase_in_de_market_is_refused_and_creates_no_record(self):
		with self.assertRaises(MarketNotOpenError) as error:
			self.purchase("DE")
		self.assertEqual(error.exception.http_status_code, 422)
		self.assertEqual(
			frappe.local.response.get("market_error"),
			{"code": "MarketNotOpenError", "market": "DE", "open_markets": ["TR"]},
		)
		self.assertEqual(self.count(), 0)

	def test_german_interface_does_not_change_the_tr_purchase(self):
		frappe.local.lang = "de"
		self.purchase("TR")
		self.assertEqual(self.count(), 1)

	def test_empty_market_is_refused(self):
		for market in (None, "", "  "):
			frappe.local.response = frappe._dict()
			with self.assertRaises(MarketRequiredError) as error:
				self.purchase(market)
			self.assertEqual(error.exception.http_status_code, 422)
			self.assertEqual(
				frappe.local.response.get("market_error"),
				{"code": "MarketRequiredError", "market": None, "open_markets": ["TR"]},
			)
		self.assertEqual(self.count(), 0)

	def test_lowercase_market_code_is_not_open(self):
		with self.assertRaises(MarketNotOpenError):
			self.purchase("tr")
		self.assertEqual(self.count(), 0)

	def test_open_markets_come_from_one_setting(self):
		self.assertEqual(json.loads(SETTING_FILE.read_text()), {"open_markets": ["TR"]})
		self.assertEqual(open_markets(), ["TR"])
		# The product owner changes only the setting. The gate follows it.
		with patch.object(market_gate, "read_setting", return_value={"open_markets": ["DE"]}):
			self.assertEqual(open_markets(), ["DE"])
			self.purchase("DE")
			with self.assertRaises(MarketNotOpenError):
				self.purchase("TR")
		self.assertEqual(self.count(), 1)

	def test_code_has_no_second_market_list(self):
		tree = ast.parse(Path(market_gate.__file__).read_text())
		literals = [
			node.value
			for node in ast.walk(tree)
			if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.isupper()
		]
		self.assertEqual([value for value in literals if len(value) == 2], [])
