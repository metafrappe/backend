"""The operations handoff notes must exist and point only at files that exist.

The notes moved from the old frappesetup branch pc/handoff-ops-release (AJA-2454). The old
repository kept the code under a "backend/" folder; this repository keeps it at the root. The
test checks that:

- every operations note is in docs/handoff,
- every relative Markdown link in a handoff note opens an existing file,
- every repository path in backticks in an operations note exists,
- no operations note uses the old "backend/" prefix,
- no operations note names a commit code, because the code may not be on main.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "docs" / "handoff"
OPERATIONS_NOTES = (
    "capacity-monitoring.md",
    "data-assurance-gate.md",
    "release-and-deploy.md",
    "security-advisories.md",
    "staging-e2e.md",
)

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
CODE = re.compile(r"`([^`\n]+)`")
SHELL_BLOCK = re.compile(r"```sh\n(.*?)```", re.S)
TOP_FOLDERS = ("apps/", "contracts/", "deploy/", "dev/", "docs/", "e2e/", "identity/", "libs/")
COMMIT = re.compile(r"\b[0-9a-f]{7,40}\b")
OLD_PREFIX = re.compile(r"(?<![\w/.-])backend/[\w./-]*")


def relative_links(text):
    for target in LINK.findall(text):
        if "://" in target or target.startswith(("#", "mailto:")):
            continue
        yield target.split("#", 1)[0]


def code_paths(text):
    """Repository paths in backticks and in shell blocks, also inside commands."""
    spans = CODE.findall(text) + SHELL_BLOCK.findall(text)
    for word in " ".join(spans).split():
        if word.startswith(TOP_FOLDERS) and "<" not in word:
            yield word


class HandoffNotes(unittest.TestCase):
    def test_operations_notes_exist(self):
        for name in OPERATIONS_NOTES:
            with self.subTest(note=name):
                self.assertTrue((HANDOFF / name).is_file())

    def test_relative_links_open_existing_files(self):
        problems = []
        for note in sorted(HANDOFF.glob("*.md")):
            for target in relative_links(note.read_text()):
                if target and not (note.parent / target).exists():
                    problems.append(f"{note.name}: {target}")
        self.assertEqual(problems, [])

    def test_code_paths_exist_without_the_old_prefix(self):
        problems = []
        for name in OPERATIONS_NOTES:
            path = HANDOFF / name
            if not path.is_file():
                continue
            text = path.read_text()
            problems += [f"{name}: {word}" for word in OLD_PREFIX.findall(text)]
            for word in code_paths(text):
                if not (ROOT / word).exists():
                    problems.append(f"{name}: {word}")
        self.assertEqual(problems, [])

    def test_no_commit_codes(self):
        problems = []
        for name in OPERATIONS_NOTES:
            path = HANDOFF / name
            if path.is_file():
                problems += [f"{name}: {code}" for code in COMMIT.findall(path.read_text())]
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
