"""Path checks for the G-81 evidence note.

The note names code, test and document files. Each name must point to a file in this repository.
Paths under src/ belong to the frappesetup documentation repository. The note must say so.
"""

from __future__ import annotations

import pathlib
import re
import unittest

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
NOTE = PACKAGE / "G81-EVIDENCE.md"
# Inline code spans only. Fenced command blocks are not paths of this repository.
INLINE_CODE = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
OTHER_REPO_PREFIX = "src/"


def note_paths() -> list[str]:
    text = FENCE.sub("", NOTE.read_text(encoding="utf-8"))
    paths = []
    for span in INLINE_CODE.findall(text):
        if " " in span or span.startswith(("/", "~", "-")):
            continue
        if "/" in span or span.endswith((".py", ".md", ".json")):
            paths.append(span)
    return paths


class EvidenceNotePathTest(unittest.TestCase):
    def test_note_names_paths(self) -> None:
        self.assertGreater(len(note_paths()), 5)

    def test_no_path_keeps_the_old_backend_prefix(self) -> None:
        old = [path for path in note_paths() if path.startswith("backend/")]
        self.assertEqual(old, [])

    def test_every_local_path_exists(self) -> None:
        missing = []
        for path in note_paths():
            if path.startswith(OTHER_REPO_PREFIX):
                continue
            roots = (REPO, PACKAGE, PACKAGE / "identity_sync", PACKAGE / "tests")
            if not any((root / path).exists() for root in roots):
                missing.append(path)
        self.assertEqual(missing, [])

    def test_frappesetup_paths_are_marked(self) -> None:
        text = NOTE.read_text(encoding="utf-8")
        if any(path.startswith(OTHER_REPO_PREFIX) for path in note_paths()):
            self.assertTrue(
                "frappesetup" in text, "src/ paths are not marked as frappesetup paths"
            )

    def test_note_has_the_tenant_client_section(self) -> None:
        text = NOTE.read_text(encoding="utf-8")
        for needle in ("identity/keycloak/bin/create-tenant-client.py", "40 testin 40"):
            self.assertTrue(needle in text, f"note does not mention {needle}")


if __name__ == "__main__":
    unittest.main()
