"""The DNS, offsite backup and secrets handoff notes must match main.

The notes moved from the old frappesetup branch pc/b9f-devir-notu (AJA-2455). The old
repository kept the code under a "backend/" folder; this repository keeps it at the root.
The test checks that:

- every note is in docs/handoff,
- every relative Markdown link in a note opens an existing file,
- every repository path in backticks in a note exists,
- no note uses the old "backend/" prefix,
- no note names a commit code or a branch, because they may not be on main,
- the DNS note uses the login address form of docs/dagitim/ortamlar.md.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "docs" / "handoff"
NOTES = ("dns-records.md", "offsite-backup.md", "secrets-management.md")

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
CODE = re.compile(r"`([^`\n]+)`")
TOP_FOLDERS = ("apps/", "contracts/", "deploy/", "dev/", "docs/", "e2e/", "identity/", "libs/")
COMMIT = re.compile(r"\b[0-9a-f]{7,40}\b")
BRANCH = re.compile(r"\b(?:pc|feat|fix)/[\w.-]+")
OLD_PREFIX = re.compile(r"(?<![\w/.-])backend/[\w./-]*")


def read(name):
    path = HANDOFF / name
    return path.read_text() if path.is_file() else None


class DnsBackupSecretsNotes(unittest.TestCase):
    def test_notes_exist(self):
        for name in NOTES:
            with self.subTest(note=name):
                self.assertTrue((HANDOFF / name).is_file())

    def test_relative_links_open_existing_files(self):
        problems = []
        for name in NOTES:
            text = read(name)
            if text is None:
                continue
            for target in LINK.findall(text):
                if "://" in target or target.startswith(("#", "mailto:")):
                    continue
                target = target.split("#", 1)[0]
                if target and not (HANDOFF / target).exists():
                    problems.append(f"{name}: {target}")
        self.assertEqual(problems, [])

    def test_code_paths_exist_without_the_old_prefix(self):
        problems = []
        for name in NOTES:
            text = read(name)
            if text is None:
                continue
            problems += [f"{name}: {word}" for word in OLD_PREFIX.findall(text)]
            for span in CODE.findall(text):
                for word in span.split():
                    if word.startswith(TOP_FOLDERS) and "<" not in word:
                        if not (ROOT / word).exists():
                            problems.append(f"{name}: {word}")
        self.assertEqual(problems, [])

    def test_no_commit_codes_or_branch_names(self):
        problems = []
        for name in NOTES:
            text = read(name)
            if text is not None:
                problems += [f"{name}: {code}" for code in COMMIT.findall(text)]
                problems += [f"{name}: {branch}" for branch in BRANCH.findall(text)]
        self.assertEqual(problems, [])

    def test_dns_note_uses_the_login_address_form(self):
        text = read("dns-records.md")
        self.assertIsNotNone(text)
        self.assertIn("api.login.<ortam tabanı>", text)
        self.assertIn("api.login.<ortam tabanı>", (ROOT / "docs/dagitim/ortamlar.md").read_text())


if __name__ == "__main__":
    unittest.main()
