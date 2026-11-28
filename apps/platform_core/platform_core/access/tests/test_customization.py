"""G-97: the “Tenant Admin” role customizes its own site (AJA-2533). Written before the code (D-2).

Decision: AJA-2516, document “karar”. The holder adds and changes its own custom fields. The
holder changes only the label and the hidden flag of a field through the customization endpoints.
The holder changes only the hidden flag and the order of a shared workspace.

A “Property Setter” record also sets the permission level of a field. hrms_tr keeps
`Employee.date_of_birth` at level 1. Level 0 would open personal data to every employee. So the
type gets no general permission and every other path is closed.
"""

import json
from unittest.mock import patch
from urllib.parse import quote

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.tests import IntegrationTestCase
from frappe.tests.test_api import make_request
from frappe.utils import get_test_client
from frappe.utils.password import update_password

from platform_core.access import customization, tenant_admin
from platform_core.access.tests.base import PASSWORD

API = "/api/method/platform_core.api.customization."
HOLDER = "cz.yonetici@example.test"
ASSISTANT = "cz.yardimci@example.test"
ASSISTANT_ROLE = "Tenant Admin Assistant"
# A business type of ERPNext. Its only own field is required.
TARGET = "Sales Partner Type"
TARGET_REQUIRED = "sales_partner_type"
# hrms_tr sets the level of this field to 1 (`04_property_setter.json`). The test site has no
# hrms_tr, so the setup writes the same record as the application would.
PERSONAL_TYPE = "Employee"
PERSONAL_FIELD = "date_of_birth"
PERSONAL_SETTER = f"{PERSONAL_TYPE}-{PERSONAL_FIELD}-permlevel"
WORKSPACE = "CZ Ortak Alan"
WORKSPACE_PRIVATE = "CZ Ozel Alan"
FIELD_PREFIX = "custom_cz_"
ENDPOINTS = ("list_field_properties", "set_field_property", "remove_field_property")


def _user(email: str, roles: list[str]) -> None:
	if frappe.db.exists("User", email):
		doc = frappe.get_doc("User", email)
		doc.set("roles", [{"role": role} for role in roles])
		doc.save(ignore_permissions=True)
	else:
		frappe.get_doc(
			doctype="User",
			email=email,
			first_name=email.split("@")[0],
			send_welcome_email=0,
			roles=[{"role": role} for role in roles],
		).insert(ignore_permissions=True)
	update_password(email, PASSWORD)


def _workspace(name: str, public: int) -> None:
	if frappe.db.exists("Workspace", name):
		return
	frappe.get_doc(
		doctype="Workspace",
		label=name,
		title=name,
		public=public,
		for_user="" if public else "Administrator",
		module="Setup" if public else None,
		content="[]",
		sequence_id=1,
	).insert(ignore_permissions=True)


