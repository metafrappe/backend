app_name = "tr_localization"
app_title = "Turkey Localization"
app_publisher = "Platform"
app_description = "Turkey accounting and address integration for ERPNext"
app_email = "noreply@example.test"
app_license = "MIT"
required_apps = ["erpnext"]

after_install = "tr_localization.install.after_install"
after_migrate = "tr_localization.install.after_migrate"

doc_events = {
    "Company": {
        "on_update": "tr_localization.company.install_tax_templates",
    },
    "Address": {"validate": "tr_localization.address.validate_address"},
}

user_data_fields = [
    {
        "doctype": "Address",
        "filter_by": "email_id",
        "redact_fields": [
            "custom_trl_tax_id",
            "custom_trl_identity_number",
            "custom_trl_tax_office",
            "custom_trl_district",
        ],
    }
]
