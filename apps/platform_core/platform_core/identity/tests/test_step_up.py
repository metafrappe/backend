"""Sensitive operations need a fresh and strong sign-in (G-163, item 2).

Expected behaviour comes from the G-163 technical design (AJA-403), the `x-sensitive-operations` list of
contracts/platform_core-identity.openapi.yaml and docs/contracts.md (D-1):
- every listed method calls the step-up check in its first statement, and the code list equals the contract,
- a session whose `auth_time` is older than the limit (300 seconds) gets 403 `reauthentication_required`,
- a session whose `acr` is lower than the required level gets the same answer,
- the answer carries a sign-in address with `prompt=login`, `max_age=0` and `acr_values`,
- requests with a token carry no session record and cannot call these methods,
- a fresh `admin` sign-in runs the method.
"""

import ast
import importlib
import inspect
import os
import textwrap
import time
from urllib.parse import parse_qs, urlparse

import frappe
import yaml
from frappe.tests.test_api import FrappeAPITestCase

from platform_core.identity import provider_setup, session_policy
from platform_core.identity.tests import helpers as h

APP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTRACT = os.path.join(APP, "..", "..", "..", "contracts", "platform_core-identity.openapi.yaml")
API_DIR = os.path.join(APP, "api")
ADMIN = "yonetici.ornek@example.test"
EMPLOYEE = "calisan.ornek@example.test"
METHOD = "platform_core.api.model.purge_usage"
METHOD_PATH = f"/api/method/{METHOD}"


def _contract_operations() -> list[dict]:
	with open(CONTRACT, encoding="utf-8") as handle:
		return yaml.safe_load(handle)["x-sensitive-operations"]["operations"]


def _is_step_up_call(node) -> bool:
	"""`step_up.require(...)` as an expression statement."""
	if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
		return False
	func = node.value.func
	return (
		isinstance(func, ast.Attribute)
		and func.attr == "require"
		and isinstance(func.value, ast.Name)
		and func.value.id == "step_up"
	)


def _first_statement(function) -> ast.stmt:
	tree = ast.parse(textwrap.dedent(inspect.getsource(inspect.unwrap(function))))
	body = tree.body[0].body
	if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
		body = body[1:]
	return body[0]


def _functions_calling_step_up() -> set[str]:
	found = set()
	for filename in sorted(os.listdir(API_DIR)):
		if not filename.endswith(".py") or filename.startswith("test_"):
			continue
		with open(os.path.join(API_DIR, filename), encoding="utf-8") as handle:
			tree = ast.parse(handle.read())
		for node in tree.body:
			if isinstance(node, ast.FunctionDef) and any(
				_is_step_up_call(statement) for statement in ast.walk(node) if isinstance(statement, ast.Expr)
			):
				found.add(f"platform_core.api.{filename[:-3]}.{node.name}")
	return found


class TestSensitiveOperationContract(FrappeAPITestCase):
	def test_contract_lists_method_level_and_age(self):
		operations = _contract_operations()
		self.assertTrue(operations)
		for operation in operations:
			self.assertEqual(sorted(operation), ["max_age_seconds", "method", "min_acr"], operation)
			# Review finding (AJA-405): end users approve their own AI proposals and have no strong key.
			# Approval needs a fresh sign-in at their own level; every other listed method needs `admin`.
			expected = (
				"employee" if operation["method"] == "platform_core.api.ai.approve_proposal" else "admin"
			)
			self.assertEqual(operation["min_acr"], expected, operation)
			self.assertEqual(operation["max_age_seconds"], 300, operation)

	def test_code_list_equals_contract_list(self):
		from platform_core.identity import step_up

		contract = {op["method"]: (op["min_acr"], op["max_age_seconds"]) for op in _contract_operations()}
		code = {method: (rule.min_acr, rule.max_age) for method, rule in step_up.SENSITIVE_OPERATIONS.items()}
		self.assertEqual(code, contract)
		self.assertEqual(step_up.DEFAULT_MAX_AGE, 300)

	def test_every_listed_method_calls_the_check_first(self):
		problems = []
		for operation in _contract_operations():
			module_name, _dot, name = operation["method"].rpartition(".")
			function = getattr(importlib.import_module(module_name), name)
			first = _first_statement(function)
			if not _is_step_up_call(first):
				problems.append(f"{operation['method']}: first statement is not step_up.require")
				continue
			args = first.value.args
			if not args or not isinstance(args[0], ast.Constant) or args[0].value != operation["method"]:
				problems.append(f"{operation['method']}: step_up.require names another method")
		self.assertEqual(problems, [])

	def test_no_unlisted_method_calls_the_check(self):
		listed = {op["method"] for op in _contract_operations()}
		self.assertEqual(_functions_calling_step_up(), listed)


