"""The staging, Press provisioning and Keycloak hardening handoff notes are in the repository.

The three notes moved from the old site repository (AJA-2456). They live in docs/handoff/ without a
"backend/" prefix. Every relative link in them opens a file in this repository. They name no real
person, no branch and no commit code: those go stale and the release gate forbids person names.

The Press server setup steps are written once, in dev/press/provisioning-handoff.md. The staging
Press note links to that note instead of repeating the steps, and the local note links back.
"""

import importlib.util
import re
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]
BACKEND = DEPLOY.parent
HANDOFF = BACKEND / "docs" / "handoff"
NOTES = {
    name: HANDOFF / name
    for name in ("staging-server.md", "press-provisioning.md", "keycloak-hardening.md")
}
LOCAL_PRESS_NOTE = BACKEND / "dev" / "press" / "provisioning-handoff.md"
RESIDUE = BACKEND / "dev" / "tests" / "test_release_residue.py"

LINK = re.compile(r"\]\(([^)\s]+)\)")
# A Git commit code or a work branch name; neither belongs in a handoff note.
COMMIT_CODE = re.compile(r"(?<![\w-])[0-9a-f]{7,40}(?![\w-])")
BRANCH = re.compile(r"\b(?:pc|paperclip|feature|fix)/[\w./-]+")
# The setup flow that dev/press/provisioning-handoff.md owns.
SETUP_FLOW = ("Setup Server", "Ansible Play")


def residue_scanner():
    spec = importlib.util.spec_from_file_location("release_residue", RESIDUE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.scan_text


def local_links(path):
    """Relative link targets of a note, without the #anchor part."""
    targets = []
    for target in LINK.findall(path.read_text()):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        targets.append(target.split("#", 1)[0])
    return targets


class HandoffNotes(unittest.TestCase):
    def test_notes_are_in_docs_handoff(self):
        for name, path in NOTES.items():
            with self.subTest(note=name):
                self.assertTrue(path.is_file(), f"{path} is missing")

    def test_every_local_link_opens_a_file(self):
        for name, path in NOTES.items():
            for target in local_links(path):
                with self.subTest(note=name, link=target):
                    resolved = (path.parent / target).resolve()
                    self.assertTrue(resolved.is_file(), f"{name}: {target} does not open a file")
                    self.assertTrue(resolved.is_relative_to(BACKEND), f"{name}: {target} leaves the repository")

    def test_notes_name_no_branch_or_commit_code(self):
        for name, path in NOTES.items():
            text = path.read_text()
            with self.subTest(note=name):
                self.assertEqual(COMMIT_CODE.findall(text), [])
                self.assertEqual(BRANCH.findall(text), [])

    def test_notes_name_no_real_person(self):
        scan = residue_scanner()
        for name, path in NOTES.items():
            with self.subTest(note=name):
                self.assertEqual(scan(name, path.read_text()), [])


class PressSetupWrittenOnce(unittest.TestCase):
    def test_staging_press_note_links_to_the_local_note(self):
        note = NOTES["press-provisioning.md"]
        targets = {(note.parent / target).resolve() for target in local_links(note)}
        self.assertIn(LOCAL_PRESS_NOTE.resolve(), targets)

    def test_staging_press_note_does_not_repeat_the_setup_flow(self):
        text = NOTES["press-provisioning.md"].read_text()
        for phrase in SETUP_FLOW:
            self.assertNotIn(phrase, text)

    def test_local_note_links_to_the_staging_press_note(self):
        targets = {(LOCAL_PRESS_NOTE.parent / target).resolve() for target in local_links(LOCAL_PRESS_NOTE)}
        self.assertIn(NOTES["press-provisioning.md"].resolve(), targets)


if __name__ == "__main__":
    unittest.main()
