"""Keep the tenant site endpoint inventory (G-143) equal to the endpoints in the code."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from tenant_endpoints import INVENTORY, check, main, update

BACKEND = Path(__file__).resolve().parents[2]


class TenantInventoryIsCurrentTest(unittest.TestCase):
    """The real repository: this test turns red when the inventory goes stale."""

    def test_inventory_matches_the_code(self):
        problems = check(BACKEND)
        self.assertEqual(
            problems,
            [],
            "The tenant endpoint inventory is stale. "
            "Run `python3.14 -B dev/security/tenant_endpoints.py --write .` and classify the new rows.",
        )


class TenantInventoryRulesTest(unittest.TestCase):
    """A small fake backend shows each rule of the check."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.backend = Path(directory.name)
        self.write(
            "apps/demo/demo/api.py",
            """
            import frappe

            @frappe.whitelist(methods=["GET"])
            def read():
                return "test"
            """,
        )
        self.write(
            "apps/demo/demo/hooks.py",
            """
            override_whitelisted_methods = {"frappe.desk.search.search_link": "demo.api.read"}
            website_user_allowed_methods = ["demo.api.read", "logout"]
            """,
        )
        self.write(
            "apps/press_tr/press_tr/api.py",
            """
            import frappe

            @frappe.whitelist(methods=["POST"])
            def control_plane():
                return "test"
            """,
        )
        self.inventory = {
            "apps": ["demo"],
            "sources": {"spa": "Panel", "override": "Replaces a Frappe method"},
            "endpoints": [
                {
                    "route": "/api/method/demo.api.read",
                    "methods": ["GET"],
                    "access": "authenticated",
                    "source": "spa",
                    "evidence": "frontend src/api/client.ts",
                }
            ],
            "desk": [
                {
                    "route": "/api/method/frappe.desk.search.search_link",
                    "methods": ["GET", "POST"],
                    "handler": "demo.api.read",
                    "reason": "The panel link field searches through it.",
                },
                {
                    "route": "/api/method/logout",
                    "methods": ["GET", "POST"],
                    "handler": None,
                    "reason": "Frappe's own sign out.",
                },
            ],
        }
        self.save()

    def write(self, relative_path, source):
        path = self.backend / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(source), encoding="utf-8")

    def save(self):
        path = self.backend / INVENTORY
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.inventory), encoding="utf-8")

    def load(self):
        return json.loads((self.backend / INVENTORY).read_text(encoding="utf-8"))

    def test_current_inventory_passes(self):
        self.assertEqual(check(self.backend), [])

    def test_control_plane_app_is_not_a_tenant_endpoint(self):
        problems = check(self.backend)
        self.assertFalse(any("press_tr" in problem for problem in problems))

    def test_new_endpoint_is_reported(self):
        self.write(
            "apps/demo/demo/extra.py",
            """
            import frappe

            @frappe.whitelist(methods=["POST"])
            def write():
                return "test"
            """,
        )
        problems = check(self.backend)
        self.assertTrue(
            any("/api/method/demo.extra.write" in p and "missing" in p for p in problems), problems
        )

    def test_removed_endpoint_is_reported(self):
        self.inventory["endpoints"].append(
            {
                "route": "/api/method/demo.api.gone",
                "methods": ["GET"],
                "access": "authenticated",
                "source": "spa",
                "evidence": "frontend",
            }
        )
        self.save()
        problems = check(self.backend)
        self.assertTrue(any("demo.api.gone" in p and "no longer" in p for p in problems), problems)

    def test_changed_method_or_access_is_reported(self):
        self.inventory["endpoints"][0]["methods"] = ["POST"]
        self.inventory["endpoints"][0]["access"] = "guest"
        self.save()
        problems = check(self.backend)
        self.assertTrue(any("methods" in p for p in problems), problems)
        self.assertTrue(any("access" in p for p in problems), problems)

    def test_unknown_source_and_empty_evidence_are_reported(self):
        self.inventory["endpoints"][0]["source"] = "unclassified"
        self.inventory["endpoints"][0]["evidence"] = ""
        self.save()
        problems = check(self.backend)
        self.assertTrue(any("source" in p for p in problems), problems)
        self.assertTrue(any("evidence" in p for p in problems), problems)

    def test_desk_entry_needs_reason_and_a_real_override(self):
        self.inventory["desk"][0]["reason"] = " "
        self.inventory["desk"][0]["handler"] = "demo.api.other"
        self.save()
        problems = check(self.backend)
        self.assertTrue(any("reason" in p for p in problems), problems)
        self.assertTrue(any("override_whitelisted_methods" in p for p in problems), problems)

    def test_override_source_needs_an_override_hook(self):
        self.inventory["endpoints"][0]["source"] = "override"
        self.save()
        self.assertEqual(check(self.backend), [])
        self.write("apps/demo/demo/hooks.py", 'website_user_allowed_methods = ["demo.api.read", "logout"]\n')
        problems = check(self.backend)
        self.assertTrue(any("override_whitelisted_methods" in p for p in problems), problems)

    def test_website_user_method_outside_inventory_is_reported(self):
        self.write(
            "apps/demo/demo/hooks.py",
            """
            override_whitelisted_methods = {"frappe.desk.search.search_link": "demo.api.read"}
            website_user_allowed_methods = ["demo.api.read", "logout", "frappe.client.get_list"]
            """,
        )
        problems = check(self.backend)
        self.assertTrue(any("frappe.client.get_list" in p for p in problems), problems)

    def test_unreadable_file_is_reported(self):
        self.write("apps/demo/demo/broken.py", "def broken(:\n")
        problems = check(self.backend)
        self.assertTrue(any("Could not read" in p for p in problems), problems)

    def test_update_keeps_classification_and_marks_new_rows(self):
        self.write(
            "apps/demo/demo/extra.py",
            """
            import frappe

            @frappe.whitelist(allow_guest=True, methods=["POST"])
            def write():
                return "test"
            """,
        )
        update(self.backend)
        rows = {row["route"]: row for row in self.load()["endpoints"]}
        self.assertEqual(rows["/api/method/demo.api.read"]["source"], "spa")
        self.assertEqual(rows["/api/method/demo.api.read"]["evidence"], "frontend src/api/client.ts")
        new = rows["/api/method/demo.extra.write"]
        self.assertEqual(new["source"], "unclassified")
        self.assertEqual(new["methods"], ["POST"])
        self.assertEqual(new["access"], "guest")
        self.assertEqual(len(self.load()["desk"]), 2)
        self.assertTrue(any("source" in p for p in check(self.backend)))

    def test_main_exit_status(self):
        output = io.StringIO()
        with patch("sys.argv", ["tenant_endpoints.py", str(self.backend)]):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.assertEqual(main(), 0)
        self.inventory["endpoints"] = []
        self.save()
        with patch("sys.argv", ["tenant_endpoints.py", str(self.backend)]):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.assertEqual(main(), 1)


if __name__ == "__main__":
    unittest.main()
