"""G-43: Frappe session limits match the Keycloak employee clients (AJA-2278).

Keycloak ends an employee client session after 1 hour idle and 24 hours in total.
The Frappe cookie session on the tenant site must end at the same limits.
The test reads the constants from session_policy.py without importing Frappe.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from helpers import read_realm

ROOT = Path(__file__).resolve().parents[3]
SESSION_POLICY = ROOT / "apps" / "platform_core" / "platform_core" / "identity" / "session_policy.py"
EMPLOYEE_CLIENTS = ("site-tenant1", "mobile-app", "mcp-external")


def _constants(path: Path) -> dict:
    values = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return values


def _hh_mm_seconds(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 3600 + int(minutes) * 60


class FrappeKeycloakAlignmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = _constants(SESSION_POLICY)
        cls.clients = {c["clientId"]: c for c in read_realm()["clients"]}

    def test_frappe_idle_limit_matches_every_employee_client(self):
        settings = self.policy["SYSTEM_SETTINGS"]
        self.assertEqual(_hh_mm_seconds(settings["session_expiry"]), self.policy["IDLE_SECONDS"])
        for client_id in EMPLOYEE_CLIENTS:
            with self.subTest(client=client_id):
                idle = self.clients[client_id]["attributes"]["client.session.idle.timeout"]
                self.assertEqual(int(idle), self.policy["IDLE_SECONDS"])

    def test_frappe_total_lifespan_matches_every_employee_client(self):
        for client_id in EMPLOYEE_CLIENTS:
            with self.subTest(client=client_id):
                lifespan = self.clients[client_id]["attributes"]["client.session.max.lifespan"]
                self.assertEqual(int(lifespan), self.policy["MAX_LIFESPAN_SECONDS"])


if __name__ == "__main__":
    unittest.main()
