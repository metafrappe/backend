"""Local contracts for G-65; these doubles do not replace a Frappe site test."""

import importlib
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[2]
sys.path.insert(0, str(APP))


class Document(dict):
    def __getattr__(self, name):
        return self.get(name)

    def __setattr__(self, name, value):
        self[name] = value

    def is_new(self):
        return self.get("_new", True)


def fake_frappe():
    frappe = ModuleType("frappe")
    frappe._ = lambda value: value
    frappe.ValidationError = ValueError
    frappe.PermissionError = PermissionError
    frappe.session = SimpleNamespace(user="Administrator")
    frappe.conf = {"trl_address_catalogue_ready": True}
    frappe.throw = Mock(side_effect=ValueError)
    frappe.db = Mock()
    frappe.get_all = Mock(return_value=[])
    frappe.get_doc = Mock()
    frappe.only_for = Mock()
    frappe.has_permission = Mock(return_value=True)
    frappe.whitelist = lambda **kwargs: lambda fn: fn
    return frappe


class FrappeFixture(unittest.TestCase):
    def setUp(self):
        self.frappe = fake_frappe()
        self.modules = patch.dict(sys.modules, {"frappe": self.frappe})
        self.modules.start()
        for name in list(sys.modules):
            if name.startswith("tr_localization."):
                del sys.modules[name]

    def tearDown(self):
        self.modules.stop()

    def load(self, name):
        return importlib.import_module("tr_localization." + name)


