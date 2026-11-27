"""Backend guidance must describe the PR and ProPR merge flow (AJA-1508, AJA-1673).

Moved from frappesetup PR 77. In this repository work enters `main` through a PR.

    python3 -I -m unittest discover -s dev/tests -p test_branch_flow_docs.py
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ("AGENTS.md", "CLAUDE.md")
DOCS = GUIDES + ("PROJECT-RECORD.md",)

# Sentences that said the branch stays local or that the orchestrator merges.
STALE = (
    re.compile(r"Push yapmayın\. Pull request açmayın"),
    re.compile(r"Push, pull request ve canlıya yükleme bu turda yapılmaz"),
    re.compile(r"Dalları orkestratör birleştirir"),
    re.compile(r"Orkestratör dalınızı inceler ve birleştirir"),
    re.compile(r"backend[^.\n]*GitHub'a gitmez"),
)


class BranchFlowDocsTests(unittest.TestCase):
    def test_documents_sit_at_the_root(self):
        self.assertFalse((ROOT / "backend").exists())
        for name in DOCS:
            with self.subTest(doc=name):
                self.assertTrue((ROOT / name).is_file())

    def test_no_document_says_the_branch_stays_local(self):
        for name in DOCS:
            text = (ROOT / name).read_text(encoding="utf-8")
            for pattern in STALE:
                with self.subTest(doc=name, pattern=pattern.pattern):
                    self.assertIsNone(pattern.search(text))

    def test_documents_name_the_pr_and_propr_rule(self):
        for name in DOCS:
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(doc=name):
                self.assertIn("`main` dalına PR", text)
                self.assertIn("PR'ı ProPR birleştirir", text)

    def test_documents_forbid_direct_push(self):
        for name in DOCS:
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(doc=name):
                self.assertIn("Hiçbir ajan `main` dalına doğrudan push etmez", text)

    def test_record_keeps_the_old_history_note(self):
        text = (ROOT / "PROJECT-RECORD.md").read_text(encoding="utf-8")
        self.assertIn("`58e8dbc` kaydı bu depoda yoktur", text)

    def test_guides_stay_identical(self):
        self.assertEqual(
            (ROOT / "AGENTS.md").read_text(encoding="utf-8"),
            (ROOT / "CLAUDE.md").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
