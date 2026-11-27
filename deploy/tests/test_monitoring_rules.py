"""Monitoring, alert, error tracking and capacity rule files are valid and complete (G-113).

The rule files live in deploy/monitoring/. Prometheus reads rule files as YAML, and JSON is
valid YAML, so the files are JSON: the test reads them with the standard library only.
- Every Prometheus rule has the fields Prometheus needs, and every alert names its severity
  and a runbook that exists.
- The alerts G-113 asks for are present. Example: a disk space alert.
- The error tracking file names the Frappe Sentry variables and holds no secret value.
- When promtool is on PATH, the test also runs "promtool check rules". CI does not need it.
Design: G-113 in the decision site (src/data/requirements.json) and AJA-2375.
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
MONITORING = BACKEND / "deploy" / "monitoring"
RULE_FILES = (
    MONITORING / "prometheus" / "alerts.rules.json",
    MONITORING / "prometheus" / "capacity.rules.json",
)
UPTIME = MONITORING / "uptime-checks.json"
ERRORS = MONITORING / "error-tracking.json"

REQUIRED_ALERTS = {
    "InstanceDown",
    "UptimeProbeFailed",
    "CertificateExpiresSoon",
    "DiskSpaceLow",
    "DiskSpaceCritical",
    "MemoryLow",
    "ContainerRestarting",
    "BackupMissing",
    "OffsiteBackupMissing",
    "AvailabilityBudgetBurn",
    "DiskWillFillSoon",
    "CpuSaturated",
}
SEVERITIES = {"warning", "critical"}
DURATION = re.compile(r"^([0-9]+(ms|s|m|h|d|w|y))+$")
RECORD_NAME = re.compile(r"^[a-z_]+:[a-z0-9_]+:[a-z0-9_]+$")
SECRET_LIKE = re.compile(r"(https?://[^\s\"/]+@|password\s*[:=]|token\s*[:=]|secret\s*[:=])", re.I)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def all_rules():
    for path in RULE_FILES:
        for group in load(path)["groups"]:
            for rule in group["rules"]:
                yield path, group, rule


def balanced(expr):
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    in_string = None
    for char in expr:
        if in_string:
            if char == in_string:
                in_string = None
            continue
        if char in "\"'":
            in_string = char
        elif char in "([{":
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                return False
    return not stack and in_string is None


class RuleFileTests(unittest.TestCase):
    def test_files_exist_and_parse(self):
        for path in (*RULE_FILES, UPTIME, ERRORS):
            with self.subTest(file=path.name):
                self.assertTrue(path.is_file(), f"missing {path}")
                load(path)

    def test_rule_structure(self):
        groups = set()
        names = set()
        for path in RULE_FILES:
            data = load(path)
            self.assertEqual(set(data), {"groups"}, path.name)
            self.assertTrue(data["groups"], f"{path.name}: no groups")
            for group in data["groups"]:
                self.assertNotIn(group["name"], groups, "group names must be unique")
                groups.add(group["name"])
                self.assertTrue(group["rules"], f"{group['name']}: no rules")
        for path, group, rule in all_rules():
            label = rule.get("alert") or rule.get("record")
            with self.subTest(file=path.name, rule=label):
                self.assertEqual(("alert" in rule) + ("record" in rule), 1, "alert or record, not both")
                self.assertIsInstance(rule.get("expr"), str)
                self.assertTrue(rule["expr"].strip())
                self.assertTrue(balanced(rule["expr"]), f"unbalanced expr: {rule['expr']}")
                if "for" in rule:
                    self.assertRegex(rule["for"], DURATION)
                if "record" in rule:
                    self.assertRegex(rule["record"], RECORD_NAME)
                    self.assertNotIn("annotations", rule)
                    continue
                self.assertNotIn(rule["alert"], names, "alert names must be unique")
                names.add(rule["alert"])
                self.assertIn(rule.get("labels", {}).get("severity"), SEVERITIES)
                notes = rule.get("annotations", {})
                for key in ("summary", "description", "runbook_url"):
                    self.assertTrue(notes.get(key), f"missing annotation {key}")
                target = notes["runbook_url"].split("#", 1)[0]
                self.assertRegex(target, r"^deploy/runbooks/[a-z-]+\.md$")
                self.assertTrue((BACKEND / target).is_file(), f"runbook {target} does not exist")

    def test_required_alerts(self):
        present = {rule["alert"] for _, _, rule in all_rules() if "alert" in rule}
        self.assertEqual(REQUIRED_ALERTS - present, set())

    def test_disk_alerts_read_free_space(self):
        rules = {rule.get("alert"): rule for _, _, rule in all_rules()}
        for name in ("DiskSpaceLow", "DiskSpaceCritical", "DiskWillFillSoon"):
            with self.subTest(alert=name):
                self.assertIn("node_filesystem_avail_bytes", rules[name]["expr"])
        self.assertEqual(rules["DiskSpaceCritical"]["labels"]["severity"], "critical")

    def test_capacity_has_recording_rules(self):
        records = [r for p, _, r in all_rules() if p.name == "capacity.rules.json" and "record" in r]
        self.assertTrue(records, "capacity.rules.json needs recording rules")

    def test_uptime_checks(self):
        data = load(UPTIME)
        checks = data["checks"]
        services = {check["service"] for check in checks}
        self.assertTrue({"tenant-frontend", "keycloak"} <= services, services)
        names = [check["name"] for check in checks]
        self.assertEqual(len(names), len(set(names)), "check names must be unique")
        for check in checks:
            with self.subTest(check=check["name"]):
                self.assertTrue(check["path"].startswith("/"), "path only, the host comes from the environment")
                self.assertIsInstance(check["expect_status"], int)
                self.assertRegex(check["interval"], DURATION)

    def test_error_tracking(self):
        data = load(ERRORS)
        names = {item["name"] for item in data["environment"]}
        self.assertTrue({"FRAPPE_SENTRY_DSN", "SENTRY_ENVIRONMENT"} <= names, names)
        for item in data["environment"]:
            with self.subTest(variable=item["name"]):
                self.assertNotIn("value", item, "values live on the server, never in the repository")
        scrub = {field.lower() for field in data["scrub"]}
        self.assertTrue({"authorization", "cookie", "email"} <= scrub, scrub)
        self.assertIn("X-Request-Id", data["shared_tags"])

    def test_no_secret_values(self):
        for path in MONITORING.rglob("*.json"):
            with self.subTest(file=str(path.relative_to(BACKEND))):
                self.assertIsNone(SECRET_LIKE.search(path.read_text(encoding="utf-8")))

    @unittest.skipUnless(shutil.which("promtool"), "promtool is not installed")
    def test_promtool(self):
        result = subprocess.run(
            ["promtool", "check", "rules", *map(str, RULE_FILES)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
