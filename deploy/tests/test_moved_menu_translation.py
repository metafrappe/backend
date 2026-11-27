"""G-73 menu translation moved from frappesetup PR 55 to the repository root (AJA-1673).

The Frappe test in platform_core needs a bench. This test reads the same CSV row with the
standard library only:

    python3 -I -m unittest discover -s deploy/tests
"""

import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "apps/platform_core/platform_core/shell"
CSV_PATH = ROOT / "apps/platform_core/platform_core/translations/tr.csv"


class MenuTranslationLayoutTests(unittest.TestCase):
    def test_frappe_test_sits_at_the_root(self):
        self.assertTrue((SHELL / "test_sidebar_translations.py").is_file())
        self.assertFalse((ROOT / "backend").exists())

    def test_connected_app_row_has_the_fix_and_no_context(self):
        with CSV_PATH.open(encoding="utf-8", newline="") as handle:
            rows = [row for row in csv.reader(handle) if row and row[0] == "Connected App"]
        self.assertEqual(len(rows), 1, rows)
        _source, translation, *context = rows[0]
        self.assertEqual(translation, "Bağlı Uygulamalar")
        self.assertFalse(any(context), context)


if __name__ == "__main__":
    unittest.main()
