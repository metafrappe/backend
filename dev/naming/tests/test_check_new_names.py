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
        self.assertIn(f"Wrote {len(findings)} findings", process.stdout)
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

    # B2: a fixed finding left in the baseline would hide a new finding at the same place later.
    def test_a_fixed_finding_left_in_the_baseline_fails_and_asks_to_shrink_it(self):
        baseline = self.baseline_from([finding("apps/a.py", 3), finding("apps/b.py", 7)])
        process = self.run_gate([finding("apps/a.py", 3)], baseline)
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertIn("apps/b.py", process.stdout)
        self.assertIn("Shrink the baseline", process.stdout)
        self.assertIn("--update", process.stdout)

    def test_one_of_two_copies_fixed_fails_too(self):
        baseline = self.baseline_from([finding("apps/a.py", 3), finding("apps/a.py", 9)])
        process = self.run_gate([finding("apps/a.py", 3)], baseline)
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertIn("Shrink the baseline", process.stdout)

    # B1: a pull request must not grow the baseline that the target branch reviewed.
    def test_an_entry_missing_from_the_target_baseline_fails(self):
        base = self.baseline_from([finding("apps/a.py", 3)])
        baseline = base + [{"path": "apps/b.py", "rule": "discouraged-name",
                            "message": "Use a descriptive name in place of 'data'.", "count": 1}]
        process = self.run_gate(
            [finding("apps/a.py", 3), finding("apps/b.py", 7)], baseline,
            "--base-baseline", str(self.write("base.json", base)),
        )
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertIn("baseline grew", process.stdout)
        self.assertIn("apps/b.py", process.stdout)

    def test_a_higher_count_than_the_target_baseline_fails(self):
        base = self.baseline_from([finding("apps/a.py", 3)])
        baseline = [dict(base[0], count=2)]
        process = self.run_gate(
            [finding("apps/a.py", 3), finding("apps/a.py", 9)], baseline,
            "--base-baseline", str(self.write("base.json", base)),
        )
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertIn("baseline grew", process.stdout)

    def test_a_baseline_that_only_shrinks_without_fixed_findings_passes(self):
        base = self.baseline_from([finding("apps/a.py", 3), finding("apps/b.py", 7)])
        baseline = self.baseline_from([finding("apps/a.py", 3)])
        process = self.run_gate(
            [finding("apps/a.py", 3)], baseline,
            "--base-baseline", str(self.write("base.json", base)),
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_a_broken_target_baseline_fails(self):
        baseline = self.baseline_from([finding("apps/a.py", 3)])
        process = self.run_gate(
            [finding("apps/a.py", 3)], baseline,
            "--base-baseline", str(self.write("base.json", {"not": "a list"})),
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("Naming gate could not finish", process.stderr)

    def test_a_broken_baseline_fails(self):
        process = self.run_gate([], {"not": "a list"})
        self.assertEqual(process.returncode, 2)


def git(folder, *arguments):
    return subprocess.run(
        ["git", "-C", str(folder), "-c", "core.hooksPath=/dev/null", *arguments],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


class BaseRefTests(unittest.TestCase):
    """CI reads the target baseline with git from the target commit, not from the pull request."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "test")
        git(self.root, "config", "user.email", "test@example.invalid")
        (self.root / "findings.json").write_text(json.dumps([finding("apps/a.py", 3)]), encoding="utf-8")

    def commit(self, baseline):
        target = self.root / "dev/naming/baseline.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(baseline), encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "baseline")
        return git(self.root, "rev-parse", "HEAD")

    def run_gate(self, *extra):
        return subprocess.run(
            [
                sys.executable, "-B", str(SCRIPT), "--root", str(self.root),
                "--findings", str(self.root / "findings.json"),
                "--baseline", str(self.root / "dev/naming/baseline.json"), *extra,
            ],
            capture_output=True, text=True, check=False,
        )

    def entry(self, path):
        return {"path": path, "rule": "discouraged-name",
                "message": "Use a descriptive name in place of 'data'.", "count": 1}

    def test_a_grown_baseline_fails_against_the_target_commit(self):
        base = self.commit([self.entry("apps/a.py")])
        self.commit([self.entry("apps/a.py"), self.entry("apps/b.py")])
        (self.root / "findings.json").write_text(
            json.dumps([finding("apps/a.py", 3), finding("apps/b.py", 7)]), encoding="utf-8")
        process = self.run_gate("--base-ref", base)
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertIn("baseline grew", process.stdout)

    def test_the_same_baseline_passes_against_the_target_commit(self):
        base = self.commit([self.entry("apps/a.py")])
        process = self.run_gate("--base-ref", base)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_a_target_without_a_baseline_skips_the_growth_check(self):
        (self.root / "README").write_text("x", encoding="utf-8")
        git(self.root, "add", "README")
        git(self.root, "commit", "-q", "-m", "start")
        base = git(self.root, "rev-parse", "HEAD")
        self.commit([self.entry("apps/a.py")])
        process = self.run_gate("--base-ref", base)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("has no baseline", process.stdout)

    def test_an_unknown_target_commit_fails(self):
        self.commit([self.entry("apps/a.py")])
        process = self.run_gate("--base-ref", "0" * 40)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertIn("Naming gate could not finish", process.stderr)


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
