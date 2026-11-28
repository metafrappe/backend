"""Run with bench run-tests only on a disposable site, after installing the app."""

import frappe
from frappe.model import get_permitted_fields
from frappe.tests import IntegrationTestCase
from frappe.utils import fmt_money


class TestTurkeyInstallation(IntegrationTestCase):
    def test_identity_field_is_readable_and_writable_only_by_approved_roles(self):
        from tr_localization.install import install_address_fields

        install_address_fields()
        install_address_fields()
        for role in ("Accounts Manager", "System Manager", "Sales User"):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": f"trl-{role.lower().replace(' ', '-')}@example.test",
                    "first_name": "TRL Test",
                    "enabled": 1,
                    "send_welcome_email": 0,
                    "roles": [{"role": role}],
                }
            ).insert()
            for permission_type in ("read", "write"):
                with self.subTest(role=role, permission_type=permission_type):
                    fields = get_permitted_fields("Address", user=user.name, permission_type=permission_type)
                    self.assertEqual("custom_trl_identity_number" in fields, role != "Sales User")
                    levels = frappe.get_meta("Address").get_permlevel_access(permission_type, user=user.name)
                    self.assertEqual(1 in levels, role != "Sales User")

    def test_native_company_creates_chart_and_taxes(self):
        company = frappe.get_doc(
            {
                "doctype": "Company",
                "company_name": "_Test TRL Company",
                "abbr": "TRLTEST",
                "country": "Türkiye",
                "default_currency": "TRY",
                "chart_of_accounts": "Turkey - Chart of Accounts",
            }
        )
        company.insert()
        self.assertEqual(company.chart_of_accounts, "Turkey - Chart of Accounts")
        for number in ("100.01", "191.01.04", "391.01.04"):
            self.assertTrue(frappe.db.exists("Account", {"company": company.name, "account_number": number}))
        for kind in (
            "Sales Taxes and Charges Template",
            "Purchase Taxes and Charges Template",
            "Item Tax Template",
        ):
            self.assertEqual(frappe.db.count(kind, {"company": company.name}), 3)
        company.save()
        self.assertEqual(frappe.db.count("Sales Taxes and Charges Template", {"company": company.name}), 3)

    def test_try_native_formatter(self):
        self.assertEqual(fmt_money(1234.50, precision=2, currency="TRY"), "₺ 1.234,50")
        self.assertEqual(fmt_money(-1234.50, precision=2, currency="TRY"), "₺ -1.234,50")

    def test_address_data_is_used_by_native_document(self):
        frappe.get_doc(
            {
                "doctype": "TRL District",
                "province": "_Test Province",
                "district": "_Test District",
                "enabled": 1,
                "source_url": "https://example.test/catalogue",
                "source_date": "2026-11-20",
            }
        ).insert()
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": "_Test TRL Address",
                "address_type": "Billing",
                "address_line1": "Example Street",
                "country": "Türkiye",
                "state": "_Test Province",
                "city": "_Test City",
                "custom_trl_district": "_Test District",
            }
        )
        address.insert()
        address.custom_trl_district = "_Unknown District"
        with self.assertRaises(frappe.ValidationError):
            address.save()

    def test_platform_dependency_is_installed(self):
        self.assertIn("tr_localization", frappe.get_installed_apps())
        self.assertIn("erpnext", frappe.get_installed_apps())

    def test_district_pair_is_immutable(self):
        district = frappe.get_doc(
            {
                "doctype": "TRL District",
                "province": "_Test Fixed Province",
                "district": "_Test Fixed District",
                "source_url": "https://example.test/catalogue",
                "source_date": "2026-11-20",
            }
        ).insert()
        district.district = "_Test Changed District"
        with self.assertRaises(frappe.ValidationError):
            district.save()
