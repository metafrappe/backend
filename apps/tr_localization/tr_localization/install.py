"""Idempotent installation through native Frappe document operations."""

import frappe
from frappe import _


def configure_currency() -> None:
    currency = frappe.get_doc("Currency", "TRY")
    currency.symbol = "₺"
    currency.symbol_on_right = 0
    currency.number_format = "#.###,##"
    currency.fraction = "Kuruş"
    currency.fraction_units = 100
    currency.smallest_currency_fraction_value = 0.01
    # platform_core.config.turkey_setup (G-41) enables TRY and owns the system number format.
    currency.save()


def install_address_fields() -> None:
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    install_identity_permissions()
    create_custom_fields(
        {
            "Address": [
                {
                    "fieldname": "custom_trl_district",
                    "label": "District",
                    "fieldtype": "Data",
                    "insert_after": "state",
                    "description": "District in the installed Turkish province catalogue.",
                },
                {
                    "fieldname": "custom_trl_tax_office",
                    "label": "Tax Office",
                    "fieldtype": "Data",
                    "insert_after": "custom_trl_district",
                    "description": "Turkish tax office for this address.",
                },
                {
                    "fieldname": "custom_trl_tax_id",
                    "label": "Tax Identification Number",
                    "fieldtype": "Data",
                    "insert_after": "custom_trl_tax_office",
                    "description": "Ten ASCII digits. Not an identity verification.",
                },
                {
                    "fieldname": "custom_trl_identity_number",
                    "label": "Identity Number",
                    "fieldtype": "Data",
                    "insert_after": "custom_trl_tax_id",
                    "description": "Optional eleven ASCII digits. Not an identity verification.",
                    "permlevel": 1,
                },
            ]
        }
    )


def install_identity_permissions() -> None:
    """Reserve Address level one for the approved roles without replacing other permissions."""
    from frappe.permissions import add_permission

    roles = ("Accounts Manager", "System Manager")
    meta = frappe.get_meta("Address")
    if any(f.permlevel == 1 and f.fieldname != "custom_trl_identity_number" for f in meta.fields):
        frappe.throw(_("Address permission level one is already used by another field."))
    permissions = meta.permissions
    if any(p.permlevel == 1 and p.role not in roles and (p.read or p.write) for p in permissions):
        frappe.throw(_("Address permission level one is already granted to another role."))
    for role in roles:
        # Frappe requires the same role at level zero before allowing level one.
        for level in (0, 1):
            if not any(p.role == role and p.permlevel == level and not p.if_owner for p in permissions):
                add_permission("Address", role, permlevel=level)
            permission = frappe.get_doc(
                "Custom DocPerm", {"parent": "Address", "role": role, "permlevel": level, "if_owner": 0}
            )
            if not permission.read or not permission.write:
                permission.read = 1
                permission.write = 1
                permission.save()


def after_migrate() -> None:
    """Apply the field permissions and currency correction to existing installations."""
    configure_currency()
    install_address_fields()


def after_install() -> None:
    after_migrate()
    if not frappe.db.exists("Tax Category", "TRL Exempt"):
        frappe.get_doc({"doctype": "Tax Category", "title": "TRL Exempt"}).insert()
    # Installation is an administrator operation. No caller-selected company is queried.
    from tr_localization.company import install_tax_templates

    for company in frappe.get_all("Company", filters={"country": "Türkiye"}, pluck="name"):
        install_tax_templates(frappe.get_doc("Company", company))
