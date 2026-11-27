"""The naming gate fails only for findings that are not in the reviewed baseline."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

NAMING = Path(__file__).resolve().parents[1]
SCRIPT = NAMING / "check_new_names.py"
BASELINE = NAMING / "baseline.json"


def finding(path, line, rule="discouraged-name", message="Use a descriptive name in place of 'data'."):
    return {"path": path, "line": line, "rule": rule, "message": message}


class BaselineGateTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def write(self, name, data):
        path = self.folder / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def run_gate(self, findings, baseline, *extra):
        process = subprocess.run(
            [
                sys.executable, "-B", str(SCRIPT),
                "--findings", str(self.write("findings.json", findings)),
                "--baseline", str(self.write("baseline.json", baseline)),
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return process

    def baseline_from(self, findings):
        self.write("findings.json", findings)
        target = self.folder / "baseline.json"
        process = subprocess.run(
            [
                sys.executable, "-B", str(SCRIPT),
                "--findings", str(self.folder / "findings.json"),
                "--baseline", str(target),
                "--update",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("1", process.stdout)
        return json.loads(target.read_text(encoding="utf-8"))

    def test_known_findings_pass_even_when_lines_move(self):
        baseline = self.baseline_from([finding("apps/a.py", 3)])
        process = self.run_gate([finding("apps/a.py", 40)], baseline)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_a_new_finding_fails_the_gate(self):
        baseline = self.baseline_from([finding("apps/a.py", 3)])
        process = self.run_gate([finding("apps/a.py", 3), finding("apps/b.py", 7)], baseline)
        self.assertEqual(process.returncode, 1)
        self.assertIn("apps/b.py:7", process.stdout)

    def test_a_second_copy_of_a_known_finding_fails_the_gate(self):
        baseline = self.baseline_from([finding("apps/a.py", 3)])
        process = self.run_gate([finding("apps/a.py", 3), finding("apps/a.py", 9)], baseline)
        self.assertEqual(process.returncode, 1)
        self.assertIn("apps/a.py:3", process.stdout)
        self.assertIn("apps/a.py:9", process.stdout)

    def test_a_fixed_finding_passes_and_asks_for_a_baseline_update(self):
        baseline = self.baseline_from([finding("apps/a.py", 3), finding("apps/b.py", 7)])
        process = self.run_gate([finding("apps/a.py", 3)], baseline)
        self.assertEqual(process.returncode, 0)
        self.assertIn("apps/b.py", process.stdout)
        self.assertIn("--update", process.stdout)

    def test_a_broken_baseline_fails(self):
        process = self.run_gate([], {"not": "a list"})
        self.assertEqual(process.returncode, 2)


class RepositoryBaselineTests(unittest.TestCase):
    def test_baseline_is_sorted_and_without_line_numbers(self):
        entries = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertTrue(entries)
        keys = [(e["path"], e["rule"], e["message"]) for e in entries]
        self.assertEqual(keys, sorted(set(keys)))
        for entry in entries:
            self.assertEqual(set(entry), {"path", "rule", "message", "count"})
            self.assertGreater(entry["count"], 0)

    @unittest.skipIf(sys.version_info < (3, 14), "check_names.py reads Python 3.14 syntax")
    def test_repository_has_no_new_naming_findings(self):
        process = subprocess.run(
            [sys.executable, "-B", str(SCRIPT)], capture_output=True, text=True, check=False
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)


if __name__ == "__main__":
    unittest.main()
