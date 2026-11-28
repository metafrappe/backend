"""Installation grants only the PO-approved identity-field roles."""

import re
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_localization import APP, Document, FrappeFixture


class AddressPermissionTest(FrappeFixture):
    def setUp(self):
        super().setUp()
        self.permissions = [
            Document(role="Sales User", permlevel=0, read=1, write=1, if_owner=0),
            Document(role="System Manager", permlevel=0, read=1, write=1, if_owner=0),
        ]
        self.frappe.get_meta = Mock(return_value=SimpleNamespace(permissions=self.permissions, fields=[]))
        self.fields = Mock()

        def add_permission(doctype, role, permlevel=0, ptype=None):
            self.assertEqual(doctype, "Address")
            if not any(
                p.role == role and p.permlevel == permlevel and not p.if_owner for p in self.permissions
            ):
                self.permissions.append(
                    Document(role=role, permlevel=permlevel, read=1, write=0, if_owner=0, save=Mock())
                )

        def get_doc(doctype, filters):
            self.assertEqual(doctype, "Custom DocPerm")
            self.assertEqual(filters["parent"], "Address")
            return next(
                p
                for p in self.permissions
                if p.role == filters["role"]
                and p.permlevel == filters["permlevel"]
                and p.if_owner == filters["if_owner"]
            )

        self.frappe.get_doc.side_effect = get_doc
        self.native = SimpleNamespace(add_permission=add_permission)
        self.patches = patch.dict(
            "sys.modules",
            {
                "frappe.permissions": self.native,
                "frappe.custom.doctype.custom_field.custom_field": SimpleNamespace(
                    create_custom_fields=self.fields
                ),
            },
        )
        self.patches.start()
        self.addCleanup(self.patches.stop)

    def test_install_grants_two_roles_and_keeps_sales_user_at_level_zero(self):
        module = self.load("install")
        module.install_address_fields()
        module.install_address_fields()
        identity = next(
            f
            for f in self.fields.call_args.args[0]["Address"]
            if f["fieldname"] == "custom_trl_identity_number"
        )
        self.assertEqual(identity["permlevel"], 1)
        granted = {(p.role, p.read, p.write) for p in self.permissions if p.permlevel == 1}
        self.assertEqual(granted, {("Accounts Manager", 1, 1), ("System Manager", 1, 1)})
        self.assertEqual(len([p for p in self.permissions if p.permlevel == 1]), 2)
        self.assertFalse(any(p.role == "Sales User" and p.permlevel == 1 for p in self.permissions))
        self.assertEqual(
            self.permissions[0], Document(role="Sales User", permlevel=0, read=1, write=1, if_owner=0)
        )
        self.assertTrue(all(call.args[0] == "Custom DocPerm" for call in self.frappe.get_doc.call_args_list))

    def test_owner_only_grant_is_preserved_while_unconditional_grant_is_added(self):
        owned = Document(role="Accounts Manager", permlevel=1, read=1, write=0, if_owner=1)
        self.permissions.append(owned)
        self.load("install").install_address_fields()
        self.assertEqual(owned.write, 0)
        self.assertTrue(
            any(
                p.role == "Accounts Manager" and p.permlevel == 1 and p.write == 1 and not p.if_owner
                for p in self.permissions
            )
        )

    def test_conflicting_level_one_grant_stops_before_creating_personal_field(self):
        self.permissions.append(Document(role="Sales User", permlevel=1, read=1, write=1, if_owner=0))
        original = [dict(p) for p in self.permissions]
        with self.assertRaises(ValueError):
            self.load("install").install_address_fields()
        self.fields.assert_not_called()
        self.assertEqual(self.permissions, original)

    def test_other_level_one_field_stops_before_granting_access(self):
        self.frappe.get_meta.return_value.fields = [Document(fieldname="custom_private_note", permlevel=1)]
        original = [dict(p) for p in self.permissions]
        with self.assertRaises(ValueError):
            self.load("install").install_address_fields()
        self.fields.assert_not_called()
        self.frappe.get_doc.assert_not_called()
        self.assertEqual(self.permissions, original)

    def test_migration_updates_existing_installations(self):
        module = self.load("install")
        hooks = self.load("hooks")
        self.assertEqual(hooks.after_migrate, "tr_localization.install.after_migrate")
        with (
            patch.object(module, "configure_currency") as currency,
            patch.object(module, "install_address_fields") as fields,
        ):
            module.after_migrate()
        currency.assert_called_once_with()
        fields.assert_called_once_with()

    def test_exempt_category_translation_is_exact(self):
        catalogue = (APP / "tr_localization/locale/tr.po").read_text()
        self.assertRegex(catalogue, re.compile(r'msgid "TRL Exempt"\s+msgstr "İstisna"'))
