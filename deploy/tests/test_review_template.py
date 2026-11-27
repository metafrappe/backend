"""The review template and the project record moved from frappesetup (AJA-1674).

Source pull requests: karacaismail/frappesetup #68 and #71. The text stays the same as the
source. Only the paths change. These tests run with the standard library only:

    python3 -I -m unittest discover -s deploy/tests
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "docs" / "standards" / "review-template.md"
RECORD = ROOT / "PROJECT-RECORD.md"


def read(path):
    return path.read_text(encoding="utf-8")


class CommitIdentityTests(unittest.TestCase):
    """frappesetup #68: ProPR merges and every commit identity is karacaismail (D-17, K-62)."""

    def test_project_record_has_decision_d17(self):
        text = read(RECORD)
        self.assertIn(
            "- **D-17. PR'ları ProPR birleştirir. ProPR'ın commit kimliği `karacaismail` olur.**",
            text,
        )
        self.assertIn("- `PROPR_AGENT_COMMIT_AUTHOR_NAME=karacaismail`", text)
        self.assertIn(
            "- `PROPR_AGENT_COMMIT_AUTHOR_EMAIL=35493655+karacaismail@users.noreply.github.com`",
            text,
        )
        self.assertIn("Adım `docs/standards/review-template.md` dosyasındadır.", text)
        # D-17 sits right after D-16 and before the orchestrator defaults.
        self.assertLess(text.index("- **D-16."), text.index("- **D-17."))
        self.assertLess(text.index("- **D-17."), text.index("## Orkestratörün seçtiği varsayılanlar"))

    def test_review_template_has_the_commit_identity_step(self):
        text = read(TEMPLATE)
        self.assertIn(
            "11. Committer her PR'da commit kimliğini denetler. Bu adım ProPR kuralının gereğidir. "
            "Kural `PROJECT-RECORD.md` dosyasındadır.",
            text,
        )
        self.assertIn("Kimliği şu komutla görün: `git log --format='%h %an %cn' <ana dal>..<PR dalı>`.", text)
        self.assertIn("Başka bir kimlik varsa dal birleşmez. Committer işi gerekçesiyle geri verir.", text)
        self.assertNotIn("backend/PROJECT-RECORD.md", text)


class AutoMergeLabelTests(unittest.TestCase):
    """frappesetup #71: the auto-merge label goes on only after approval; backend has no CI yet."""

    def test_review_template_has_the_auto_merge_section(self):
        text = read(TEMPLATE)
        self.assertIn("## `auto-merge` etiketi", text)
        self.assertIn("Etiket, PR'a konan kısa bir işarettir. ProPR, `auto-merge` etiketli PR'ı birleştirir.", text)
        self.assertIn("1. QA ve Committer onay verince PR'a `auto-merge` etiketi konur.", text)
        self.assertIn("2. Etiket onaydan önce konmaz.", text)
        self.assertIn(
            "3. Backend deposunda CI henüz yoktur. CI gelmeden backend'de hiçbir PR'a `auto-merge` etiketi konmaz. "
            "CI işi AJA-1528 kapsamındadır.",
            text,
        )
        # The section sits between the 7 step flow and the merge gate note, as in the source.
        self.assertLess(text.index("7. Hiçbir ajan `main` dalına"), text.index("## `auto-merge` etiketi"))
        self.assertLess(text.index("## `auto-merge` etiketi"), text.index("Birleştirme kapıları birleştirmenin parçasıdır."))
        # Paperclip issue links do not work in this repository (same rule as PR 11).
        self.assertNotIn("(/AJA/issues/", text)


if __name__ == "__main__":
    unittest.main()
