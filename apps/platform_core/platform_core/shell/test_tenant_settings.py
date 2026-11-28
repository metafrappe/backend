"""G-97 part 1 (AJA-2551): Tenant Settings and Tenant Branding single DocTypes.

Written before the implementation (D-2). Every permission check runs through
Frappe's real WSGI application (D-6) so cookie sessions, role checks and REST
endpoints match production behavior.
"""

import json
from urllib.parse import quote

import frappe
from frappe.tests import IntegrationTestCase
from frappe.tests.test_api import make_request
from frappe.utils import get_test_client
from frappe.utils.password import update_password

TENANT_SETTINGS = "Tenant Settings"
TENANT_BRANDING = "Tenant Branding"
META_API = "/api/method/platform_core.api.meta.get_doctype"
ACCESS_SET_PERM_API = "/api/method/platform_core.api.access.set_role_permission"

TENANT_ADMIN_ROLE = "Tenant Admin"
TENANT_ADMIN_ASSISTANT_ROLE = "Tenant Admin Assistant"
RESELLER_ADMIN_ROLE = "Reseller Admin"
RESELLER_ASSISTANT_ROLE = "Reseller Assistant"
PLAIN_ROLE = "TS Plain Test Role"

ADMIN_USER = "ts.tenant.admin@example.test"
ASSISTANT_USER = "ts.tenant.assistant@example.test"
RESELLER_ADMIN_USER = "ts.reseller.admin@example.test"
RESELLER_ASSISTANT_USER = "ts.reseller.assistant@example.test"
PLAIN_USER = "ts.plain.user@example.test"
SYSTEM_MANAGER_USER = "ts.system.manager@example.test"

TEST_USERS = (
	(ADMIN_USER, [TENANT_ADMIN_ROLE]),
	(ASSISTANT_USER, [TENANT_ADMIN_ASSISTANT_ROLE]),
	(RESELLER_ADMIN_USER, [RESELLER_ADMIN_ROLE]),
	(RESELLER_ASSISTANT_USER, [RESELLER_ASSISTANT_ROLE]),
	(PLAIN_USER, [PLAIN_ROLE]),
	(SYSTEM_MANAGER_USER, ["System Manager"]),
)

TEST_PASSWORD = "-".join(("Test", "Pass", "2551", "TenantSettings!"))
TEST_EMAIL_DOMAIN = "kiraci.example.test"
TEST_EMAIL_ACCOUNT_NAME = "TS Outgoing Test"
TEST_EMAIL_ID = "bildirim@kiraci.example.test"

WRITABLE_SETTINGS_FIELDS = frozenset(
	{
		"language",
		"time_zone",
		"date_format",
		"time_format",
		"number_format",
		"session_expiry",
	}
)
READ_ONLY_SETTINGS_FIELDS = frozenset({"email_domain", "email_account"})
BRANDING_DATA_FIELDS = frozenset({"logo", "primary_color", "accent_color"})
LAYOUT_FIELDTYPES = frozenset({"Section Break", "Column Break", "Tab Break"})


def _ensure_user(email: str, roles: list[str]) -> None:
	if frappe.db.exists("User", email):
		doc = frappe.get_doc("User", email)
		doc.set("roles", [{"role": role} for role in roles])
		doc.save()
	else:
		frappe.get_doc(
			doctype="User",
			email=email,
			first_name=email.split("@")[0],
			send_welcome_email=0,
			roles=[{"role": role} for role in roles],
		).insert()
	update_password(email, TEST_PASSWORD)


