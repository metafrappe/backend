"""G-119/G-143 through Frappe's WSGI entry, with in-memory session storage.

Run inside the pinned tenant image. No database, Redis, network or live site is used.
This verifies application behavior, not proxy routing or real browser CORS enforcement.
"""

import secrets
import unittest
from contextlib import ExitStack
from importlib.util import find_spec
from unittest.mock import Mock, patch
from urllib.parse import urlencode

if find_spec("frappe") is None:
    raise unittest.SkipTest("Run in the pinned tenant image to exercise the real Frappe WSGI application")

import frappe
import frappe.app
import frappe.auth
from werkzeug.test import Client
from werkzeug.wrappers import Response

from platform_core import hooks

HOST = "tenant-a.example.test"
OTHER_HOST = "tenant-b.example.test"
PANEL_ORIGIN = "https://panel.example.test"
FOREIGN_ORIGIN = "https://foreign.example.test"
USER = "reader@example.test"
SESSION_ID = "fixture-session"
# Fresh request token for each run.
CSRF_TOKEN = secrets.token_hex(16)
ALLOWED = "frappe.auth.get_logged_user"
DENIED = "frappe.client.get_count"


class RequestIsolationTests(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.addCleanup(frappe.destroy)
        self.observed_requests = []
        self.cache = Mock()
        self.cache.get_value.return_value = []
        # Empty translation maps keep messages as plain source strings.
        self.cache.hget.return_value = {}
        replacements = {
            "frappe.get_site_config": lambda **kwargs: frappe._dict(
                db_name="fixture", db_type="mariadb", allow_cors=[PANEL_ORIGIN], allowed_referrers=[]
            ),
            "frappe.setup_module_map": lambda **kwargs: None,
            "frappe.connect": lambda **kwargs: None,
            "frappe.cache": self.cache,
            "frappe.client_cache": Mock(),
            "frappe.get_hooks": self.get_hooks,
            "frappe.get_installed_apps": lambda *args, **kwargs: ["frappe", "platform_core"],
            "frappe.get_system_settings": lambda *args: None,
            "frappe.auth.HTTPRequest.set_session": self.set_session,
            "frappe.auth.HTTPRequest.set_lang": lambda instance: None,
            "frappe.auth.get_expiry_in_seconds": lambda: 3600,
            "frappe.app.sync_database": lambda: None,
            "frappe.app.log_request": lambda *args: None,
            "frappe.app.log_error_snapshot": lambda *args: None,
            "frappe.handler.get_server_script_map": lambda: {},
            "frappe.app.run_after_request_hooks": lambda *args: None,
            "frappe.app.is_oauth_metadata_enabled": lambda *args: False,
            "frappe.api.add_data_to_monitor": lambda **kwargs: None,
            "frappe.api.capture_app_heartbeat": lambda *args: None,
            "frappe.monitor.get_trace_id": lambda: None,
            "frappe.utils.response.is_traceback_allowed": lambda: False,
            "platform_core.shell.native_metadata.is_system_user": lambda: False,
            "platform_core.shell.native_metadata.get_server_script_map": lambda: {},
        }
        for target, replacement in replacements.items():
            self.patches.enter_context(patch(target, replacement))
        self.client = Client(frappe.app.application, Response)
        self.client.set_cookie("sid", SESSION_ID, domain=HOST, origin_only=True)

    @staticmethod
    def get_hooks(name=None, default=None, **kwargs):
        values = {
            "before_request": ["platform_core.shell.native_metadata.guard_website_rpc_before_request"],
            "auth_hooks": ["platform_core.shell.native_metadata.guard_native_metadata"],
            "website_user_allowed_methods": hooks.website_user_allowed_methods,
            "override_whitelisted_methods": {},
        }
        return values.get(name, default if default is not None else [])

    def set_session(self):
        request = frappe.local.request
        sid = request.cookies.get("sid")
        self.observed_requests.append((request.host, sid))
        user = USER if sid == SESSION_ID and request.host == HOST else "Guest"
        frappe.local.session = frappe._dict(
            user=user,
            sid=SESSION_ID if user == USER else None,
            data=frappe._dict(csrf_token=CSRF_TOKEN if user == USER else None),
        )

    def request(self, path, *, method="GET", host=HOST, headers=None):
        return self.client.open(
            path,
            method=method,
            base_url=f"https://{host}",
            headers={"Accept": "application/json", **(headers or {})},
        )

    def test_production_hooks_register_both_rpc_guards(self):
        self.assertIn(
            "platform_core.shell.native_metadata.guard_website_rpc_before_request", hooks.before_request
        )
        self.assertIn("platform_core.shell.native_metadata.guard_native_metadata", hooks.auth_hooks)

    def test_session_cookie_is_host_only_secure_and_not_sent_to_another_site(self):
        response = self.request(f"/api/method/{ALLOWED}")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json["message"], USER)
        cookie = self.client.get_cookie("sid", domain=HOST)
        self.assertIsNotNone(cookie)
        self.assertTrue(cookie.origin_only)
        self.assertTrue(cookie.secure)
        self.assertTrue(cookie.http_only)
        self.assertEqual(cookie.same_site, "Lax")
        other = self.request(f"/api/method/{ALLOWED}", host=OTHER_HOST)
        self.assertEqual(other.status_code, 403, other.data)
        self.assertEqual(self.observed_requests[-1], (OTHER_HOST, None))

    def test_foreign_origin_receives_no_cors_permission(self):
        for method in ("GET", "OPTIONS"):
            with self.subTest(method=method):
                response = self.request(
                    f"/api/method/{ALLOWED}",
                    method=method,
                    headers={"Origin": FOREIGN_ORIGIN, "Access-Control-Request-Method": "POST"},
                )
                self.assertEqual(response.status_code, 200, response.data)
                self.assertNotIn("Access-Control-Allow-Origin", response.headers)
                self.assertNotIn("Access-Control-Allow-Credentials", response.headers)

    def test_permitted_origin_keeps_the_existing_read_flow(self):
        response = self.request(f"/api/method/{ALLOWED}", headers={"Origin": PANEL_ORIGIN})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json["message"], USER)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], PANEL_ORIGIN)
        self.assertEqual(response.headers["Access-Control-Allow-Credentials"], "true")

    def test_write_without_csrf_is_400_before_the_handler_runs(self):
        for headers in ({}, {"Origin": FOREIGN_ORIGIN}, {"X-Frappe-CSRF-Token": "wrong"}):
            with self.subTest(headers=headers), patch("frappe.handler.execute_cmd") as execute:
                response = self.request(f"/api/method/{ALLOWED}", method="POST", headers=headers)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.json["exc_type"], "CSRFTokenError")
                execute.assert_not_called()

    def test_write_with_csrf_reaches_the_permitted_handler(self):
        response = self.request(
            f"/api/method/{ALLOWED}", method="POST", headers={"X-Frappe-CSRF-Token": CSRF_TOKEN}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json["message"], USER)

    def test_unlisted_method_returns_403_on_every_rpc_route(self):
        paths = [
            f"/api/method/{DENIED}",
            f"/api/v1/method/{DENIED}",
            f"/api/v2/method/{DENIED}",
            "/?" + urlencode({"cmd": DENIED}),
        ]
        for path in paths:
            with self.subTest(path=path), patch("frappe.handler.execute_cmd") as execute:
                response = self.request(path)
                self.assertEqual(response.status_code, 403, response.data)
                self.assertNotIn("message", response.json)
                self.assertNotIn("data", response.json)
                execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
