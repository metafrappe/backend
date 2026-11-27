"""Check that the GitHub CI runs the eight backend gates and that build-and-test waits for them."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

try:
    import yaml
except ModuleNotFoundError as error:  # The dev tests job installs PyYAML. A skip there is a failure.
    raise unittest.SkipTest("Install dev/requirements-contract-tests.txt for the CI workflow test") from error


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ci.yml"

# Each gate: job id -> commands that must appear as whole lines of `run` steps.
GATES = {
    "module-boundaries": ("dev/bin/module-boundaries",),
    "security": (
        "dev/bin/security-audit",
        "python3.12 -B -m unittest discover -s dev/security",
    ),
    "ai-readiness": (
        "dev/bin/ai-readiness --self-test",
        "dev/bin/ai-readiness",
    ),
    "dev-tests": ("python3.14 -B -m unittest discover -s dev/tests",),
    "naming": (
        "python3.14 -B -m unittest discover -s dev/naming/tests",
        "python3.14 -B dev/naming/check_new_names.py",
    ),
    "deploy-tests": ("python3.14 -I -m unittest discover -s deploy/tests",),
    "press-ai": ("python3.14 -I -m unittest discover -s tools/press-ai/tests",),
    "contract": (
        "python3.14 -I tools/press-ai/server.py check-contract",
        "python3.14 -B -m unittest discover -s dev/tests -p test_gateway_openapi.py",
        "python3.14 -B -m unittest discover -s dev/press -p test_openapi_contract.py",
        "python3.14 -B -m unittest discover -s dev/mobile_test_app/tests -p test_contract_examples.py",
    ),
}
AGGREGATE = "build-and-test"


def run_lines(step):
    return [line.strip() for line in step.get("run", "").splitlines() if line.strip()]


PIP_INSTALL = re.compile(r"\bpip3?(?:\.\d+)? install\b|\b-m pip install\b")
HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}\b")


def pip_install_problems(lines):
    """Return the pip install lines that do not install only from hashed lock files.

    A good line uses --require-hashes and names only lock files with -r. It names no package.
    """
    problems = []
    for line in lines:
        if not PIP_INSTALL.search(line):
            continue
        words = line.split()
        tail = words[words.index("install") + 1:]
        files, extra, i = [], [], 0
        while i < len(tail):
            word = tail[i]
            if word in ("-r", "--requirement") and i + 1 < len(tail):
                files.append(tail[i + 1])
                i += 2
                continue
            if word != "--require-hashes":
                extra.append(word)
            i += 1
        if "--require-hashes" not in tail or not files or extra:
            problems.append(line)
    return problems


def lock_problems(text):
    """Return the requirements in a lock file that have no exact version or no sha256 hash."""
    problems = []
    entries = re.split(r"\n(?=\S)", "\n".join(
        line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ))
    for entry in entries:
        name = entry.split("\n", 1)[0].strip()
        if not entry.strip():
            continue
        if not re.match(r"^[A-Za-z0-9._-]+(\[[^]]+\])?==[^\s;\\]+", name) or not HASH.search(entry):
            problems.append(name)
    return problems


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")
        self.workflow = yaml.safe_load(self.text)
        self.jobs = self.workflow["jobs"]

    def test_runs_on_pull_requests_and_main_pushes(self):
        # PyYAML reads the bare key `on` as True.
        triggers = self.workflow.get("on", self.workflow.get(True))
        self.assertIn("pull_request", triggers)
        self.assertEqual(triggers["push"]["branches"], ["main"])

    def test_every_gate_is_its_own_job_and_runs_unconditionally(self):
        for job_id, commands in GATES.items():
            with self.subTest(job=job_id):
                self.assertIn(job_id, self.jobs)
                job = self.jobs[job_id]
                self.assertNotIn("if", job)
                self.assertNotIn("strategy", job)
                self.assertFalse(job.get("continue-on-error"))
                lines = {}
                for step in job["steps"]:
                    self.assertNotIn("if", step)
                    self.assertFalse(step.get("continue-on-error"))
                    for line in run_lines(step):
                        lines[line] = step
                for command in commands:
                    self.assertIn(command, lines)

    def test_only_gates_and_the_aggregate_are_jobs(self):
        self.assertEqual(set(self.jobs), {*GATES, AGGREGATE})

    def test_contract_job_installs_the_validators_before_the_tests(self):
        # Without these packages the OpenAPI tests skip and look green.
        lines = [line for step in self.jobs["contract"]["steps"] for line in run_lines(step)]
        install = next(i for i, line in enumerate(lines) if "pip install" in line)
        self.assertIn("-r dev/requirements-openapi-tests.txt", lines[install])
        lock = (ROOT / "dev/requirements-openapi-tests.txt").read_text(encoding="utf-8")
        for package in ("jsonschema==", "pyyaml==", "openapi-spec-validator==", "referencing==", "rpds-py=="):
            self.assertRegex(lock, rf"(?m)^{re.escape(package)}")
        first_test = next(i for i, line in enumerate(lines) if "unittest" in line)
        self.assertLess(install, first_test)

    def test_every_pip_install_uses_a_hashed_lock_file(self):
        # SecOps finding B3: each package and each dependency is pinned with a sha256 hash.
        lines = [line for job in self.jobs.values() for step in job["steps"] for line in run_lines(step)]
        installs = [line for line in lines if PIP_INSTALL.search(line)]
        self.assertTrue(installs)
        self.assertEqual(pip_install_problems(lines), [])
        for line in installs:
            words = line.split()
            for lock in (words[i + 1] for i, word in enumerate(words) if word in ("-r", "--requirement")):
                with self.subTest(lock=lock):
                    text = (ROOT / lock).read_text(encoding="utf-8")
                    self.assertIn("Regenerate", text.split("\n", 3)[0] + text.split("\n", 3)[1])
                    self.assertEqual(lock_problems(text), [])

    def test_the_pip_install_check_rejects_hashless_lines(self):
        bad = (
            "python3.14 -m pip install -r dev/requirements-contract-tests.txt",
            "python3.14 -m pip install uv==0.13.9",
            "pip install --require-hashes -r dev/a.txt openapi-spec-validator==0.7.2",
            "python3 -m pip install --require-hashes requests==2.0",
        )
        for line in bad:
            with self.subTest(line=line):
                self.assertEqual(pip_install_problems([line]), [line])
        good = "python3.14 -m pip install --require-hashes -r dev/a.txt -r dev/b.txt"
        self.assertEqual(pip_install_problems([good, "echo pip"]), [])
        hashed = "a==1.0 \\\n    --hash=sha256:" + "0" * 64 + "\n"
        self.assertEqual(lock_problems(hashed), [])
        self.assertEqual(lock_problems("a==1.0\n"), ["a==1.0"])
        self.assertEqual(lock_problems("a>=1.0 --hash=sha256:" + "0" * 64 + "\n"), ["a>=1.0 --hash=sha256:" + "0" * 64])

    def test_aggregate_keeps_its_name_and_always_runs(self):
        aggregate = self.jobs[AGGREGATE]
        self.assertEqual(aggregate.get("name", AGGREGATE), AGGREGATE)
        self.assertIn(aggregate["if"], ("always()", "${{ always() }}"))
        self.assertEqual(set(aggregate["needs"]), set(GATES))

    @unittest.skipIf(shutil.which("bash") is None, "bash is not installed")
    def test_aggregate_fails_unless_every_gate_succeeded(self):
        aggregate = self.jobs[AGGREGATE]
        step = next(s for s in aggregate["steps"] if "RESULTS" in s.get("env", {}))
        self.assertEqual(step["env"]["RESULTS"], "${{ join(needs.*.result, ' ') }}")
        others = ["success"] * (len(GATES) - 1)
        for gate_result in ("success", "failure", "cancelled", "skipped"):
            for position in (0, len(others)):
                with self.subTest(result=gate_result, position=position):
                    results = list(others)
                    results.insert(position, gate_result)
                    run = subprocess.run(
                        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
                        env={**os.environ, "RESULTS": " ".join(results)},
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(run.returncode, 0 if gate_result == "success" else 1)
        with self.subTest(result="empty"):
            run = subprocess.run(
                ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
                env={**os.environ, "RESULTS": ""},
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(run.returncode, 0)

    def test_actions_use_full_commit_hashes_with_a_version_comment(self):
        uses = re.findall(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$", self.text, flags=re.MULTILINE)
        self.assertTrue(uses)
        for action, rest in uses:
            with self.subTest(action=action):
                if action.startswith("./"):
                    continue
                self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$")
                self.assertRegex(rest, r"#\s*v\d")


if __name__ == "__main__":
    unittest.main()
