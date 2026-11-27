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
        'python3.14 -B dev/naming/check_new_names.py --base-ref "$BASE_SHA"',
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
        self.assertIn("-r dev/requirements-contract-tests.txt", lines[install])
        self.assertIn("openapi-spec-validator==", lines[install])
        first_test = next(i for i, line in enumerate(lines) if "unittest" in line)
        self.assertLess(install, first_test)

    def test_naming_gate_reads_the_target_baseline_from_the_target_commit(self):
        # A pull request must not grow the reviewed baseline (AJA-1721, B1). The target commit comes
        # from the event, never from pull request text, and git needs its history to read it.
        job = self.jobs["naming"]
        checkout = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@"))
        self.assertEqual(checkout["with"]["fetch-depth"], 0)
        step = next(s for s in job["steps"] if "check_new_names.py" in s.get("run", ""))
        self.assertEqual(
            step["env"]["BASE_SHA"],
            "${{ github.event.pull_request.base.sha || github.event.before }}",
        )
        self.assertNotIn("${{", step["run"])

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
