"""G-39 site config keys moved from the frappesetup pc/config-secrets branch (AJA-660, AJA-1673).

The Semgrep review of the repository root (AJA-690, AJA-691) covers press_tr/hooks.py. The review
summary must match the files at their root paths, so the reviewed findings stay valid.

    python3 -I -m unittest discover -s deploy/tests
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/press_tr/press_tr"
CONFIG = ROOT / "dev/security/semgrep-exceptions.json"
sys.path.insert(0, str(ROOT / "dev/security"))
from semgrep_exceptions import source_digest  # noqa: E402


class ConfigSecretsLayoutTests(unittest.TestCase):
    def test_fixture_and_test_sit_at_the_root(self):
        self.assertTrue((APP / "fixtures/site_config_key.json").is_file())
        self.assertTrue((ROOT / "apps/press_tr/tests/test_site_config_keys.py").is_file())
        self.assertFalse((ROOT / "backend").exists())

    def test_hooks_export_the_site_config_key_fixture(self):
        self.assertIn('"dt": "Site Config Key"', (APP / "hooks.py").read_text(encoding="utf-8"))


@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "needs a Git checkout")
class SemgrepReviewSummaryTests(unittest.TestCase):
    def test_root_review_covers_press_hooks_with_root_paths(self):
        review = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(review["scope"], ".")
        self.assertIn("apps/press_tr/press_tr/hooks.py", review["files"])
        self.assertFalse([name for name in review["files"] if name.startswith("backend/")])

    def test_root_review_summary_matches_the_tree(self):
        review = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(source_digest(ROOT, review["scope"], review["files"]), review["sha256"])


if __name__ == "__main__":
    unittest.main()
