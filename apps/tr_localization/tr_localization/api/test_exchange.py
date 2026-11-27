"""Authorization regression checks; real HTTP checks remain a separate site gate."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from tr_localization.api.exchange import import_rates


class ExchangeAuthorizationTest(unittest.TestCase):
    def test_import_rates_guest_denied(self):
        with (
            patch.object(frappe, "session", SimpleNamespace(user="Guest")),
            patch("tr_localization.api.exchange.fetch_rates") as fetch,
            self.assertRaises(frappe.PermissionError),
        ):
            import_rates()
        fetch.assert_not_called()

    def test_import_rates_foreign_data_denied(self):
        # No company/site parameter can select another tenant. Permission is checked
        # in the current Frappe site before fetching or writing shared currency data.
        with (
            patch.object(frappe, "session", SimpleNamespace(user="restricted@example.test")),
            patch.object(frappe, "only_for"),
            patch.object(frappe, "has_permission", return_value=False),
            patch("tr_localization.api.exchange.fetch_rates") as fetch,
            self.assertRaises(frappe.PermissionError),
        ):
            import_rates()
        fetch.assert_not_called()
