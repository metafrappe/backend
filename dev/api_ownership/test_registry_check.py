"""Regression tests for the API ownership check (G-126).

Run: python3 -I -m unittest discover -s backend/dev/api_ownership
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).resolve().parent))

from registry_check import check  # noqa: E402

ENDPOINT = {
    "endpoint": "demo.api.begin",
    "app": "demo",
    "file": "apps/demo/demo/api/__init__.py",
    "owner_team": "demo-team",
    "status": "new-custom",
    "version": "0.1.0",
    "methods": ["POST"],
    "access": "authenticated",
}
SOURCE = """
import frappe

@frappe.whitelist(methods=["POST"])
def begin():
    return "ok"
"""


class ApiOwnershipCheckTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.backend = Path(directory.name)
        self.write("apps/demo/demo/api/__init__.py", SOURCE)

    def write(self, relative_path, source):
        path = self.backend / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(source), encoding="utf-8")

    def registry(self, endpoints, overrides=()):
        self.write(
            "contracts/api-ownership.json",
            json.dumps({"schema": 1, "endpoints": list(endpoints), "overrides": list(overrides)}),
        )

    def assertFails(self, needle):
        errors = check(self.backend)
        self.assertTrue(any(needle in error for error in errors), errors)

    def test_complete_registry_passes(self):
        self.registry([ENDPOINT])
        self.assertEqual(check(self.backend), [])

    def test_missing_registry_fails(self):
        self.assertFails("contracts/api-ownership.json")

    def test_endpoint_without_owner_team_fails(self):
        self.registry([{**ENDPOINT, "owner_team": ""}])
        self.assertFails("demo.api.begin: owner_team")

    def test_endpoint_without_version_fails(self):
        record = dict(ENDPOINT)
        del record["version"]
        self.registry([record])
        self.assertFails("demo.api.begin: version")

    def test_new_endpoint_missing_from_registry_fails(self):
        self.registry([ENDPOINT])
        self.write(
            "apps/demo/demo/api/extra.py",
            """
            import frappe

            @frappe.whitelist(methods=["GET"])
            def added():
                return "ok"
            """,
        )
        self.assertFails("demo.api.extra.added is not in the API ownership registry")

    def test_record_without_endpoint_in_code_fails(self):
        self.registry([ENDPOINT, {**ENDPOINT, "endpoint": "demo.api.removed"}])
        self.assertFails("demo.api.removed is registered but not whitelisted")

    def test_duplicate_record_fails(self):
        self.registry([ENDPOINT, ENDPOINT])
        self.assertFails("demo.api.begin is registered twice")

    def test_unknown_status_fails(self):
        self.registry([{**ENDPOINT, "status": "maybe"}])
        self.assertFails("demo.api.begin: status")

    def test_wrong_file_fails(self):
        self.registry([{**ENDPOINT, "file": "apps/demo/demo/api/other.py"}])
        self.assertFails("demo.api.begin: file")

    def test_methods_and_access_follow_the_code(self):
        self.registry([{**ENDPOINT, "methods": ["GET"], "access": "guest"}])
        self.assertFails("demo.api.begin: methods")
        self.assertFails("demo.api.begin: access")

    def test_override_must_be_registered_with_owner(self):
        self.write(
            "apps/demo/demo/hooks.py",
            'override_whitelisted_methods = {"frappe.core.sign_up": "demo.api.begin"}\n',
        )
        self.registry([ENDPOINT])
        self.assertFails("frappe.core.sign_up is not in the API ownership registry")

        override = {
            "endpoint": "frappe.core.sign_up",
            "target": "demo.api.begin",
            "app": "demo",
            "owner_team": "demo-team",
            "status": "upstream-patch",
            "version": "0.1.0",
        }
        self.registry([ENDPOINT], [override])
        self.assertEqual(check(self.backend), [])

        self.registry([ENDPOINT], [{**override, "target": "demo.api.other"}])
        self.assertFails("frappe.core.sign_up: target")

    def test_test_files_are_not_endpoints(self):
        self.write("apps/demo/demo/api/test_extra.py", SOURCE)
        self.registry([ENDPOINT])
        self.assertEqual(check(self.backend), [])


if __name__ == "__main__":
    unittest.main()