class StepUpCase(FrappeAPITestCase):
	"""Shared setup: an administrator and a desk employee who sign in through Keycloak."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.settings = h.SiteSettings().__enter__()
		cls.addClassCleanup(cls.settings.__exit__, None, None, None)
		provider_setup.ensure_social_login_key()
		h.ensure_user(ADMIN, user_type="System User", roles=["System Manager"])
		role = h.ensure_role("Kimlik Test Employee", 1)
		h.ensure_user(EMPLOYEE, user_type="System User", roles=[role])
		h.refresh()
		cls.patcher = h.jwks_patch()
		cls.patcher.start()
		cls.addClassCleanup(cls.patcher.stop)

	@classmethod
	def tearDownClass(cls):
		h.clear_links(ADMIN, EMPLOYEE)
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		h.clear_links(ADMIN, EMPLOYEE)
		frappe.cache.delete_keys(session_policy.ACTIVITY_PREFIX)
		self.client = h.new_client()

	def _sign_in(self, user: str, subject: str, acr: str) -> None:
		response = h.login_with_keycloak(self.client, h.userinfo(subject, user, acr=acr))
		self.assertEqual(response.status_code, 302, response.data[:300])
		self.assertEqual(h.logged_user(self.client), user)

	def _set_session_values(self, **values) -> None:
		"""Changes the session record the client's cookie points at and drops the cached copy."""
		h.refresh()
		sid = self.client.get_cookie("sid").value
		sessions = frappe.qb.DocType("Sessions")
		raw = frappe.qb.from_(sessions).select(sessions.sessiondata).where(sessions.sid == sid).run()[0][0]
		data = frappe.parse_json(raw or "{}")
		data.update(values)
		frappe.qb.update(sessions).set(sessions.sessiondata, frappe.as_json(data, indent=None)).where(
			sessions.sid == sid
		).run()
		frappe.cache.hdel("session", sid)
		h.refresh()

	def _call(self, headers: dict | None = None):
		return h.request(
			self.client.post,
			METHOD_PATH,
			json={"dry_run": True},
			headers=headers if headers is not None else h.csrf_headers(self.client),
		)

	def _assert_reauthentication_required(self, response) -> dict:
		self.assertEqual(response.status_code, 403, response.data[:400])
		self.assertEqual(response.json.get("error"), "reauthentication_required", response.json)
		return response.json


class TestStepUp(StepUpCase):
	def test_stale_auth_time_gets_403_with_reauthentication_address(self):
		self._sign_in(ADMIN, "sub-admin", "admin")
		self._set_session_values(keycloak_auth_time=int(time.time()) - 301)
		body = self._assert_reauthentication_required(self._call())
		address = urlparse(body["reauthentication_url"])
		query = {k: v[0] for k, v in parse_qs(address.query).items()}
		self.assertEqual(query.get("prompt"), "login")
		self.assertEqual(query.get("max_age"), "0")
		self.assertEqual(query.get("acr_values"), "admin")

	def test_reauthentication_address_leads_to_a_forced_strong_sign_in(self):
		self._sign_in(ADMIN, "sub-admin", "admin")
		self._set_session_values(keycloak_auth_time=int(time.time()) - 301)
		body = self._assert_reauthentication_required(self._call())
		address = urlparse(body["reauthentication_url"])
		response = h.request(self.client.get, address.path, query_string=address.query)
		self.assertEqual(response.status_code, 302, response.data[:300])
		authorize = {k: v[0] for k, v in parse_qs(urlparse(response.headers["Location"]).query).items()}
		self.assertTrue(
			response.headers["Location"].startswith("http://identity.localhost:8660/realms/platform/")
		)
		self.assertEqual(authorize.get("prompt"), "login")
		self.assertEqual(authorize.get("max_age"), "0")
		self.assertEqual(authorize.get("acr_values"), "admin")

	def test_employee_acr_gets_403(self):
		self._sign_in(ADMIN, "sub-admin", "admin")
		self._set_session_values(keycloak_acr="employee")
		self._assert_reauthentication_required(self._call())

	def test_desk_employee_with_employee_acr_gets_403_before_any_permission_check(self):
		self._sign_in(EMPLOYEE, "sub-employee", "employee")
		self._assert_reauthentication_required(self._call())

	def test_session_without_acr_gets_403(self):
		self._sign_in(ADMIN, "sub-admin", "admin")
		self._set_session_values(keycloak_acr=None, keycloak_auth_time=None)
		self._assert_reauthentication_required(self._call())

	def test_fresh_admin_sign_in_runs_the_method(self):
		self._sign_in(ADMIN, "sub-admin", "admin")
		response = self._call()
		self.assertEqual(response.status_code, 200, response.data[:400])
		self.assertEqual(response.json["message"]["deleted"], 0)

	def test_token_request_cannot_call_the_method(self):
		user = frappe.get_doc("User", ADMIN)
		api_key = frappe.generate_hash(length=15)
		api_secret = frappe.generate_hash(length=15)
		user.api_key = api_key
		user.api_secret = api_secret
		user.save(ignore_permissions=True)
		h.refresh()
		client = h.new_client()
		response = h.request(
			client.post,
			METHOD_PATH,
			json={"dry_run": True},
			headers={"Authorization": f"token {api_key}:{api_secret}"},
		)
		self._assert_reauthentication_required(response)


