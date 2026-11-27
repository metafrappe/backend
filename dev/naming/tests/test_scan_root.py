"""The naming gate scans the repository root and refuses an empty scan."""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECK = Path(__file__).resolve().parents[1] / "check_names.py"
SCANNED = re.compile(r"Scanned (\d+) files\.")


def run_check(root, *arguments):
    return subprocess.run(
        [sys.executable, "-B", str(CHECK), "--root", str(root), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )


def scanned(result):
    match = SCANNED.search(result.stderr)
    return int(match[1]) if match else None


class ScanRootTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        # The folder name must not matter, not even the old "backend" name.
        self.root = Path(workspace.name) / "backend"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)], check=True)

    def write(self, relative, contents):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", relative], check=True)

    def test_files_at_repository_root_are_scanned(self):
        self.write("libs/sample.py", "total = 1\n")
        self.write("identity/view.ts", "const total = 1;\n")
        result = run_check(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(scanned(result), 2, result.stderr)

    def test_root_finding_is_reported(self):
        self.write("libs/sample.py", "giris = 1\n")
        result = run_check(self.root)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("libs/sample.py:1 [turkish-name]", result.stdout)

    def test_empty_scan_fails(self):
        result = run_check(self.root)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("no files", result.stderr.lower())

    def test_real_repository_scan_is_not_empty(self):
        result = run_check(CHECK.parents[2])
        self.assertGreater(scanned(result) or 0, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
