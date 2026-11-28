"""G-11: closure evidence for Press access rules.

The checks need the pinned Press source, but not a database:
- Frappe 16 runs `before_request` hooks before the Press auth hook checks a request.
- press_tr adds only documented routes to `press.auth.ALLOWED_PATHS`, once.
- Website users reach documented press_tr routes and nothing else under `/api/`.
- press_tr DocTypes stay out of the Press dashboard client.
- A team cannot read another team's record through the dashboard client.
"""

import ast
import importlib
import inspect
import json
import pkgutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
import frappe.app
import frappe.auth
import press
import press.auth
from press.api import client
from werkzeug.exceptions import HTTPException

import press_tr
import press_tr.api
from press_tr import hooks
from press_tr.press_identity import request_policy

APP_ROOT = Path(press_tr.__file__).resolve().parent


def raise_exception(message, exception=frappe.ValidationError, *args, **kwargs):
	raise exception(message)


def functions_named(path, names):
	module = ast.parse(Path(path).read_text())
	return {
		node.name: node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in names
	}


def get_hooks_names(node):
	return {
		call.args[0].value
		for call in ast.walk(node)
		if isinstance(call, ast.Call)
		and ast.unparse(call.func) == "frappe.get_hooks"
		and call.args
		and isinstance(call.args[0], ast.Constant)
	}


def press_auth_hooks():
	# Importing press.hooks reads the database, so read the assignment from the source.
	module = ast.parse((Path(press.__file__).parent / "hooks.py").read_text())
	values = [
		ast.literal_eval(node.value)
		for node in module.body
		if isinstance(node, ast.Assign)
		and any(isinstance(target, ast.Name) and target.id == "auth_hooks" for target in node.targets)
	]
	return values[-1] if values else []


def called_names(node):
	return [
		call.func.id
		for call in ast.walk(node)
		if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
	]


def press_tr_api_methods():
	for module in pkgutil.iter_modules(press_tr.api.__path__):
		if not module.name.startswith("test_"):
			importlib.import_module(f"press_tr.api.{module.name}")
	return sorted(
		f"{method.__module__}.{method.__qualname__}"
		for method in map(inspect.unwrap, frappe.whitelisted)
		if method.__module__.split(".")[:2] == ["press_tr", "api"]
	)


def press_tr_doctypes():
	return sorted(
		json.loads(path.read_text())["name"]
		for path in APP_ROOT.glob("*/doctype/*/*.json")
		if path.stem == path.parent.name
	)