class TestStepUpReview(StepUpCase):
	"""Findings of the independent review (AJA-405)."""

	def _forced_attempt(self, acr: str = "admin") -> dict:
		response = h.request(
			self.client.get,
			"/api/method/platform_core.api.auth.start_login",
			query_string={"prompt": "login", "max_age": "0", "acr_values": acr},
		)
		self.assertEqual(response.status_code, 302, response.data[:300])
		return {k: v[0] for k, v in parse_qs(urlparse(response.headers["Location"]).query).items()}

	def test_max_age_zero_attempt_refuses_an_old_sign_in_even_for_an_active_user(self):
		session_policy.mark_activity(None, ADMIN)
		query = self._forced_attempt()
		token = h.id_token(
			query, h.userinfo("sub-admin", ADMIN, acr="admin"), auth_time=int(time.time()) - 600
		)
		response = h.finish_login(self.client, query, token)
		self.assertEqual(response.status_code, 403, response.data[:300])
		self.assertEqual(h.session_count(ADMIN), 0)

	def test_restart_of_a_max_age_zero_attempt_keeps_max_age(self):
		# A System Manager re-authenticates for an approval (`acr_values=employee`). Keycloak answers with
		# `employee`, so the sign-in restarts with `admin`. The restart still needs a sign-in made now.
		query = self._forced_attempt("employee")
		response = h.finish_login(
			self.client, query, h.id_token(query, h.userinfo("sub-admin", ADMIN, acr="employee"))
		)
		self.assertEqual(response.status_code, 302, response.data[:300])
		restart = {k: v[0] for k, v in parse_qs(urlparse(response.headers["Location"]).query).items()}
		self.assertEqual(restart.get("acr_values"), "admin")
		self.assertEqual(restart.get("max_age"), "0")
		self.assertEqual(restart.get("prompt"), "login")
		self.assertEqual(h.session_count(ADMIN), 0)

	def test_desk_employee_with_a_fresh_employee_sign_in_passes_the_approval_check(self):
		self._sign_in(EMPLOYEE, "sub-employee", "employee")
		response = h.request(
			self.client.post,
			"/api/method/platform_core.api.ai.approve_proposal",
			json={"proposal_id": "missing-proposal", "digest": "0" * 64},
			headers=h.csrf_headers(self.client),
		)
		self.assertNotEqual(response.json.get("error"), "reauthentication_required", response.json)

	def test_stale_employee_sign_in_gets_403_on_approval(self):
		self._sign_in(EMPLOYEE, "sub-employee", "employee")
		self._set_session_values(keycloak_auth_time=int(time.time()) - 301)
		response = h.request(
			self.client.post,
			"/api/method/platform_core.api.ai.approve_proposal",
			json={"proposal_id": "missing-proposal", "digest": "0" * 64},
			headers=h.csrf_headers(self.client),
		)
		body = self._assert_reauthentication_required(response)
		query = {k: v[0] for k, v in parse_qs(urlparse(body["reauthentication_url"]).query).items()}
		self.assertEqual(query.get("acr_values"), "employee")