class TestCustomization(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.site = frappe.local.site
		frappe.set_user("Administrator")
		cls.clean()
		tenant_admin.ensure_permissions()
		if not frappe.db.exists("Role", ASSISTANT_ROLE):
			frappe.get_doc(doctype="Role", role_name=ASSISTANT_ROLE, desk_access=0).insert()
		_user(HOLDER, [tenant_admin.ROLE])
		_user(ASSISTANT, [ASSISTANT_ROLE])
		frappe.db.commit()  # nosemgrep: frappe-test-commit

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		cls.clean()
		frappe.db.delete("Property Setter", {"name": PERSONAL_SETTER})
		frappe.db.commit()  # nosemgrep: frappe-test-commit
		super().tearDownClass()

	@staticmethod
	def clean():
		frappe.db.delete(
			"Property Setter",
			{"doc_type": ("in", [TARGET, PERSONAL_TYPE]), "property": ("in", ["label", "hidden"])},
		)
		for name in frappe.get_all(
			"Custom Field", filters={"dt": TARGET, "fieldname": ("like", FIELD_PREFIX + "%")}, pluck="name"
		):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
		frappe.db.delete("Workspace", {"name": ("in", [WORKSPACE, WORKSPACE_PRIVATE])})
		frappe.clear_cache()

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.clean()
		_workspace(WORKSPACE, 1)
		_workspace(WORKSPACE_PRIVATE, 0)
		# The record hrms_tr installs. Installation writes it as a system record.
		frappe.db.delete("Property Setter", {"name": PERSONAL_SETTER})
		make_property_setter(
			PERSONAL_TYPE, PERSONAL_FIELD, "permlevel", 1, "Int", validate_fields_for_doctype=False
		)
		frappe.db.commit()  # nosemgrep: frappe-test-commit

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.in_import = False
		frappe.db.rollback()
		self.clean()
		frappe.db.commit()  # nosemgrep: frappe-test-commit
		super().tearDown()

	# --- request helpers ---

	def send(self, client, method: str, path: str, *, body=None, query=None):
		headers = {"Accept": "application/json"}
		kwargs = {"path": path, "method": method, "headers": headers}
		if body is not None:
			headers["Content-Type"] = "application/json"
			kwargs["data"] = json.dumps(body)
		if query:
			kwargs["query_string"] = query
		# Committed on purpose: the request uses another connection.
		frappe.db.commit()  # nosemgrep: frappe-request-commit
		try:
			return make_request(client.open, args=(), kwargs=kwargs, site=self.site)
		finally:
			frappe.db.rollback()

	def login(self, user: str = HOLDER):
		client = get_test_client(use_cookies=True)
		response = self.send(client, "POST", "/api/method/login", body={"usr": user, "pwd": PASSWORD})
		self.assertEqual(response.status_code, 200)
		return client

	def resource(self, client, method: str, doctype: str, name: str | None = None, body=None):
		path = "/api/resource/" + quote(doctype)
		if name is not None:
			path += "/" + quote(name)
		return self.send(client, method, path, body=body)

	def call(self, client, endpoint: str, **params):
		if endpoint == "list_field_properties":
			return self.send(client, "GET", API + endpoint, query=params)
		return self.send(client, "POST", API + endpoint, body=params)

	def field_body(self, **values) -> dict:
		body = {"dt": TARGET, "label": "CZ Not", "fieldname": "cz_not", "fieldtype": "Data"}
		body.update(values)
		return body

	def setter_value(self, name: str = PERSONAL_SETTER):
		return frappe.db.get_value("Property Setter", name, "value")

	# --- wiring ---

	def test_role_gets_custom_field_and_workspace_permissions(self):
		self.assertEqual(tenant_admin.GRANTS["Custom Field"], ("read", "write", "create", "delete", "report"))
		self.assertEqual(tenant_admin.GRANTS["Workspace"], ("read", "write"))
		# No general permission on “Property Setter”: only the endpoints write it.
		self.assertNotIn("Property Setter", tenant_admin.GRANTS)

	def test_guards_are_bound_to_the_document_events(self):
		events = frappe.get_hooks("doc_events")
		field_guard = "platform_core.access.tenant_admin.guard_custom_field"
		for event in ("before_insert", "validate", "on_trash"):
			self.assertIn(field_guard, events["Custom Field"][event], event)
		workspace_guard = "platform_core.access.tenant_admin.guard_workspace"
		for event in ("validate", "on_trash"):
			self.assertIn(workspace_guard, events["Workspace"][event], event)
		setter_guard = "platform_core.access.customization.guard_property_setter"
		for event in ("before_insert", "validate", "on_trash"):
			self.assertIn(setter_guard, events["Property Setter"][event], event)

	def test_generic_ai_writes_are_closed(self):
		closed = frappe.get_hooks("ai_write_closed_doctypes")
		for doctype in ("Custom Field", "Property Setter", "Workspace"):
			self.assertIn(doctype, closed)

	def test_endpoints_are_on_the_website_user_list(self):
		allowed = frappe.get_hooks("website_user_allowed_methods")
		for endpoint in ENDPOINTS:
			self.assertIn("platform_core.api.customization." + endpoint, allowed)

	# --- acceptance 1: custom fields ---

	def test_holder_adds_changes_and_deletes_a_custom_field(self):
		client = self.login()
		response = self.resource(client, "POST", "Custom Field", body=self.field_body())
		self.assertEqual(response.status_code, 200, response.json)
		name = response.json["data"]["name"]
		self.assertTrue(frappe.db.get_value("Custom Field", name, "fieldname").startswith("custom_"))
		response = self.resource(client, "PUT", "Custom Field", name, body={"label": "CZ Yeni Not"})
		self.assertEqual(response.status_code, 200, response.json)
		response = self.resource(client, "DELETE", "Custom Field", name)
		self.assertIn(response.status_code, (200, 202), response.json)
		self.assertFalse(frappe.db.exists("Custom Field", name))

	# --- acceptance 2: closed types ---

	def test_no_custom_field_on_a_closed_type(self):
		client = self.login()
		for doctype in ("User", "Role", "System Settings"):
			with self.subTest(doctype=doctype):
				response = self.resource(client, "POST", "Custom Field", body=self.field_body(dt=doctype))
				self.assertEqual(response.status_code, 403, response.json)
				self.assertFalse(
					frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": "custom_cz_not"})
				)

	# --- acceptance 3: unsafe field settings ---

	def test_unsafe_field_settings_are_refused(self):
		client = self.login()
		cases = {
			"fetch_from": {"fetch_from": "sales_partner_type.name"},
			"depends_on": {"depends_on": "eval:1"},
			"mandatory_depends_on": {"mandatory_depends_on": "eval:1"},
			"read_only_depends_on": {"read_only_depends_on": "eval:1"},
			"permlevel": {"permlevel": 1},
			"password": {"fieldtype": "Password"},
			"code": {"fieldtype": "Code"},
			"html": {"fieldtype": "HTML"},
			"table": {"fieldtype": "Table", "options": "Has Role"},
			"dynamic link": {"fieldtype": "Dynamic Link", "options": "dt"},
			"attach": {"fieldtype": "Attach"},
			"link to a closed type": {"fieldtype": "Link", "options": "User"},
			"system generated": {"is_system_generated": 1},
		}
		for case, values in cases.items():
			with self.subTest(case=case):
				response = self.resource(client, "POST", "Custom Field", body=self.field_body(**values))
				self.assertEqual(response.status_code, 403, response.json)
				self.assertFalse(
					frappe.db.exists("Custom Field", {"dt": TARGET, "fieldname": "custom_cz_not"})
				)

	def test_link_to_a_business_type_is_allowed(self):
		client = self.login()
		body = self.field_body(fieldtype="Link", options=PERSONAL_TYPE)
		response = self.resource(client, "POST", "Custom Field", body=body)
		self.assertEqual(response.status_code, 200, response.json)

	def test_a_field_added_later_cannot_get_fetch_from(self):
		client = self.login()
		name = self.resource(client, "POST", "Custom Field", body=self.field_body()).json["data"]["name"]
		response = self.resource(
			client, "PUT", "Custom Field", name, body={"fetch_from": "sales_partner_type.name"}
		)
		self.assertEqual(response.status_code, 403, response.json)
		self.assertFalse(frappe.db.get_value("Custom Field", name, "fetch_from"))

	def test_application_field_is_not_changed_or_deleted(self):
		# A field an application installed is a system field (`is_system_generated`).
		doc = frappe.get_doc(
			doctype="Custom Field",
			dt=TARGET,
			fieldname="custom_cz_uygulama",
			label="CZ Uygulama",
			fieldtype="Data",
			is_system_generated=1,
		).insert(ignore_permissions=True)
		client = self.login()
		response = self.resource(client, "PUT", "Custom Field", doc.name, body={"label": "CZ Degisti"})
		self.assertEqual(response.status_code, 403, response.json)
		response = self.resource(client, "DELETE", "Custom Field", doc.name)
		self.assertEqual(response.status_code, 403, response.json)
		self.assertEqual(frappe.db.get_value("Custom Field", doc.name, "label"), "CZ Uygulama")

	# --- acceptance 4: the permission level of a personal field ---

	def test_personal_field_level_is_not_changed_or_deleted(self):
		client = self.login()
		# The endpoint changes only the label and the hidden flag.
		response = self.call(
			client,
			"set_field_property",
			doctype=PERSONAL_TYPE,
			fieldname=PERSONAL_FIELD,
			property="permlevel",
			value=0,
		)
		self.assertEqual(response.status_code, 403, response.json)
		response = self.call(
			client,
			"remove_field_property",
			doctype=PERSONAL_TYPE,
			fieldname=PERSONAL_FIELD,
			property="permlevel",
		)
		self.assertEqual(response.status_code, 403, response.json)
		# The general REST path is closed: no read, no change, no delete, no new record.
		self.assertEqual(self.resource(client, "GET", "Property Setter", PERSONAL_SETTER).status_code, 403)
		response = self.resource(client, "PUT", "Property Setter", PERSONAL_SETTER, body={"value": "0"})
		self.assertEqual(response.status_code, 403, response.json)
		response = self.resource(client, "DELETE", "Property Setter", PERSONAL_SETTER)
		self.assertEqual(response.status_code, 403, response.json)
		body = {
			"doctype_or_field": "DocField",
			"doc_type": PERSONAL_TYPE,
			"field_name": PERSONAL_FIELD,
			"property": "permlevel",
			"value": "0",
			"property_type": "Int",
		}
		response = self.resource(client, "POST", "Property Setter", body=body)
		self.assertEqual(response.status_code, 403, response.json)
		self.assertEqual(self.setter_value(), "1")

	def test_property_setter_guard_closes_paths_without_permission_checks(self):
		# A data import or a code path that skips permissions still meets the guard.
		frappe.set_user(HOLDER)
		frappe.flags.in_import = True
		doc = frappe.get_doc(
			doctype="Property Setter",
			doctype_or_field="DocField",
			doc_type=PERSONAL_TYPE,
			field_name=PERSONAL_FIELD,
			property="permlevel",
			value="0",
			property_type="Int",
		)
		with self.assertRaises(frappe.PermissionError):
			doc.insert(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("Property Setter", PERSONAL_SETTER, ignore_permissions=True, force=True)
		frappe.set_user("Administrator")
		self.assertEqual(self.setter_value(), "1")

	# --- acceptance 5: system fields get 403 ---

	def test_system_fields_get_403(self):
		client = self.login()
		cases = [
			# Frappe's own columns.
			(TARGET, "name", "label", "Ad"),
			(TARGET, "owner", "hidden", 1),
			(PERSONAL_TYPE, "naming_series", "label", "Seri"),
			# A required field of the type. Hidden, the record could not be saved.
			(TARGET, TARGET_REQUIRED, "hidden", 1),
			# A field above level 0 keeps its hidden flag.
			(PERSONAL_TYPE, PERSONAL_FIELD, "hidden", 1),
		]
		for doctype, fieldname, prop, value in cases:
			with self.subTest(field=f"{doctype}.{fieldname}.{prop}"):
				response = self.call(
					client,
					"set_field_property",
					doctype=doctype,
					fieldname=fieldname,
					property=prop,
					value=value,
				)
				self.assertEqual(response.status_code, 403, response.json)
				self.assertFalse(
					frappe.db.exists(
						"Property Setter", {"doc_type": doctype, "field_name": fieldname, "property": prop}
					)
				)

	def test_application_custom_field_is_a_system_field(self):
		frappe.get_doc(
			doctype="Custom Field",
			dt=TARGET,
			fieldname="custom_cz_sistem",
			label="CZ Sistem",
			fieldtype="Data",
			is_system_generated=1,
		).insert(ignore_permissions=True)
		client = self.login()
		response = self.call(
			client,
			"set_field_property",
			doctype=TARGET,
			fieldname="custom_cz_sistem",
			property="label",
			value="CZ",
		)
		self.assertEqual(response.status_code, 403, response.json)

	def test_application_record_is_not_changed(self):
		# A setter named in an application fixture file stays as the application wrote it.
		key = (TARGET, TARGET_REQUIRED, "label")
		client = self.login()
		with patch.object(customization, "fixture_keys", return_value=frozenset({key})):
			response = self.call(
				client,
				"set_field_property",
				doctype=TARGET,
				fieldname=TARGET_REQUIRED,
				property="label",
				value="CZ",
			)
			self.assertEqual(response.status_code, 403, response.json)
			response = self.call(
				client, "remove_field_property", doctype=TARGET, fieldname=TARGET_REQUIRED, property="label"
			)
			self.assertEqual(response.status_code, 403, response.json)

	def test_endpoint_refuses_other_properties_and_closed_types(self):
		client = self.login()
		for prop in ("permlevel", "read_only", "reqd", "options", "fetch_from"):
			with self.subTest(property=prop):
				response = self.call(
					client,
					"set_field_property",
					doctype=TARGET,
					fieldname=TARGET_REQUIRED,
					property=prop,
					value="1",
				)
				self.assertEqual(response.status_code, 403, response.json)
		response = self.call(
			client, "set_field_property", doctype="User", fieldname="first_name", property="label", value="Ad"
		)
		self.assertEqual(response.status_code, 403, response.json)
		response = self.call(client, "list_field_properties", doctype="User")
		self.assertEqual(response.status_code, 403, response.json)

	# --- the endpoints work for the holder ---

	def test_holder_sets_lists_and_removes_label_and_hidden(self):
		field = frappe.get_doc(
			doctype="Custom Field",
			dt=TARGET,
			fieldname="custom_cz_kiraci",
			label="CZ Kiraci",
			fieldtype="Data",
			is_system_generated=0,
		).insert(ignore_permissions=True)
		client = self.login()
		response = self.call(
			client,
			"set_field_property",
			doctype=TARGET,
			fieldname=TARGET_REQUIRED,
			property="label",
			value="CZ Tur",
		)
		self.assertEqual(response.status_code, 200, response.json)
		self.assertEqual(response.json["message"]["value"], "CZ Tur")
		response = self.call(
			client,
			"set_field_property",
			doctype=TARGET,
			fieldname=field.fieldname,
			property="hidden",
			value=1,
		)
		self.assertEqual(response.status_code, 200, response.json)
		# The endpoint writes every other value itself.
		name = frappe.db.get_value(
			"Property Setter", {"doc_type": TARGET, "field_name": field.fieldname, "property": "hidden"}
		)
		row = frappe.db.get_value(
			"Property Setter",
			name,
			["value", "property_type", "doctype_or_field", "is_system_generated"],
			as_dict=True,
		)
		self.assertEqual(
			(row.value, row.property_type, row.doctype_or_field, row.is_system_generated),
			("1", "Check", "DocField", 0),
		)

		response = self.call(client, "list_field_properties", doctype=TARGET)
		self.assertEqual(response.status_code, 200, response.json)
		listed = {
			(row["fieldname"], row["property"], row["value"])
			for row in response.json["message"]["properties"]
		}
		self.assertEqual(listed, {(TARGET_REQUIRED, "label", "CZ Tur"), (field.fieldname, "hidden", "1")})
		fields = {row["fieldname"]: row for row in response.json["message"]["fields"]}
		self.assertTrue(fields[TARGET_REQUIRED]["hidden_locked"])
		self.assertFalse(fields[field.fieldname]["system"])

		response = self.call(
			client, "remove_field_property", doctype=TARGET, fieldname=TARGET_REQUIRED, property="label"
		)
		self.assertEqual(response.status_code, 200, response.json)
		self.assertFalse(
			frappe.db.exists(
				"Property Setter", {"doc_type": TARGET, "field_name": TARGET_REQUIRED, "property": "label"}
			)
		)

	def test_list_does_not_show_other_properties(self):
		client = self.login()
		response = self.call(client, "list_field_properties", doctype=PERSONAL_TYPE)
		self.assertEqual(response.status_code, 200, response.json)
		self.assertNotIn("permlevel", {row["property"] for row in response.json["message"]["properties"]})

	# --- acceptance 6: the assistant role ---

	def test_assistant_is_refused_on_all_three_types(self):
		client = self.login(ASSISTANT)
		self.assertEqual(
			self.resource(client, "POST", "Custom Field", body=self.field_body()).status_code, 403
		)
		self.assertEqual(self.resource(client, "GET", "Custom Field").status_code, 403)
		self.assertEqual(
			self.resource(client, "PUT", "Workspace", WORKSPACE, body={"is_hidden": 1}).status_code, 403
		)
		self.assertEqual(self.resource(client, "GET", "Property Setter", PERSONAL_SETTER).status_code, 403)
		self.assertEqual(self.call(client, "list_field_properties", doctype=TARGET).status_code, 403)
		response = self.call(
			client,
			"set_field_property",
			doctype=TARGET,
			fieldname=TARGET_REQUIRED,
			property="label",
			value="CZ",
		)
		self.assertEqual(response.status_code, 403, response.json)
		response = self.call(
			client, "remove_field_property", doctype=TARGET, fieldname=TARGET_REQUIRED, property="label"
		)
		self.assertEqual(response.status_code, 403, response.json)
		self.assertEqual(frappe.db.get_value("Workspace", WORKSPACE, "is_hidden"), 0)

	# --- workspaces ---

	def test_holder_changes_only_hidden_and_order_of_a_shared_workspace(self):
		client = self.login()
		response = self.resource(
			client, "PUT", "Workspace", WORKSPACE, body={"is_hidden": 1, "sequence_id": 7}
		)
		self.assertEqual(response.status_code, 200, response.json)
		self.assertEqual(frappe.db.get_value("Workspace", WORKSPACE, ["is_hidden", "sequence_id"]), (1, 7.0))
		cases = {
			"title": {"title": "CZ Baska"},
			"content": {"content": '[{"type": "header"}]'},
			"links": {
				"links": [
					{"type": "Link", "label": "CZ", "link_type": "URL", "link_to": "https://example.test"}
				]
			},
			"roles": {"roles": [{"role": tenant_admin.ROLE}]},
			"public": {"public": 0},
		}
		for case, body in cases.items():
			with self.subTest(case=case):
				response = self.resource(client, "PUT", "Workspace", WORKSPACE, body=body)
				self.assertEqual(response.status_code, 403, response.json)
		self.assertEqual(frappe.db.get_value("Workspace", WORKSPACE, "title"), WORKSPACE)

	def test_holder_does_not_create_delete_or_change_a_private_workspace(self):
		client = self.login()
		self.assertEqual(self.resource(client, "DELETE", "Workspace", WORKSPACE).status_code, 403)
		self.assertTrue(frappe.db.exists("Workspace", WORKSPACE))
		body = {"label": "CZ Yeni", "title": "CZ Yeni", "public": 1, "module": "Setup", "content": "[]"}
		self.assertEqual(self.resource(client, "POST", "Workspace", body=body).status_code, 403)
		response = self.resource(client, "PUT", "Workspace", WORKSPACE_PRIVATE, body={"is_hidden": 1})
		self.assertEqual(response.status_code, 403, response.json)

	# --- acceptance 7: developer mode ---

	def test_workspace_write_is_refused_in_developer_mode(self):
		# In developer mode a standard page is written to the application folder,
		# which every tenant shares.
		frappe.set_user(HOLDER)
		doc = frappe.get_doc("Workspace", WORKSPACE)
		doc.is_hidden = 1
		with patch.dict(frappe.conf, {"developer_mode": 1}), self.assertRaises(frappe.PermissionError):
			doc.save()
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Workspace", WORKSPACE, "is_hidden"), 0)
