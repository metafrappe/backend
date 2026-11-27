"""Price quote: discount split and tax per line (AJA-1757, AJA-1731).

The expected amounts come from the task, not from the code. The result must follow
contracts/tax_result.schema.json (AJA-1756). All rates and country codes here are fictional.

Standard library only. Run from the repository root:

python3 -I -m unittest discover -s apps/platform_core/platform_core/tests -t apps/platform_core -p test_tax_quote.py -v
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from platform_core.tax_quote import quote

REPO = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((REPO / "contracts" / "tax_result.schema.json").read_text(encoding="utf-8"))

# Fictional rule table. "ZZ" and "QZ" are user-assigned codes, not real countries.
RULES = {
	"ZZ": {
		"reduced": {"status": "calculated", "reason": "TAX_REDUCED_RATE", "rate": "10"},
		"standard": {"status": "calculated", "reason": "TAX_STANDARD_RATE", "rate": "20"},
		"export": {"status": "zero_rated", "reason": "TAX_ZERO_RATE_EXPORT", "rate": "0"},
		"training": {"status": "exempt", "reason": "TAX_EXEMPT_BY_LAW"},
		"b2b": {"status": "reverse_charge", "reason": "TAX_REVERSE_CHARGE_B2B"},
	},
	"QZ": {
		"reduced": {"status": "calculated", "reason": "TAX_REDUCED_RATE", "rate": "5"},
		"standard": {"status": "calculated", "reason": "TAX_STANDARD_RATE", "rate": "15"},
	},
}

LINE_A = {"line_id": "A", "description": "Plan A", "net": "100.00", "tax_class": "reduced"}
LINE_B = {"line_id": "B", "description": "Plan B", "net": "50.00", "tax_class": "standard"}


def values(result, field):
	return [None if line[field] is None else line[field]["value"] for line in result["lines"]]


def validate(value, schema, path="$"):
	"""Small JSON Schema check for the keywords the tax contract uses."""
	if "$ref" in schema:
		name = schema["$ref"].rsplit("/", 1)[-1]
		return validate(value, SCHEMA["$defs"][name], path)
	if "const" in schema and value != schema["const"]:
		raise AssertionError(f"{path}: {value!r} is not {schema['const']!r}")
	if "enum" in schema and value not in schema["enum"]:
		raise AssertionError(f"{path}: {value!r} is not in {schema['enum']}")
	kind = schema.get("type")
	checks = {"object": dict, "array": list, "string": str, "null": type(None)}
	if kind and not isinstance(value, checks[kind]):
		raise AssertionError(f"{path}: {value!r} is not {kind}")
	if "pattern" in schema and not re.search(schema["pattern"], value):
		raise AssertionError(f"{path}: {value!r} does not match {schema['pattern']}")
	if "oneOf" in schema:
		passed = 0
		for option in schema["oneOf"]:
			try:
				validate(value, option, path)
				passed += 1
			except AssertionError:
				pass
		if passed != 1:
			raise AssertionError(f"{path}: {value!r} matches {passed} oneOf options")
	for part in schema.get("allOf", []):
		if "if" in part:
			try:
				validate(value, part["if"], path)
				branch = part.get("then")
			except AssertionError:
				branch = part.get("else")
			if branch:
				validate(value, branch, path)
		else:
			validate(value, part, path)
	if isinstance(value, dict):
		for name in schema.get("required", []):
			if name not in value:
				raise AssertionError(f"{path}: {name} is missing")
		props = schema.get("properties", {})
		if schema.get("additionalProperties") is False:
			extra = set(value) - set(props)
			if extra:
				raise AssertionError(f"{path}: extra fields {sorted(extra)}")
		for name, sub in props.items():
			if name in value:
				validate(value[name], sub, f"{path}.{name}")
	if isinstance(value, list):
		if len(value) < schema.get("minItems", 0):
			raise AssertionError(f"{path}: too few items")
		if "items" in schema:
			for index, item in enumerate(value):
				validate(item, schema["items"], f"{path}[{index}]")


class TaxQuoteTest(unittest.TestCase):
	def run_quote(self, lines, country="ZZ", discount="0", **extra):
		result = quote(
			lines, billing_country=country, currency="EUR", discount=discount, rules=RULES, **extra
		)
		validate(result, SCHEMA)
		return result

	# Test 1: the worked example from the task.
	def test_discount_split_and_tax(self):
		result = self.run_quote([LINE_A, LINE_B], discount="15.00")
		self.assertEqual(values(result, "net"), ["90.00", "45.00"])
		self.assertEqual([line["tax_rate"] for line in result["lines"]], ["10", "20"])
		self.assertEqual(values(result, "tax"), ["9.00", "9.00"])
		self.assertEqual(result["totals"]["net"]["value"], "135.00")
		self.assertEqual(result["totals"]["tax"]["value"], "18.00")
		self.assertEqual(result["totals"]["gross"]["value"], "153.00")
		self.assertEqual(result["operation"], "quote")
		self.assertIsNone(result["idempotency_key"])
		self.assertIsNone(result["invoice"])

	def test_discount_cents_are_not_lost(self):
		lines = [
			{"line_id": str(n), "description": "x", "net": "10.00", "tax_class": "reduced"}
			for n in range(3)
		]
		result = self.run_quote(lines, discount="10.00")
		self.assertEqual(sorted(values(result, "net")), ["6.66", "6.67", "6.67"])
		self.assertEqual(result["totals"]["net"]["value"], "20.00")

	def test_discount_larger_than_total_is_refused(self):
		with self.assertRaises(ValueError):
			quote([LINE_A], billing_country="ZZ", currency="EUR", discount="100.01", rules=RULES)

	# Test 2: each tax state returns its own reason code.
	def test_each_state_has_its_own_reason_code(self):
		cases = {
			"zero_rated": ({"tax_class": "export"}, "ZZ", {}, "TAX_ZERO_RATE_EXPORT"),
			"exempt": ({"tax_class": "training"}, "ZZ", {}, "TAX_EXEMPT_BY_LAW"),
			"reverse_charge": (
				{"tax_class": "b2b"}, "ZZ", {"buyer_tax_id": "ZZ000"}, "TAX_REVERSE_CHARGE_B2B"
			),
			"not_calculated": ({"tax_class": "reduced"}, "XX", {}, "TAX_UNSUPPORTED_COUNTRY"),
		}
		seen = set()
		for status, (change, country, extra, reason) in cases.items():
			with self.subTest(status=status):
				line = {**LINE_A, **change}
				result = self.run_quote([line], country=country, **extra)
				out = result["lines"][0]
				self.assertEqual(out["tax_status"], status)
				self.assertEqual(out["reason_code"], reason)
				self.assertEqual(out["label_key_short"], f"tax.status.{status}.short")
				if status == "not_calculated":
					self.assertIsNone(out["tax"])
					self.assertIsNone(result["totals"]["tax"])
					self.assertIsNone(result["totals"]["gross"])
				else:
					self.assertEqual(out["tax"]["value"], "0.00")
					self.assertEqual(out["gross"]["value"], "100.00")
				seen.add(out["reason_code"])
		self.assertEqual(len(seen), 4)

	def test_reverse_charge_without_buyer_tax_id_is_not_calculated(self):
		result = self.run_quote([{**LINE_A, "tax_class": "b2b"}])
		self.assertEqual(result["lines"][0]["tax_status"], "not_calculated")
		self.assertEqual(result["lines"][0]["reason_code"], "TAX_MISSING_TAX_ID")

	def test_rule_service_down_is_not_zero(self):
		result = quote(
			[LINE_A], billing_country="ZZ", currency="EUR", discount="0", rules=None
		)
		validate(result, SCHEMA)
		self.assertEqual(result["lines"][0]["tax_status"], "service_unavailable")
		self.assertEqual(result["lines"][0]["reason_code"], "TAX_SERVICE_UNAVAILABLE")
		self.assertIsNone(result["lines"][0]["tax"])

	# Test 3: the interface language never changes the amount.
	def test_language_does_not_change_amount(self):
		tr = self.run_quote([LINE_A, LINE_B], discount="15.00", language="tr")
		en = self.run_quote([LINE_A, LINE_B], discount="15.00", language="en")
		self.assertEqual(tr, en)
		self.assertNotIn("language", tr)

	# Test 4: a new billing country means a new calculation.
	def test_billing_country_change_recalculates(self):
		zz = self.run_quote([LINE_A, LINE_B], country="ZZ", discount="15.00")
		qz = self.run_quote([LINE_A, LINE_B], country="QZ", discount="15.00")
		self.assertEqual(qz["billing_country"], "QZ")
		self.assertEqual(values(qz, "tax"), ["4.50", "6.75"])
		self.assertEqual(qz["totals"]["tax"]["value"], "11.25")
		self.assertEqual(qz["totals"]["gross"]["value"], "146.25")
		self.assertNotEqual(zz["totals"]["gross"], qz["totals"]["gross"])
		self.assertEqual(zz["totals"]["net"], qz["totals"]["net"])


if __name__ == "__main__":
	unittest.main()
