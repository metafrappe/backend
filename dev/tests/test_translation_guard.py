"""Contract for the backend translation check."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_translations", DEV / "check_translations.py")
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class TestTranslationGuard(unittest.TestCase):
    def check_source(self, source):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.py"
            path.write_text(source, encoding="utf-8")
            return CHECKER.violations(path)

    def test_literal_user_message_is_reported(self):
        self.assertEqual(self.check_source('import frappe\nfrappe.throw("Choose a record.")\n'), [2])

    def test_translated_message_and_internal_values_are_accepted(self):
        self.assertEqual(
            self.check_source(
                'from frappe import _, throw\nstate = "pending"\nthrow(_("Choose a record."))\n'
            ),
            [],
        )

    def test_alias_and_formatted_user_message_are_reported(self):
        self.assertEqual(
            self.check_source('from frappe import msgprint as notify\nnotify(f"Choose {name}.")\n'),
            [2],
        )

    def test_keyword_title_and_joined_message_are_reported(self):
        self.assertEqual(
            self.check_source(
                "import frappe as f\n"
                'f.throw(msg=_("Choose a record."), title="Error")\n'
                'f.msgprint("Saved " + name)\n'
                'f.throw("Choose {0}.".format(name))\n'
            ),
            [2, 3, 4],
        )

    def test_backend_apps_have_no_literal_user_message(self):
        found = {
            str(path.relative_to(CHECKER.BACKEND)): lines
            for path in CHECKER.source_files()
            if (lines := CHECKER.violations(path))
        }
        self.assertEqual(found, {})


if __name__ == "__main__":
    unittest.main()