class LocalizationTest(FrappeFixture):
    def test_taxes_install_all_rates_on_company_scoped_accounts(self):
        inserted = []
        self.frappe.db.exists.return_value = False

        def account(doctype, filters, *args):
            self.assertEqual(doctype, "Account")
            self.assertEqual(filters["company"], "Example")
            self.assertEqual(filters["is_group"], 0)
            return filters["account_number"] + " - EX"

        self.frappe.db.get_value.side_effect = account
        self.frappe.get_doc.side_effect = lambda values: SimpleNamespace(
            insert=lambda: inserted.append(values)
        )
        self.load("company").install_tax_templates(
            Document(name="Example", country="Türkiye", chart_of_accounts="Turkey - Chart of Accounts")
        )
        for doctype in [
            "Sales Taxes and Charges Template",
            "Purchase Taxes and Charges Template",
            "Item Tax Template",
        ]:
            rows = [row for row in inserted if row["doctype"] == doctype]
            self.assertEqual(len(rows), 3)
            field = "tax_rate" if doctype == "Item Tax Template" else "rate"
            self.assertEqual({row["taxes"][0][field] for row in rows}, {20, 10, 1})
            self.assertTrue(all(row["company"] == "Example" for row in rows))
        sales = [row for row in inserted if row["doctype"] == "Sales Taxes and Charges Template"]
        self.assertEqual(
            {row["taxes"][0]["account_head"] for row in sales},
            {"391.01.04 - EX", "391.01.05 - EX", "391.01.03 - EX"},
        )
        self.assertTrue(all(row["is_default"] == 0 for row in sales))
        expected_accounts = {
            20: ("191.01.04 - EX", "391.01.04 - EX"),
            10: ("191.01.05 - EX", "391.01.05 - EX"),
            1: ("191.01.03 - EX", "391.01.03 - EX"),
        }
        for row in inserted:
            rate = int(row["title"].rsplit(" ", 1)[1])
            purchase, sale = expected_accounts[rate]
            if row["doctype"] == "Item Tax Template":
                self.assertEqual(
                    {(tax["tax_type"], tax["tax_rate"]) for tax in row["taxes"]},
                    {(purchase, rate), (sale, rate)},
                )
            else:
                expected = sale if row["doctype"] == "Sales Taxes and Charges Template" else purchase
                self.assertEqual(row["taxes"][0]["account_head"], expected)
                self.assertEqual(row["taxes"][0]["rate"], rate)

    def test_tax_install_does_not_overwrite_existing_templates(self):
        self.frappe.db.exists.return_value = True
        self.frappe.db.get_value.return_value = None
        self.load("company").install_tax_templates(
            Document(name="Example", country="Türkiye", chart_of_accounts="Turkey - Chart of Accounts")
        )
        self.frappe.get_doc.assert_not_called()
        self.frappe.db.get_value.assert_not_called()

    def test_catalogue_pair_fields_cannot_change_after_creation(self):
        import json

        schema = json.loads(
            (APP / "tr_localization/turkey_localization/doctype/trl_district/trl_district.json").read_text()
        )
        for field in schema["fields"]:
            if field["fieldname"] in {"province", "district"}:
                self.assertEqual(field.get("set_only_once"), 1)

    def test_missing_tax_account_rejects_before_any_write(self):
        self.frappe.db.exists.return_value = False
        self.frappe.db.get_value.return_value = None
        with self.assertRaises(ValueError):
            self.load("company").install_tax_templates(
                Document(name="Example", country="Türkiye", chart_of_accounts="Turkey - Chart of Accounts")
            )
        self.frappe.get_doc.assert_not_called()

    def test_foreign_company_does_not_get_turkish_taxes(self):
        self.load("company").install_tax_templates(Document(name="Example", country="Germany"))
        self.frappe.db.get_value.assert_not_called()
        self.frappe.get_doc.assert_not_called()

    def test_existing_custom_chart_is_not_modified_or_blocked(self):
        self.frappe.db.get_value.return_value = None
        company = Document(name="Example", country="Türkiye", chart_of_accounts="Custom", _new=False)
        original = company.copy()
        self.load("company").install_tax_templates(company)
        self.assertEqual(company, original)
        self.frappe.db.get_value.assert_not_called()
        self.frappe.get_doc.assert_not_called()

    def test_address_uses_province_and_district_pair(self):
        self.frappe.db.exists.return_value = True
        address = Document(
            country="Türkiye",
            state="Example Province",
            custom_trl_district="Example District",
            custom_trl_tax_id="0000000000",
            custom_trl_identity_number="",
        )
        self.load("address").validate_address(address)
        self.frappe.db.exists.assert_called_once_with(
            "TRL District",
            {
                "province": "Example Province",
                "district": "Example District",
                "enabled": 1,
            },
        )

    def test_address_rejects_unknown_pair(self):
        self.frappe.db.exists.return_value = False
        with self.assertRaises(ValueError):
            self.load("address").validate_address(
                Document(country="Türkiye", state="Example Province", custom_trl_district="Other District")
            )

    def test_unconfigured_catalogue_keeps_native_address_save(self):
        self.frappe.conf = {}
        self.frappe.db.exists.return_value = False
        self.load("address").validate_address(Document(country="Türkiye", state="Example Province"))
        self.frappe.db.exists.assert_not_called()

    def test_address_rejects_non_ascii_tax_identifier(self):
        self.frappe.db.exists.return_value = True
        with self.assertRaises(ValueError):
            self.load("address").validate_address(
                Document(
                    country="Türkiye",
                    state="Example Province",
                    custom_trl_district="Example District",
                    custom_trl_tax_id="１２３４５６７８９０",
                )
            )

    def test_foreign_address_keeps_native_rules(self):
        self.load("address").validate_address(Document(country="Germany"))
        self.frappe.db.exists.assert_not_called()

    def test_identity_number_requires_exactly_eleven_ascii_digits(self):
        self.frappe.conf = {}
        address = self.load("address")
        for value in ("0000000000", "000000000000", "１２３４５６７８９０１"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                address.validate_address(Document(country="Türkiye", custom_trl_identity_number=value))
        for value in ("00000000000", ""):
            address.validate_address(Document(country="Türkiye", custom_trl_identity_number=value))

    def test_currency_configuration_keeps_turkish_symbol_and_precision(self):
        currency = Mock()
        self.frappe.get_doc.return_value = currency
        self.load("install").configure_currency()
        self.frappe.get_doc.assert_called_once_with("Currency", "TRY")
        self.assertEqual(currency.symbol, "₺")
        self.assertEqual(currency.number_format, "#.###,##")
        self.assertEqual(currency.fraction_units, 100)
        self.assertEqual(currency.fraction, "Kuruş")
        currency.save.assert_called_once_with()

    def test_currency_configuration_leaves_enabling_to_g41(self):
        # platform_core.config.turkey_setup (G-41) already enables TRY. Do not write it twice.
        currency = Mock()
        self.frappe.get_doc.return_value = currency
        self.load("install").configure_currency()
        self.assertNotIn("enabled", vars(currency))
        source = (APP / "tr_localization" / "install.py").read_text()
        self.assertNotIn("currency.enabled", source)

    def test_install_hook_sets_currency_and_address_fields(self):
        module = self.load("install")
        with (
            patch.object(module, "configure_currency") as currency,
            patch.object(module, "install_address_fields") as fields,
        ):
            module.after_install()
        currency.assert_called_once_with()
        fields.assert_called_once_with()


class ExchangeContractTest(FrappeFixture):
    def test_exchange_accepts_seven_days_but_rejects_eight_days(self):
        parser = self.load("exchange").parse_rates
        self.assertEqual(len(parser(self.xml(day="11/16/2026"), today=date(2026, 11, 23))), 2)
        with self.assertRaises(ValueError):
            parser(self.xml(day="11/15/2026"), today=date(2026, 11, 23))

    def xml(self, unit="1", buying="35.50", selling="35.70", code="USD", day="11/20/2026"):
        return (
            f'<Tarih_Date Date="{day}"><Currency CurrencyCode="{code}"><Unit>{unit}</Unit>'
            f"<ForexBuying>{buying}</ForexBuying><ForexSelling>{selling}</ForexSelling>"
            "</Currency></Tarih_Date>"
        ).encode()

    def test_exchange_preserves_bulletin_date_and_unit(self):
        rates = self.load("exchange").parse_rates(self.xml(unit="100", code="JPY"), today=date(2026, 11, 23))
        self.assertEqual(
            rates,
            [
                {
                    "date": "2026-11-20",
                    "from_currency": "JPY",
                    "to_currency": "TRY",
                    "exchange_rate": Decimal("0.355"),
                    "for_buying": 1,
                    "for_selling": 0,
                },
                {
                    "date": "2026-11-20",
                    "from_currency": "JPY",
                    "to_currency": "TRY",
                    "exchange_rate": Decimal("0.357"),
                    "for_buying": 0,
                    "for_selling": 1,
                },
            ],
        )

    def test_exchange_rejects_invalid_numbers_dates_and_currency(self):
        for values in [
            {"unit": "0"},
            {"unit": "-1"},
            {"buying": "NaN"},
            {"selling": "Infinity"},
            {"buying": "-1"},
            {"code": "TRY"},
            {"code": "../"},
            {"day": "11/24/2026"},
            {"day": "10/01/2026"},
        ]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.load("exchange").parse_rates(self.xml(**values), today=date(2026, 11, 23))

    def test_exchange_rejects_entities_and_oversized_payload(self):
        for payload in [b'<!DOCTYPE a [<!ENTITY x "a">]><Tarih_Date/>', b"x" * 262145]:
            with self.subTest(size=len(payload)), self.assertRaises(ValueError):
                self.load("exchange").parse_rates(payload, today=date(2026, 11, 23))

    def test_exchange_rejects_duplicate_currency_before_writing(self):
        payload = self.xml().replace(b"</Tarih_Date>", self.xml().split(b">", 1)[1])
        with self.assertRaises(ValueError):
            self.load("exchange").parse_rates(payload, today=date(2026, 11, 23))

    def test_exchange_rejects_unrepresentable_native_float_values(self):
        for values in [{"buying": "1e99999"}, {"unit": "1e99999"}, {"buying": "0.00000000001"}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.load("exchange").parse_rates(self.xml(**values), today=date(2026, 11, 23))

    def test_exchange_rounds_to_native_nine_digit_precision(self):
        result = self.load("exchange").parse_rates(
            self.xml(unit="3", buying="1", selling="2"), today=date(2026, 11, 23)
        )
        self.assertEqual(result[0]["exchange_rate"], Decimal("0.333333333"))
        self.assertEqual(result[1]["exchange_rate"], Decimal("0.666666667"))

    def test_exchange_keeps_available_quote_without_fabricating_the_other(self):
        for buying, selling, flag in [("35.50", "", "for_buying"), ("", "35.70", "for_selling")]:
            with self.subTest(flag=flag):
                rates = self.load("exchange").parse_rates(
                    self.xml(code="XDR", buying=buying, selling=selling), today=date(2026, 11, 23)
                )
                self.assertEqual(len(rates), 1)
                self.assertEqual(rates[0][flag], 1)

    def test_exchange_rejects_currency_without_any_quote(self):
        with self.assertRaises(ValueError):
            self.load("exchange").parse_rates(self.xml(buying="", selling=""), today=date(2026, 11, 23))


if __name__ == "__main__":
    unittest.main()
