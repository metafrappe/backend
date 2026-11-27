"""Every whitelisted method in the backend apps has an owner record (G-126)."""

import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND / "dev/api_ownership"))

from registry_check import check  # noqa: E402


class ApiOwnershipRegistryTest(unittest.TestCase):
    def test_registry_matches_the_apps(self):
        self.assertTrue((BACKEND / "contracts/api-ownership.json").is_file())
        self.assertEqual(check(BACKEND), [])


if __name__ == "__main__":
    unittest.main()
