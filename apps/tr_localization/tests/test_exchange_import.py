"""The import contract preserves native records and checks permissions first."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_localization
from test_localization import FrappeFixture


class ExchangeImportTest(FrappeFixture):
    def test_import_denies_wrong_role_before_network_even_with_create_permission(self):
        self.frappe.session.user = "sales@example.test"
        self.frappe.only_for.side_effect = PermissionError
        api = self.load("api.exchange")
        with patch.object(api, "fetch_rates") as fetch, self.assertRaises(PermissionError):
            api.import_rates()
        self.frappe.only_for.assert_called_once_with(("System Manager", "Accounts Manager"))
        fetch.assert_not_called()
        self.frappe.get_doc.assert_not_called()

    def test_import_skips_missing_currencies_and_keeps_available_quotes(self):
        api = self.load("api.exchange")
        xml = test_localization.ExchangeContractTest.xml
        payload = xml(self).replace(
            b"</Tarih_Date>",
            xml(self, code="AZN").split(b">", 1)[1].replace(b"</Tarih_Date>", b"")
            + xml(self, code="XDR", selling="").split(b">", 1)[1],
        )
        rates = self.load("exchange").parse_rates(payload, today=date(2026, 11, 23))
        self.frappe.db.exists.side_effect = lambda kind, filters: kind == "Currency" and filters == "USD"
        with patch.object(api, "fetch_rates", return_value=rates):
            result = api.import_rates()
        self.assertEqual(
            result,
            {
                "date": "2026-11-20",
                "inserted": 2,
                "unchanged": 0,
                "skipped_currencies": ["AZN", "XDR"],
                "skipped_currency_count": 2,
            },
        )
        self.assertEqual(self.frappe.get_doc.call_count, 2)
        for call in self.frappe.get_doc.call_args_list:
            self.assertEqual(call.args[0]["doctype"], "Currency Exchange")
            self.assertEqual(call.args[0]["from_currency"], "USD")
        self.frappe.db.commit.assert_not_called()

    def test_import_reports_bulletin_when_all_currencies_are_missing(self):
        api = self.load("api.exchange")
        rates = self.load("exchange").parse_rates(
            test_localization.ExchangeContractTest.xml(self, code="XDR", selling=""), today=date(2026, 11, 23)
        )
        self.frappe.db.exists.return_value = False
        with patch.object(api, "fetch_rates", return_value=rates):
            result = api.import_rates()
        self.assertEqual(
            result,
            {
                "date": "2026-11-20",
                "inserted": 0,
                "unchanged": 0,
                "skipped_currencies": ["XDR"],
                "skipped_currency_count": 1,
            },
        )
        self.frappe.get_doc.assert_not_called()

    def test_import_denies_guest_before_network(self):
        self.frappe.session.user = "Guest"
        self.frappe.throw.side_effect = PermissionError
        api = self.load("api.exchange")
        with patch.object(api, "fetch_rates") as fetch, self.assertRaises(PermissionError):
            api.import_rates()
        fetch.assert_not_called()

    def test_import_denies_currency_write_permission_before_network(self):
        self.frappe.has_permission.return_value = False
        self.frappe.throw.side_effect = PermissionError
        api = self.load("api.exchange")
        with patch.object(api, "fetch_rates") as fetch, self.assertRaises(PermissionError):
            api.import_rates()
        fetch.assert_not_called()

    def test_import_uses_native_currency_exchange_records(self):
        api = self.load("api.exchange")
        rate = {
            "date": "2026-11-20",
            "from_currency": "USD",
            "to_currency": "TRY",
            "exchange_rate": Decimal("35.50"),
            "for_buying": 1,
            "for_selling": 0,
        }
        self.frappe.db.exists.side_effect = lambda doctype, filters: doctype == "Currency"
        row = Mock()
        self.frappe.get_doc.return_value = row
        with patch.object(api, "fetch_rates", return_value=[rate]):
            result = api.import_rates()
        self.assertEqual(
            result,
            {
                "date": "2026-11-20",
                "inserted": 1,
                "unchanged": 0,
                "skipped_currencies": [],
                "skipped_currency_count": 0,
            },
        )
        self.frappe.get_doc.assert_called_once_with({"doctype": "Currency Exchange", **rate})
        row.insert.assert_called_once_with()
        self.frappe.db.commit.assert_not_called()

    def test_import_preserves_existing_rate_and_rejects_conflict(self):
        api = self.load("api.exchange")
        rate = {
            "date": "2026-11-20",
            "from_currency": "USD",
            "to_currency": "TRY",
            "exchange_rate": Decimal("35.50"),
            "for_buying": 1,
            "for_selling": 0,
        }
        self.frappe.db.exists.return_value = True
        self.frappe.db.get_value.return_value = 35.50
        with patch.object(api, "fetch_rates", return_value=[rate]):
            self.assertEqual(api.import_rates()["unchanged"], 1)
        self.frappe.db.get_value.return_value = 99
        with patch.object(api, "fetch_rates", return_value=[rate]), self.assertRaises(ValueError):
            api.import_rates()
        self.frappe.get_doc.assert_not_called()

    def test_import_rejects_conflicting_combined_buying_selling_record(self):
        api = self.load("api.exchange")
        rate = {
            "date": "2026-11-20",
            "from_currency": "USD",
            "to_currency": "TRY",
            "exchange_rate": Decimal("35.50"),
            "for_buying": 1,
            "for_selling": 0,
        }
        self.frappe.db.exists.side_effect = lambda kind, filters: (
            kind == "Currency" or (filters.get("for_buying") == 1 and filters.get("for_selling") == 1)
        )
        self.frappe.db.get_value.return_value = 99
        with patch.object(api, "fetch_rates", return_value=[rate]), self.assertRaises(ValueError):
            api.import_rates()
        self.frappe.get_doc.assert_not_called()

    def test_fetch_uses_fixed_tls_url_without_redirects_and_with_timeout(self):
        api = self.load("api.exchange")
        response = Mock()
        response.status_code = 200
        response.iter_content.return_value = [
            b'<Tarih_Date Date="11/20/2026"><Currency CurrencyCode="USD">',
            b"<Unit>1</Unit><ForexBuying>35.50</ForexBuying><ForexSelling>35.70</ForexSelling></Currency></Tarih_Date>",
        ]
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        client = SimpleNamespace(get=Mock(return_value=response), RequestException=RuntimeError)
        with (
            patch.dict("sys.modules", {"requests": client}),
            patch.object(api, "bulletin_today", return_value=date(2026, 11, 23)),
        ):
            self.assertEqual(len(api.fetch_rates()), 2)
        client.get.assert_called_once_with(
            "https://www.tcmb.gov.tr/kurlar/today.xml", timeout=(3, 10), allow_redirects=False, stream=True
        )

    def test_fetch_rejects_redirect_and_large_response(self):
        api = self.load("api.exchange")
        for status, chunks in [(302, []), (200, [b"x" * 262145])]:
            response = Mock(status_code=status)
            response.iter_content.return_value = chunks
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            client = SimpleNamespace(get=Mock(return_value=response), RequestException=RuntimeError)
            with patch.dict("sys.modules", {"requests": client}), self.assertRaises(ValueError):
                api.fetch_rates()