class PressAccessTest(unittest.TestCase):
	def run_before_request(self, path, allowed_paths):
		facade = Mock()
		facade.request.path = path
		facade.form_dict.get.return_value = None
		facade.get_request_header.return_value = "token key:secret"
		with (
			patch.object(request_policy, "frappe", facade),
			patch.object(request_policy, "request_target", return_value=(Mock(), {})),
			patch.object(request_policy, "blocked_identity_targets", return_value=set()),
			patch.object(request_policy, "machine_targets", return_value={}),
			patch.object(request_policy, "block_team_invitation"),
			patch.object(press.auth, "ALLOWED_PATHS", allowed_paths),
		):
			request_policy.before_request()

	def run_page_request(self, path):
		facade = Mock()
		facade.request.path = path
		facade.form_dict.get.return_value = None
		facade.conf.platform_panel_url = "https://panel.example.test"
		facade.local.response_headers = {}
		with (
			patch.object(request_policy, "frappe", facade),
			patch.object(request_policy, "request_target", return_value=(None, None)),
		):
			request_policy.before_request()
		return facade

	def press_auth_allows(self, path, allowed_paths):
		facade = Mock()
		facade.form_dict.cmd = None
		facade.request.path = path
		facade.request.method = "POST"
		facade.session.user = "member@example.test"
		facade.get_cached_value.return_value = "Website User"
		facade.AuthenticationError = frappe.AuthenticationError
		facade.throw.side_effect = raise_exception
		with (
			patch.object(press.auth, "frappe", facade),
			patch.object(press.auth, "log"),
			patch.object(press.auth, "ALLOWED_PATHS", allowed_paths),
		):
			try:
				press.auth.hook()
			except frappe.AuthenticationError:
				return False
		return True

	def test_frappe_16_runs_before_request_before_press_auth(self):
		"""Frappe 16 runs the press_tr before_request hook before the Press auth check."""
		self.assertEqual(frappe.__version__.split(".")[0], "16")
		app = functions_named(frappe.app.__file__, {"application", "init_request"})
		calls = called_names(app["application"])
		self.assertLess(calls.index("init_request"), calls.index("validate_auth"))
		self.assertIs(frappe.app.validate_auth, frappe.auth.validate_auth)
		self.assertIn("before_request", get_hooks_names(app["init_request"]))
		self.assertIn("press_tr.press_identity.request_policy.before_request", hooks.before_request)

		# Press checks its path lists in an auth hook. validate_auth must run the auth hooks,
		# and Press must register its check there; otherwise nothing runs after before_request.
		auth = functions_named(frappe.auth.__file__, {"validate_auth", "validate_auth_via_hooks"})
		self.assertIn("validate_auth_via_hooks", called_names(auth["validate_auth"]))
		self.assertIn("auth_hooks", get_hooks_names(auth["validate_auth_via_hooks"]))
		self.assertIn("press.auth.hook", press_auth_hooks())
		module, name = "press.auth.hook".rsplit(".", 1)
		self.assertIs(getattr(importlib.import_module(module), name), press.auth.hook)

	def test_every_press_tr_api_method_has_a_documented_route(self):
		methods = press_tr_api_methods()
		self.assertTrue(methods)
		# G-11 names `/api/method/press_tr.api.` as a wildcard. press_tr lists each method instead,
		# so a new method stays closed until it is documented. Every current method is reachable.
		for method in methods:
			with self.subTest(method=method):
				allowed_paths = []
				self.run_before_request(f"/api/method/{method}", allowed_paths)
				self.assertEqual(allowed_paths, [f"/api/method/{method}"])

	def test_documented_route_is_added_to_press_allowlist_once(self):
		allowed_paths = []
		path = "/api/method/press_tr.api.account.request_deletion"
		self.run_before_request(path, allowed_paths)
		self.run_before_request(path + "/", allowed_paths)
		self.assertEqual(allowed_paths, [path])
		# Press compares the raw path, so the slash spelling is not opened by the stripped entry.
		self.assertTrue(self.press_auth_allows(path, allowed_paths))
		self.assertFalse(self.press_auth_allows(path + "/", allowed_paths))

	def test_trailing_slash_does_not_skip_page_rules(self):
		# The Frappe website router ignores a trailing slash, so "/login/" shows the login page.
		# before_request strips the slash so the same page rules apply to both spellings.
		for page in ("/login/", "/signup/", "/dashboard/login/"):
			with self.subTest(page=page):
				with self.assertRaises(HTTPException) as caught:
					self.run_page_request(page)
				self.assertEqual(caught.exception.response.status_code, 302)
				self.assertEqual(caught.exception.response.location, "https://panel.example.test")
		facade = self.run_page_request(request_policy.ACCOUNT_DELETION_PAGE + "/")
		self.assertEqual(facade.local.response_headers.get("Cache-Control"), "private, no-store")
		self.assertTrue(facade.local.no_cache)

	def test_undocumented_press_tr_route_stays_closed_to_website_users(self):
		allowed_paths = []
		path = "/api/method/press_tr.api.account.undocumented"
		self.run_before_request(path, allowed_paths)
		self.assertEqual(allowed_paths, [])
		self.assertFalse(self.press_auth_allows(path, allowed_paths))

	def test_press_auth_allows_documented_routes_and_denies_other_api_paths(self):
		allowed_paths = []
		documented = "/api/method/press_tr.api.account.request_deletion"
		self.run_before_request(documented, allowed_paths)
		self.assertTrue(self.press_auth_allows(documented, allowed_paths))
		for path in (
			"/api/method/frappe.client.get_list",
			"/api/resource/PTR Identity Link",
			"/api/v2/document/PTR Keycloak Session",
		):
			with self.subTest(path=path):
				self.assertFalse(self.press_auth_allows(path, allowed_paths))

	def test_press_tr_doctypes_are_closed_to_the_dashboard_client(self):
		doctypes = press_tr_doctypes()
		self.assertTrue(doctypes)
		team = SimpleNamespace(name="team-a")
		with (
			patch.object(client.frappe, "throw", side_effect=raise_exception),
			patch.object(client.frappe.local, "team", Mock(return_value=team), create=True),
		):
			self.assertTrue(client.check_permissions("Site"))
			for doctype in doctypes:
				with self.subTest(doctype=doctype):
					self.assertNotIn(doctype, client.ALLOWED_DOCTYPES)
					with self.assertRaises(frappe.PermissionError):
						client.check_permissions(doctype)

	def test_press_tr_source_does_not_touch_press_dashboard_doctype_list(self):
		# Press opens a DocType to the dashboard client only through client.ALLOWED_DOCTYPES.
		# press_tr must never name that list, so it cannot add its own DocTypes to it.
		files = [path for path in APP_ROOT.rglob("*") if path.is_file() and "__pycache__" not in path.parts]
		self.assertTrue(files)
		for path in files:
			with self.subTest(path=path.relative_to(APP_ROOT)):
				self.assertNotIn("ALLOWED_DOCTYPES", path.read_text(errors="replace"))

	def test_press_tr_has_no_dashboard_document_methods(self):
		# Press Method Permission rows guard dashboard document methods. press_tr has none.
		for path in APP_ROOT.rglob("*.py"):
			with self.subTest(path=path.relative_to(APP_ROOT)):
				self.assertNotIn("dashboard_whitelist", path.read_text())

	def test_dashboard_client_denies_another_teams_record(self):
		facade = Mock()
		facade.local.team.return_value = SimpleNamespace(name="team-a")
		facade.throw.side_effect = raise_exception
		facade.PermissionError = frappe.PermissionError
		with patch.object(client, "frappe", facade):
			facade.db.get_value.return_value = "team-a"
			self.assertTrue(client.is_owned_by_team("Site", "own.example.test"))
			facade.db.get_value.return_value = "team-b"
			with self.assertRaises(frappe.PermissionError):
				client.is_owned_by_team("Site", "other.example.test")
		facade.db.get_value.assert_called_with("Site", "other.example.test", "team")


if __name__ == "__main__":
	unittest.main()
