"""Exercise the real agent auth hook with local session/cache substitutes (G-59, G-82).

These tests need no Frappe server. They do not replace the HTTP acceptance suite.
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

MODULE = Path(__file__).resolve().parents[2] / "apps/platform_core/platform_core/ai/agent_token.py"


class AgentIdentityTests(unittest.TestCase):
    def setUp(self):
        self.user = "operator@example.test"
        self.record = {"user": self.user, "sid": "session-1", "audience": "agent-service"}
        self.arguments = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        self.frappe = types.ModuleType("frappe")
        self.frappe._ = lambda text, **kwargs: text
        self.frappe.PermissionError = PermissionError
        self.frappe.conf = {}
        self.frappe.cache = Mock()
        self.frappe.cache.get_value.return_value = self.record
        self.frappe.db = Mock()
        self.frappe.db.get_value.return_value = 1
        self.frappe.local = types.SimpleNamespace(form_dict=self.arguments)
        self.frappe.form_dict = self.arguments
        self.frappe.session = types.SimpleNamespace(user="Guest")
        self.frappe.request = types.SimpleNamespace(
            path="/api/method/platform_core.api.ai.mcp", method="POST", cookies={}, args={}
        )
        self.frappe.get_request_header = Mock(return_value="Bearer fsat_local-test")
        self.frappe.set_user = Mock(side_effect=self.set_user)
        sessions = types.ModuleType("frappe.sessions")
        sessions.get_expired_threshold = Mock()
        sessions.get_expiry_in_seconds = Mock(return_value=300)
        utils = types.ModuleType("frappe.utils")
        utils.now = Mock()
        utils.time_diff_in_seconds = Mock(return_value=0)
        access = types.ModuleType("platform_core.ai.access")
        access.AGENT = "agent_token"
        access.record_denial = Mock()
        ai = types.ModuleType("platform_core.ai")
        ai.access = access
        errors = types.ModuleType("platform_core.ai.errors")
        errors.CONTEXT = "platform_core.ai"
        modules = {
            "frappe": self.frappe,
            "frappe.sessions": sessions,
            "frappe.utils": utils,
            "platform_core": types.ModuleType("platform_core"),
            "platform_core.ai": ai,
            "platform_core.ai.access": access,
            "platform_core.ai.errors": errors,
        }
        self.modules = patch.dict(sys.modules, modules)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location("agent_identity_under_test", MODULE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        alive = patch.object(self.module, "_session_alive", return_value=True)
        self.alive = alive.start()
        self.addCleanup(alive.stop)

    def set_user(self, user):
        self.frappe.session.user = user
        # Frappe resets form_dict when it establishes an identity.
        self.frappe.local.form_dict = {}

    def assert_denied(self):
        self.module.authenticate_request()
        self.frappe.set_user.assert_not_called()
        self.assertFalse(hasattr(self.frappe.local, "yz_agent"))

    def test_valid_identity_preserves_operator_and_request_arguments(self):
        self.module.authenticate_request()
        self.assertEqual(self.frappe.session.user, self.user)
        self.assertEqual(self.frappe.local.yz_agent["user"], self.user)
        self.assertIs(self.frappe.local.form_dict, self.arguments)

    def test_wrong_or_multiple_audiences_are_rejected(self):
        for audience in ("press", ["agent-service", "press"], ["agent-service"], None, ""):
            with self.subTest(audience=audience):
                self.record["audience"] = audience
                self.assert_denied()

    def test_configuration_change_revokes_old_target(self):
        self.frappe.conf["ai_agent_audience"] = "new-agent-service"
        self.assert_denied()

    def test_disabled_or_missing_user_is_rejected(self):
        for enabled in (0, None):
            with self.subTest(enabled=enabled):
                self.frappe.db.get_value.return_value = enabled
                self.assert_denied()

    def test_expired_or_revoked_token_is_rejected(self):
        self.frappe.cache.get_value.return_value = None
        self.assert_denied()

    def test_revoked_or_mismatched_session_is_rejected(self):
        self.alive.return_value = False
        self.assert_denied()
        self.alive.assert_called_once_with("session-1", self.user)
        self.frappe.cache.delete_value.assert_called_once()

    def test_other_endpoint_is_rejected(self):
        self.frappe.request.path = "/api/method/frappe.auth.get_logged_user"
        self.assert_denied()

    def test_dispatch_override_is_rejected(self):
        self.arguments["cmd"] = "frappe.auth.get_logged_user"
        self.assert_denied()

    def test_cookie_cannot_replace_operator(self):
        self.frappe.request.cookies["sid"] = "another-session"
        with self.assertRaises(PermissionError):
            self.module.authenticate_request()
        self.frappe.set_user.assert_not_called()


if __name__ == "__main__":
    unittest.main()
