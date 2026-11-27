"""The notification email code keeps the same languages as contracts/locales.json (AJA-1783).

The Frappe app is installed without this folder, so it cannot read contracts/locales.json at run time.
The app keeps a copy of three values. This test fails when the copy and the contract differ.

The contract file comes from AJA-1776. The test is skipped until that file is in the branch.

Run: python3 -I -m unittest discover -s contracts/tests -v
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCALES = ROOT / "contracts" / "locales.json"
CODE = ROOT / "apps" / "platform_core" / "platform_core" / "notification_email.py"


def code_constants() -> dict:
    values = {}
    for node in ast.parse(CODE.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return values


@unittest.skipUnless(LOCALES.is_file(), "contracts/locales.json is not in this branch yet (AJA-1776)")
class NotificationLocaleCopyTest(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads(LOCALES.read_text(encoding="utf-8"))
        self.code = code_constants()

    def test_open_languages(self):
        self.assertEqual(list(self.code["OPEN_LANGUAGES"]), self.contract["open_languages"])

    def test_default_locale(self):
        self.assertEqual(self.code["DEFAULT_LOCALE"], self.contract["default_locale"])

    def test_order(self):
        self.assertEqual(list(self.code["LOCALE_ORDER"]), self.contract["notification_locale_order"])


if __name__ == "__main__":
    unittest.main()
