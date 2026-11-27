"""G-64: the "AI Action Log" points at the real "Version" record. Checked without a site."""

import json
import unittest
from pathlib import Path

LOG_JSON = (
    Path(__file__).resolve().parents[2]
    / "apps/platform_core/platform_core/ai/doctype/plt_ai_action_log/plt_ai_action_log.json"
)


class ActionLogVersionLinkTests(unittest.TestCase):
    def test_version_field_links_to_the_version_doctype(self):
        fields = {field["fieldname"]: field for field in json.loads(LOG_JSON.read_text())["fields"]}

        self.assertEqual(fields["version"]["fieldtype"], "Link")
        self.assertEqual(fields["version"]["options"], "Version")
        self.assertTrue(fields["version"].get("read_only"))


if __name__ == "__main__":
    unittest.main()
