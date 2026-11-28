"""Press owns automatic app selection through its native marketplace relation."""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from test_localization import FrappeFixture

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "press_tr"))


class RegistrationTest(FrappeFixture):
    def setUp(self):
        super().setUp()
        sys.modules.pop("press_tr.localization", None)

    def test_registers_turkey_on_erpnext_marketplace_app(self):
        self.frappe.db.exists.return_value = True
        app = SimpleNamespace(localisation_apps=[], append=Mock(), save=Mock())
        self.frappe.get_doc.return_value = app
        register = importlib.import_module("press_tr.localization").register_localization
        self.assertTrue(register())
        self.frappe.get_doc.assert_called_once_with("Marketplace App", "erpnext")
        app.append.assert_called_once_with(
            "localisation_apps",
            {
                "country": "Türkiye",
                "marketplace_app": "tr_localization",
            },
        )
        app.save.assert_called_once_with()

    def test_registration_is_idempotent(self):
        self.frappe.db.exists.return_value = True
        app = SimpleNamespace(
            localisation_apps=[SimpleNamespace(country="Türkiye", marketplace_app="tr_localization")],
            append=Mock(),
            save=Mock(),
        )
        self.frappe.get_doc.return_value = app
        self.assertTrue(importlib.import_module("press_tr.localization").register_localization())
        app.append.assert_not_called()
        app.save.assert_not_called()

    def test_registration_waits_for_operator_marketplace_setup(self):
        self.frappe.db.exists.return_value = False
        self.assertFalse(importlib.import_module("press_tr.localization").register_localization())
        self.frappe.get_doc.assert_not_called()

    def test_registration_rejects_a_conflicting_country_mapping(self):
        self.frappe.db.exists.return_value = True
        self.frappe.get_doc.return_value = SimpleNamespace(
            localisation_apps=[SimpleNamespace(country="Türkiye", marketplace_app="other_app")]
        )
        with self.assertRaises(ValueError):
            importlib.import_module("press_tr.localization").register_localization()


class PressHookTest(FrappeFixture):
    def test_press_after_migrate_keeps_existing_hooks_and_adds_registration(self):
        source = (Path(__file__).resolve().parents[2] / "press_tr" / "press_tr" / "hooks.py").read_text()
        namespace = {}
        exec(compile(source, "hooks.py", "exec"), namespace)
        hooks = namespace["after_migrate"]
        self.assertIn("press_tr.press_identity.recovery.ensure_reviewer_role", hooks)
        self.assertIn("press_tr.localization.register_localization", hooks)
        self.assertEqual(source.count("after_migrate ="), 1)
