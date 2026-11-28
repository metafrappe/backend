"""The Python lock must record the digest of the current project manifests (AJA-2478).

This test does not import scans.py. scans.py still expects the old monorepo layout
(the checkout sits in a "backend/" folder of a parent repository). This test runs in
this repository on its own and rebuilds the same digest as scans.manifest_digest().
"""

import hashlib
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOCK = REPO / "dev/security/requirements.txt"
# scans.py hashes paths as the monorepo saw them: "backend/<path>".
PREFIX = "backend/"


def manifests():
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=REPO, text=True).split("\0")
    return sorted(PREFIX + path for path in files if Path(path).name == "pyproject.toml")


def digest(paths):
    value = hashlib.sha256()
    for path in paths:
        value.update(path.encode() + b"\0" + (REPO / path[len(PREFIX):]).read_bytes() + b"\0")
    return value.hexdigest()


class LockManifestTest(unittest.TestCase):
    def test_lock_records_current_manifest_digest(self):
        paths = manifests()
        self.assertTrue(paths, "No tracked pyproject.toml files.")
        expected = f"# Manifest SHA256: {digest(paths)}"
        self.assertIn(expected, LOCK.read_text().splitlines(),
                      "Python lock is stale. Regenerate it with dev/security/compile-lock.")


if __name__ == "__main__":
    unittest.main()
