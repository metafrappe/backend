"""Runbooks for backup, disaster recovery, rollback and alerts carry their required parts (G-114).

Every runbook in deploy/runbooks/ must have these sections, in this order:
purpose, owner, prerequisites, steps, verification.
- The owner section names a person by full name.
- The steps section is a numbered list.
- The verification section is not empty.
- Every repository path written in backticks exists, so a runbook cannot point at a removed script.
Design: G-114 in the decision site (src/data/requirements.json) and AJA-2375.
"""

import json
import re
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
RUNBOOKS = BACKEND / "deploy" / "runbooks"

# File name and the topic words the runbook must mention (G-114 scope).
REQUIRED = {
    "backup.md": ("RPO", "SHA256SUMS", "deploy/remote/backup"),
    "disaster-recovery.md": ("RTO", "tatbikat", "deploy/remote/restore"),
    "rollback.md": ("deploy/bin/rollback", "--restore-backup", "auto_rollback", "Keycloak"),
    "alerts.md": ("deploy/monitoring/prometheus/alerts.rules.json",),
}
SECTIONS = ("Amaç", "Görev sahibi", "Ön koşullar", "Adımlar", "Doğrulama")
OWNERS = ("Hüseyin Cengiz", "Asistan Hüseyin")
PATH_PREFIXES = ("deploy/", "docs/", "dev/")


def sections(text):
    """Return {heading: body} for level two headings."""
    parts = re.split(r"^## +(.+?)\s*$", text, flags=re.M)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


class RunbookTests(unittest.TestCase):
    def test_required_runbooks_exist(self):
        for name in REQUIRED:
            with self.subTest(runbook=name):
                self.assertTrue((RUNBOOKS / name).is_file(), f"missing {name}")

    def test_sections_in_order(self):
        for name in REQUIRED:
            path = RUNBOOKS / name
            if not path.is_file():
                self.fail(f"missing {name}")
            with self.subTest(runbook=name):
                found = list(sections(path.read_text(encoding="utf-8")))
                present = [s for s in found if s in SECTIONS]
                self.assertEqual(present, list(SECTIONS), f"{name}: sections {found}")

    def test_owner_steps_and_verification(self):
        for name in REQUIRED:
            path = RUNBOOKS / name
            if not path.is_file():
                self.fail(f"missing {name}")
            body = sections(path.read_text(encoding="utf-8"))
            with self.subTest(runbook=name, part="owner"):
                self.assertTrue(
                    any(owner in body.get("Görev sahibi", "") for owner in OWNERS),
                    f"{name}: owner must be one of {OWNERS}",
                )
            with self.subTest(runbook=name, part="steps"):
                self.assertRegex(body.get("Adımlar", ""), r"(?m)^1\. \S", f"{name}: no numbered step")
            with self.subTest(runbook=name, part="verification"):
                self.assertRegex(body.get("Doğrulama", ""), r"\S", f"{name}: empty verification")

    def test_topic_words(self):
        for name, words in REQUIRED.items():
            path = RUNBOOKS / name
            if not path.is_file():
                self.fail(f"missing {name}")
            text = path.read_text(encoding="utf-8")
            for word in words:
                with self.subTest(runbook=name, word=word):
                    self.assertIn(word, text)

    def test_repository_paths_exist(self):
        for path in sorted(RUNBOOKS.glob("*.md")):
            for ref in re.findall(r"`([^`\s]+)`", path.read_text(encoding="utf-8")):
                ref = ref.split("#", 1)[0]
                if not ref.startswith(PATH_PREFIXES) or "<" in ref:
                    continue
                with self.subTest(runbook=path.name, ref=ref):
                    self.assertTrue((BACKEND / ref).exists(), f"{path.name}: {ref} does not exist")

    def test_alert_runbook_covers_every_alert(self):
        """alerts.md names every alert, so a person paged by one finds its steps."""
        rules = BACKEND / "deploy" / "monitoring" / "prometheus" / "alerts.rules.json"
        runbook = RUNBOOKS / "alerts.md"
        if not rules.is_file() or not runbook.is_file():
            self.fail("missing alerts.rules.json or alerts.md")
        text = runbook.read_text(encoding="utf-8")
        for group in json.loads(rules.read_text(encoding="utf-8"))["groups"]:
            for rule in group["rules"]:
                if "alert" in rule:
                    with self.subTest(alert=rule["alert"]):
                        self.assertIn(f"`{rule['alert']}`", text)


if __name__ == "__main__":
    unittest.main()
