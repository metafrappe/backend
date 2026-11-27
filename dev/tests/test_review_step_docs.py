"""Process docs must describe the ProPR `/review` step before QA (AJA-2159).

Customer decision, 28 November 2026 (AJA-2151, AJA-1800 rule 4): every PR
gets a `/review` comment, the ProPR review finishes, the developer fixes the
findings, and only then QA starts.

Each check runs only when its document exists on the current branch, so the
same test file can live on both documentation branches.

    python3 -B -m unittest dev/tests/test_review_step_docs.py
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARDS = ROOT / "docs" / "standards"
DEFINITION_OF_DONE = STANDARDS / "definition-of-done.md"
REVIEW_TEMPLATE = STANDARDS / "review-template.md"

# Order of the four steps, as written in AJA-1800 rule 4.
ORDERED_STEPS = (
    "`/review` yorumu yazar",
    "ProPR incelemesi biter",
    "Geliştirici bulguları düzeltir",
    "QA bundan sonra başlar",
)
QA_RETURN_RULE = "PR'da `/review` yorumu yoksa QA işi geliştiriciye geri verir"
TEMPLATE_CHECKBOX = "- [ ] PR'a `/review` yorumu yazıldı ve ProPR incelemesi bitti."


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ReviewStepOrderMixin:
    path: Path

    def setUp(self):
        if not self.path.exists():
            self.skipTest(f"{self.path.name} is not on this branch")
        self.text = _read(self.path)

    def test_steps_in_order(self):
        positions = []
        for step in ORDERED_STEPS:
            self.assertIn(step, self.text, f"{self.path.name}: missing step {step!r}")
            positions.append(self.text.index(step))
        self.assertEqual(positions, sorted(positions), f"{self.path.name}: steps out of order")

    def test_qa_returns_work_without_review(self):
        self.assertIn(QA_RETURN_RULE, self.text)


class DefinitionOfDoneTest(ReviewStepOrderMixin, unittest.TestCase):
    path = DEFINITION_OF_DONE


class ReviewTemplateTest(ReviewStepOrderMixin, unittest.TestCase):
    path = REVIEW_TEMPLATE

    def test_checkbox_before_qa(self):
        self.assertIn(TEMPLATE_CHECKBOX, self.text)


if __name__ == "__main__":
    unittest.main()
