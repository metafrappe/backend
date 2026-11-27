"""G-128 source ledger moved from frappesetup PR 51 to the repository root (AJA-1673).

    python3 -I -m unittest discover -s deploy/tests
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOVED = (
    "dev/bin/check-source-ledger",
    "dev/tests/test_source_ledger.py",
    "docs/evidence/source-ledger.json",
    "docs/evidence/source-ledger.md",
    "docs/evidence/site-ledger-e78ba766.md",
)


class SourceLedgerLayoutTests(unittest.TestCase):
    def test_files_sit_at_the_root(self):
        for relative in MOVED:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())
                self.assertFalse((ROOT / "backend" / relative).exists())

    def test_bandit_exceptions_name_the_root_path(self):
        rows = json.loads((ROOT / "dev/security/bandit-exceptions.json").read_text(encoding="utf-8"))
        files = {row["file"] for row in rows}
        self.assertIn("dev/tests/test_source_ledger.py", files)
        self.assertNotIn("backend/dev/tests/test_source_ledger.py", files)


if __name__ == "__main__":
    unittest.main()
