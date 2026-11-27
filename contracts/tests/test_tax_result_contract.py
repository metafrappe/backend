"""Checks for the price and tax result contract (AJA-1756).

The contract is contracts/tax_result.schema.json. Its rules are explained in
contracts/tax-result.md. Standard library only.

Run: python3 -I -m unittest discover -s contracts/tests -v
"""

from __future__ import annotations

import json
import re
import unittest
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "tax_result.schema.json"
DOC = ROOT / "tax-result.md"

STATUSES = {
    "calculated",
    "zero_rated",
    "exempt",
    "reverse_charge",
    "not_calculated",
    "service_unavailable",
}
# In these states no tax was computed. Tax and gross must be null, never "0.00".
NO_AMOUNT = {"not_calculated", "service_unavailable"}
# In these states the tax is known to be zero.
ZERO_TAX = {"zero_rated", "exempt", "reverse_charge"}
OPERATIONS = {"quote": False, "purchase": True, "refund": True}
# Rates are percent text with up to four decimals.
DECIMAL = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]{1,4})?$")
# Money always carries exactly two decimals (G-41: currency_precision=2).
MONEY = re.compile(r"^-?(0|[1-9][0-9]*)\.[0-9]{2}$")
CENT = Decimal("0.01")
ROUNDING = {"scale": 2, "mode": "ROUND_HALF_EVEN", "level": "line"}


def money_value(money: dict | None) -> Decimal | None:
    if money is None:
        return None
    return Decimal(money["value"])