class TestTenantSettingsAndBranding(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.site = frappe.local.site
		frappe.set_user("Administrator")
		cls.saved_system_settings = {
			field: frappe.db.get_single_value("System Settings", field)
			for field in (
				*WRITABLE_SETTINGS_FIELDS,
				"disable_system_update_notification",
				"enable_mcp",
				"allow_error_traceback",
			)
		}
		cls.saved_defaults = {
			field: frappe.db.get_default(field) for field in (*WRITABLE_SETTINGS_FIELDS, "lang")
		}
		if not frappe.db.exists("Role", PLAIN_ROLE):
			frappe.get_doc(doctype="Role", role_name=PLAIN_ROLE, desk_access=0).insert()
		for email, roles in TEST_USERS:
			_ensure_user(email, roles)
		frappe.db.commit()  # nosemgrep: frappe-test-commit

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		cls._restore_system_settings()
		cls._clean_email_records()
		for email, _roles in TEST_USERS:
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True)
		if frappe.db.exists("Role", PLAIN_ROLE):
			frappe.delete_doc("Role", PLAIN_ROLE, force=True)
		frappe.clear_cache()
		frappe.db.commit()  # nosemgrep: frappe-test-commit
		super().tearDownClass()

	@classmethod
	def _restore_system_settings(cls):
		frappe.db.set_single_value("System Settings", cls.saved_system_settings)
		for key, value in cls.saved_defaults.items():
			if value is None:
				frappe.db.delete("DefaultValue", {"defkey": key, "parent": "__default"})
			else:
				frappe.db.set_default(key, value)
		from frappe.core.doctype.system_settings.system_settings import clear_system_settings_cache

		clear_system_settings_cache()

	@staticmethod
	def _clean_email_records():
		if frappe.db.exists("Email Account", TEST_EMAIL_ACCOUNT_NAME):
			frappe.delete_doc("Email Account", TEST_EMAIL_ACCOUNT_NAME, force=True)
		if frappe.db.exists("Email Domain", TEST_EMAIL_DOMAIN):
			frappe.delete_doc("Email Domain", TEST_EMAIL_DOMAIN, force=True)

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self._restore_system_settings()
		self._clean_email_records()
		frappe.db.commit()  # nosemgrep: frappe-test-commit

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		self._restore_system_settings()
		self._clean_email_records()
		frappe.clear_cache()
		frappe.db.commit()  # nosemgrep: frappe-test-commit
		super().tearDown()

	# --- HTTP helpers ---

	def send(self, client, method: str, path: str, *, body=None, query=None):
		headers = {"Accept": "application/json"}
		kwargs = {"path": path, "method": method, "headers": headers}
		if body is not None:
			headers["Content-Type"] = "application/json"
			kwargs["data"] = json.dumps(body)
		if query:
			kwargs["query_string"] = query
		frappe.db.commit()  # nosemgrep: frappe-request-commit
		try:
			return make_request(client.open, args=(), kwargs=kwargs, site=self.site)
		finally:
			frappe.db.rollback()

	def login(self, user: str = ADMIN_USER):
		client = get_test_client(use_cookies=True)
		response = self.send(client, "POST", "/api/method/login", body={"usr": user, "pwd": TEST_PASSWORD})
		self.assertEqual(response.status_code, 200, user)
		return client

	def resource(self, client, method: str, doctype: str, name: str | None = None, body=None, query=None):
		path = "/api/resource/" + quote(doctype)
		if name is not None:
			path += "/" + quote(name)
		return self.send(client, method, path, body=body, query=query)

	def meta_get(self, client, doctype: str):
		return self.send(client, "GET", META_API, query={"doctype": doctype})

	def _insert_outgoing_email(self):
		# Insert directly via SQL-safe ORM with validation flags bypassed only for SMTP network checks.
		domain = frappe.get_doc(
			doctype="Email Domain",
			domain_name=TEST_EMAIL_DOMAIN,
			email_server="imap.example.test",
			smtp_server="smtp.example.test",
		)
		domain.flags.in_test = True
		domain.db_insert()
		account = frappe.get_doc(
			doctype="Email Account",
			email_account_name=TEST_EMAIL_ACCOUNT_NAME,
			email_id=TEST_EMAIL_ID,
			domain=TEST_EMAIL_DOMAIN,
			enable_outgoing=1,
			default_outgoing=1,
			smtp_server="smtp.example.test",
		)
		account.db_insert()
		frappe.db.commit()  # nosemgrep: frappe-test-commit

	# --- AC 1: Tenant Settings schema ---

	def test_tenant_settings_is_single_with_exact_writable_and_readonly_fields(self):
		self.assertTrue(frappe.db.exists("DocType", TENANT_SETTINGS))
		meta = frappe.get_meta(TENANT_SETTINGS)
		self.assertEqual(meta.issingle, 1)

		data_fields = [f for f in meta.fields if f.fieldtype not in LAYOUT_FIELDTYPES]
		writable = {f.fieldname for f in data_fields if not f.read_only}
		read_only = {f.fieldname for f in data_fields if f.read_only}
		self.assertEqual(writable, WRITABLE_SETTINGS_FIELDS)
		self.assertEqual(read_only, READ_ONLY_SETTINGS_FIELDS)

		client = self.login(ADMIN_USER)
		meta_resp = self.meta_get(client, TENANT_SETTINGS)
		self.assertEqual(meta_resp.status_code, 200)
		schema_fields = {f["fieldname"]: f for f in meta_resp.json["message"]["schema"]["fields"]}
		for name in WRITABLE_SETTINGS_FIELDS:
			self.assertIn(name, schema_fields, name)
			self.assertFalse(schema_fields[name]["read_only"], name)
		for name in READ_ONLY_SETTINGS_FIELDS:
			self.assertIn(name, schema_fields, name)
			self.assertTrue(schema_fields[name]["read_only"], name)

		read_resp = self.resource(client, "GET", TENANT_SETTINGS, TENANT_SETTINGS)
		self.assertEqual(read_resp.status_code, 200)
		self.assertTrue(read_resp.json["data"].get("modified"))

	# --- AC 2: Tenant Settings writes through to System Settings ---

	def test_tenant_settings_update_syncs_allowed_fields_to_system_settings(self):
		client = self.login(ADMIN_USER)
		current = self.resource(client, "GET", TENANT_SETTINGS, TENANT_SETTINGS)
		self.assertEqual(current.status_code, 200)
		modified = current.json["data"]["modified"]

		updates = {
			"language": "en-GB",
			"time_zone": "Europe/London",
			"date_format": "dd/mm/yyyy",
			"time_format": "HH:mm:ss",
			"number_format": "#,###.##",
			"session_expiry": "04:00",
			"modified": modified,
		}
		response = self.resource(client, "PUT", TENANT_SETTINGS, TENANT_SETTINGS, body=updates)
		self.assertEqual(response.status_code, 200)

		for field in WRITABLE_SETTINGS_FIELDS:
			with self.subTest(field=field):
				self.assertEqual(frappe.db.get_single_value("System Settings", field), updates[field])
				self.assertEqual(frappe.get_system_settings(field), updates[field])
				self.assertEqual(frappe.db.get_default(field), updates[field])
		self.assertEqual(frappe.db.get_default("lang"), "en-GB")

	def test_tenant_settings_cannot_smuggle_unrelated_system_settings_fields(self):
		client = self.login(ADMIN_USER)
		current = self.resource(client, "GET", TENANT_SETTINGS, TENANT_SETTINGS)
		self.assertEqual(current.status_code, 200)
		before_mcp = frappe.db.get_single_value("System Settings", "enable_mcp")
		before_tb = frappe.db.get_single_value("System Settings", "allow_error_traceback")

		response = self.resource(
			client,
			"PUT",
			TENANT_SETTINGS,
			TENANT_SETTINGS,
			body={
				"session_expiry": "04:00",
				"enable_mcp": 1,
				"allow_error_traceback": 1,
				"modified": current.json["data"]["modified"],
			},
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(frappe.db.get_single_value("System Settings", "enable_mcp"), before_mcp)
		self.assertEqual(frappe.db.get_single_value("System Settings", "allow_error_traceback"), before_tb)

	def test_tenant_settings_rejects_invalid_session_expiry_and_locale_values(self):
		client = self.login(ADMIN_USER)
		before_expiry = frappe.db.get_single_value("System Settings", "session_expiry")
		before_tz = frappe.db.get_single_value("System Settings", "time_zone")

		for bad_expiry in ("00:00", "0:00", "abc", "-1:00", "01:60", "04:00:00", "999:00", "04:00; x"):
			current = self.resource(client, "GET", TENANT_SETTINGS, TENANT_SETTINGS)
			with self.subTest(session_expiry=bad_expiry):
				resp = self.resource(
					client,
					"PUT",
					TENANT_SETTINGS,
					TENANT_SETTINGS,
					body={"session_expiry": bad_expiry, "modified": current.json["data"]["modified"]},
				)
				self.assertEqual(resp.status_code, 417)
		self.assertEqual(frappe.db.get_single_value("System Settings", "session_expiry"), before_expiry)

		for bad_tz in ("Mars/Olympus", "../etc/passwd", "Europe/Istanbul; x"):
			current = self.resource(client, "GET", TENANT_SETTINGS, TENANT_SETTINGS)
			with self.subTest(time_zone=bad_tz):
				resp = self.resource(
					client,
					"PUT",
					TENANT_SETTINGS,
					TENANT_SETTINGS,
					body={"time_zone": bad_tz, "modified": current.json["data"]["modified"]},
				)
				self.assertEqual(resp.status_code, 417)
		self.assertEqual(frappe.db.get_single_value("System Settings", "time_zone"), before_tz)

	# --- AC 3: Tenant Admin cannot access System Settings directly ---

	def test_tenant_admin_cannot_read_or_write_system_settings_directly(self):
		client = self.login(ADMIN_USER)
		before = frappe.db.get_single_value("System Settings", "session_expiry")

		read_resp = self.resource(client, "GET", "System Settings", "System Settings")
		write_resp = self.resource(
			client, "PUT", "System Settings", "System Settings", body={"session_expiry": "05:00"}
		)
		meta_resp = self.meta_get(client, "System Settings")

		self.assertEqual(read_resp.status_code, 403)
		self.assertEqual(write_resp.status_code, 403)
		self.assertEqual(meta_resp.status_code, 403)
		self.assertEqual(frappe.db.get_single_value("System Settings", "session_expiry"), before)

	# --- AC 4: email_domain and email_account are read-only ---

	def test_tenant_admin_sees_email_fields_and_cannot_modify_them(self):
		self._insert_outgoing_email()
		client = self.login(ADMIN_USER)

		read_resp = self.resource(client, "GET", TENANT_SETTINGS, TENANT_SETTINGS)
		self.assertEqual(read_resp.status_code, 200)
		data = read_resp.json["data"]
		self.assertEqual(data.get("email_domain"), TEST_EMAIL_DOMAIN)
		self.assertEqual(data.get("email_account"), TEST_EMAIL_ID)

		for payload in (
			{"email_domain": "saldirgan.example.test", "modified": data["modified"]},
			{"email_account": "saldirgan@example.test", "modified": data["modified"]},
			{"email_domain": "", "modified": data["modified"]},
		):
			with self.subTest(payload=payload):
				resp = self.resource(client, "PUT", TENANT_SETTINGS, TENANT_SETTINGS, body=payload)
				self.assertEqual(resp.status_code, 403)

		after = self.resource(client, "GET", TENANT_SETTINGS, TENANT_SETTINGS)
		self.assertEqual(after.status_code, 200)
		self.assertEqual(after.json["data"].get("email_domain"), TEST_EMAIL_DOMAIN)
		self.assertEqual(after.json["data"].get("email_account"), TEST_EMAIL_ID)

		# Updating a writable field while leaving email fields unchanged still succeeds.
		ok = self.resource(
			client,
			"PUT",
			TENANT_SETTINGS,
			TENANT_SETTINGS,
			body={"session_expiry": "04:00", "modified": after.json["data"]["modified"]},
		)
		self.assertEqual(ok.status_code, 200)
		self.assertEqual(ok.json["data"].get("email_domain"), TEST_EMAIL_DOMAIN)
		self.assertEqual(ok.json["data"].get("email_account"), TEST_EMAIL_ID)

	# --- AC 5 & AC 6: Tenant Branding schema, color validation and logo validation ---

	def test_tenant_branding_is_single_with_logo_and_color_fields(self):
		self.assertTrue(frappe.db.exists("DocType", TENANT_BRANDING))
		meta = frappe.get_meta(TENANT_BRANDING)
		self.assertEqual(meta.issingle, 1)

		data_fields = {f.fieldname: f.fieldtype for f in meta.fields if f.fieldtype not in LAYOUT_FIELDTYPES}
		self.assertEqual(
			data_fields,
			{
				"logo": "Attach Image",
				"primary_color": "Color",
				"accent_color": "Color",
			},
		)

		client = self.login(ADMIN_USER)
		meta_resp = self.meta_get(client, TENANT_BRANDING)
		self.assertEqual(meta_resp.status_code, 200)

		read_resp = self.resource(client, "GET", TENANT_BRANDING, TENANT_BRANDING)
		self.assertEqual(read_resp.status_code, 200)
		self.assertTrue(read_resp.json["data"].get("modified"))

	def test_tenant_branding_accepts_valid_hex_colors_and_logo_and_rejects_invalid_values(self):
		client = self.login(ADMIN_USER)
		current = self.resource(client, "GET", TENANT_BRANDING, TENANT_BRANDING)
		self.assertEqual(current.status_code, 200)

		valid = self.resource(
			client,
			"PUT",
			TENANT_BRANDING,
			TENANT_BRANDING,
			body={
				"logo": "/files/tenant-logo.png",
				"primary_color": "#12ab34",
				"accent_color": "#B35C1E",
				"modified": current.json["data"]["modified"],
			},
		)
		self.assertEqual(valid.status_code, 200)
		self.assertEqual(frappe.db.get_single_value(TENANT_BRANDING, "primary_color"), "#12ab34")
		self.assertEqual(frappe.db.get_single_value(TENANT_BRANDING, "accent_color"), "#B35C1E")
		self.assertEqual(frappe.db.get_single_value(TENANT_BRANDING, "logo"), "/files/tenant-logo.png")

		invalid_colors = (
			"k\u0131rm\u0131z\u0131; x",
			"red",
			"rgb(18, 171, 52)",
			"#12ab34; background:url(javascript:alert(1))",
			"#12ab34\n",
			"#123",
			"#12345",
			"#1234567",
			"12ab34",
			"#gggggg",
		)
		for field in ("primary_color", "accent_color"):
			for bad_color in invalid_colors:
				latest = self.resource(client, "GET", TENANT_BRANDING, TENANT_BRANDING)
				with self.subTest(field=field, color=bad_color):
					resp = self.resource(
						client,
						"PUT",
						TENANT_BRANDING,
						TENANT_BRANDING,
						body={field: bad_color, "modified": latest.json["data"]["modified"]},
					)
					self.assertEqual(resp.status_code, 417)

		self.assertEqual(frappe.db.get_single_value(TENANT_BRANDING, "primary_color"), "#12ab34")
		self.assertEqual(frappe.db.get_single_value(TENANT_BRANDING, "accent_color"), "#B35C1E")

		invalid_logos = (
			"javascript:alert(1)",
			"data:image/png;base64,AAAA",
			"https://evil.example/logo.png",
			"//evil.example/logo.png",
			"/files/logo.svg",
			"/files/../secret.png",
			"/files/logo.png?x=1",
		)
		for bad_logo in invalid_logos:
			latest = self.resource(client, "GET", TENANT_BRANDING, TENANT_BRANDING)
			with self.subTest(logo=bad_logo):
				resp = self.resource(
					client,
					"PUT",
					TENANT_BRANDING,
					TENANT_BRANDING,
					body={"logo": bad_logo, "modified": latest.json["data"]["modified"]},
				)
				self.assertEqual(resp.status_code, 417)
		self.assertEqual(frappe.db.get_single_value(TENANT_BRANDING, "logo"), "/files/tenant-logo.png")

		# Optional accent_color and logo may be cleared.
		latest = self.resource(client, "GET", TENANT_BRANDING, TENANT_BRANDING)
		cleared = self.resource(
			client,
			"PUT",
			TENANT_BRANDING,
			TENANT_BRANDING,
			body={"logo": "", "accent_color": "", "modified": latest.json["data"]["modified"]},
		)
		self.assertEqual(cleared.status_code, 200)

	# --- AC 7: Only Tenant Admin reads and writes both DocTypes ---

	def test_unauthorized_users_and_guest_receive_403_on_both_doctypes(self):
		guest = get_test_client(use_cookies=True)
		for doctype in (TENANT_SETTINGS, TENANT_BRANDING):
			with self.subTest(user="Guest", doctype=doctype):
				self.assertEqual(self.meta_get(guest, doctype).status_code, 403)
				self.assertEqual(self.resource(guest, "GET", doctype, doctype).status_code, 403)
				self.assertEqual(
					self.resource(
						guest, "PUT", doctype, doctype, body={"primary_color": "#12ab34"}
					).status_code,
					403,
				)

		for user in (
			PLAIN_USER,
			ASSISTANT_USER,
			RESELLER_ADMIN_USER,
			RESELLER_ASSISTANT_USER,
			SYSTEM_MANAGER_USER,
		):
			client = self.login(user)
			for doctype in (TENANT_SETTINGS, TENANT_BRANDING):
				with self.subTest(user=user, doctype=doctype):
					self.assertEqual(self.meta_get(client, doctype).status_code, 403)
					self.assertEqual(self.resource(client, "GET", doctype, doctype).status_code, 403)
					self.assertEqual(
						self.resource(
							client, "PUT", doctype, doctype, body={"primary_color": "#12ab34"}
						).status_code,
						403,
					)

	def test_tenant_admin_cannot_grant_permissions_on_settings_or_branding_to_other_roles(self):
		client = self.login(ADMIN_USER)
		for doctype in (TENANT_SETTINGS, TENANT_BRANDING):
			with self.subTest(doctype=doctype):
				resp = self.send(
					client,
					"POST",
					ACCESS_SET_PERM_API,
					body={"doctype": doctype, "role": PLAIN_ROLE, "permissions": {"read": 1}},
				)
				self.assertEqual(resp.status_code, 403)