class TaxResultContract(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(SCHEMA.is_file(), f"{SCHEMA} is missing")
        self.assertTrue(DOC.is_file(), f"{DOC} is missing")
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.defs = self.schema["$defs"]
        self.doc = DOC.read_text(encoding="utf-8")

    # 1. Each status is its own value with its own reason codes.
    def test_status_values(self) -> None:
        self.assertEqual(set(self.defs["taxStatus"]["enum"]), STATUSES)

    def test_every_status_has_reason_codes(self) -> None:
        reasons = self.schema["x-reason-codes"]
        self.assertEqual(set(reasons), STATUSES)
        seen: set[str] = set()
        for status, codes in reasons.items():
            self.assertTrue(codes, status)
            for code in codes:
                self.assertRegex(code, r"^TAX_[A-Z0-9_]+$")
                self.assertNotIn(code, seen, f"{code} is used by two statuses")
                seen.add(code)
        self.assertEqual(set(self.defs["reasonCode"]["enum"]), seen)

    def test_every_status_has_short_and_long_label_key(self) -> None:
        labels = self.schema["x-label-keys"]
        self.assertEqual(set(labels), STATUSES)
        for status, keys in labels.items():
            self.assertEqual(keys["short"], f"tax.status.{status}.short")
            self.assertEqual(keys["long"], f"tax.status.{status}.long")

    # 2. Amounts are decimal strings with a currency.
    def test_money_shape(self) -> None:
        money = self.defs["money"]
        self.assertEqual(set(money["required"]), {"value", "currency"})
        self.assertEqual(money["properties"]["value"]["type"], "string")
        self.assertEqual(money["properties"]["value"]["pattern"], MONEY.pattern)
        self.assertEqual(money["properties"]["currency"]["pattern"], "^[A-Z]{3}$")

    # 2b. Rounding rule (J-11): two decimals, half to even, per line.
    def test_rounding_rule_in_schema(self) -> None:
        rule = self.schema["x-rounding"]
        for key, value in ROUNDING.items():
            self.assertEqual(rule[key], value, key)
        self.assertEqual(self.defs["line"]["properties"]["tax_rate"]["oneOf"][0]["pattern"],
                         DECIMAL.pattern)

    def test_rounding_rule_in_doc(self) -> None:
        self.assertTrue("## Yuvarlama" in self.doc, "rounding section is missing")
        section = self.doc.split("## Yuvarlama", 1)[1].split("\n## ", 1)[0]
        for text in ("ROUND_HALF_EVEN", "iki ondalık", "satırda", "G-41", "K-8"):
            self.assertIn(text, section, text)

    def test_examples_show_half_even_and_line_rounding(self) -> None:
        half_even_differs = False
        line_level_differs = False
        for ex in self.schema["examples"]:
            raw_sum = Decimal(0)
            for line in ex["lines"]:
                if line["tax_rate"] is None or line["tax"] is None:
                    continue
                raw = money_value(line["net"]) * Decimal(line["tax_rate"]) / 100
                raw_sum += raw
                if raw.quantize(CENT, ROUND_HALF_EVEN) != raw.quantize(CENT, ROUND_HALF_UP):
                    half_even_differs = True
            if ex["totals"]["tax"] is not None:
                if raw_sum.quantize(CENT, ROUND_HALF_EVEN) != money_value(ex["totals"]["tax"]):
                    line_level_differs = True
        self.assertTrue(half_even_differs, "no example shows a half-to-even tie")
        self.assertTrue(line_level_differs, "no example shows line-level rounding")

    def test_line_fields(self) -> None:
        line = self.defs["line"]
        for name in ("net", "tax", "gross", "tax_rate", "tax_status", "reason_code",
                     "label_key_short", "label_key_long"):
            self.assertIn(name, line["required"])
        self.assertEqual(line["properties"]["tax"]["oneOf"][1], {"type": "null"})
        self.assertEqual(line["properties"]["gross"]["oneOf"][1], {"type": "null"})

    # 3. Language does not decide tax. The billing country does.
    def test_country_decides_tax_not_language(self) -> None:
        props = self.schema["properties"]
        self.assertIn("billing_country", self.schema["required"])
        self.assertEqual(props["billing_country"]["pattern"], "^[A-Z]{2}$")
        for name in ("locale", "language", "lang"):
            self.assertNotIn(name, props)
            self.assertNotIn(name, self.defs["line"]["properties"])

    # 4. Quote is a read. Purchase and refund carry an idempotency key.
    def test_operation_and_idempotency_key(self) -> None:
        self.assertEqual(set(self.schema["properties"]["operation"]["enum"]), set(OPERATIONS))
        self.assertIn("idempotency.md", self.doc)

    # 5. Invoice snapshot keeps the original date, rate and amount.
    def test_invoice_snapshot_is_read_only(self) -> None:
        snap = self.defs["invoiceSnapshot"]
        for name in ("invoice_number", "issued_on", "currency", "lines", "totals"):
            self.assertIn(name, snap["required"])
        self.assertTrue(snap.get("readOnly"))
        self.assertEqual(snap["properties"]["issued_on"]["format"], "date")
        # Snapshot lines reuse the line shape, so each keeps its own rate.
        self.assertEqual(snap["properties"]["lines"]["items"], {"$ref": "#/$defs/line"})

    # Examples must follow every rule above.
    def test_examples_cover_every_status(self) -> None:
        statuses = {line["tax_status"] for ex in self.schema["examples"] for line in ex["lines"]}
        self.assertEqual(statuses, STATUSES)

    def test_examples_follow_rules(self) -> None:
        for ex in self.schema["examples"]:
            needs_key = OPERATIONS[ex["operation"]]
            if needs_key:
                self.assertRegex(ex["idempotency_key"],
                                 r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
            else:
                self.assertIsNone(ex["idempotency_key"])
            currency = ex["currency"]
            for line in ex["lines"]:
                self.check_line(line, currency)
            self.check_totals(ex)

    def check_line(self, line: dict, currency: str) -> None:
        status = line["tax_status"]
        self.assertIn(line["reason_code"], self.schema["x-reason-codes"][status])
        self.assertEqual(line["label_key_short"], f"tax.status.{status}.short")
        for name in ("net", "tax", "gross"):
            money = line[name]
            if money is not None:
                self.assertRegex(money["value"], MONEY)
                self.assertEqual(money["currency"], currency)
        if status in NO_AMOUNT:
            # "0.00" would claim a known zero tax. The tax is unknown.
            self.assertIsNone(line["tax"], status)
            self.assertIsNone(line["gross"], status)
            self.assertIsNone(line["tax_rate"], status)
            return
        self.assertIsNotNone(line["tax"], status)
        net, tax, gross = (money_value(line[n]) for n in ("net", "tax", "gross"))
        self.assertEqual(net + tax, gross, status)
        if line["tax_rate"] is not None:
            # Tax is rounded on each line: two decimals, half to even.
            raw = net * Decimal(line["tax_rate"]) / 100
            self.assertEqual(tax, raw.quantize(CENT, ROUND_HALF_EVEN), line["line_id"])
        if status in ZERO_TAX:
            self.assertEqual(tax, Decimal(0), status)
        else:
            self.assertGreater(tax, Decimal(0), status)

    def check_totals(self, ex: dict) -> None:
        totals = ex["totals"]
        lines = ex["lines"]
        self.assertEqual(money_value(totals["net"]), sum(money_value(l["net"]) for l in lines))
        if any(l["tax"] is None for l in lines):
            self.assertIsNone(totals["tax"])
            self.assertIsNone(totals["gross"])
        else:
            self.assertEqual(money_value(totals["tax"]), sum(money_value(l["tax"]) for l in lines))
            self.assertEqual(money_value(totals["gross"]), sum(money_value(l["gross"]) for l in lines))

    def test_invoice_only_when_every_line_has_tax(self) -> None:
        for ex in self.schema["examples"]:
            snap = ex.get("invoice")
            if snap is None:
                continue
            self.assertNotEqual(ex["operation"], "quote")
            for line in ex["lines"]:
                self.assertNotIn(line["tax_status"], NO_AMOUNT)
            # At issue time the snapshot equals the result it was made from.
            self.assertEqual(snap["lines"], ex["lines"])
            self.assertEqual(snap["totals"], ex["totals"])
            self.assertEqual(snap["currency"], ex["currency"])


if __name__ == "__main__":
    unittest.main()
