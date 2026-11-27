"""G-152: every Keycloak extension in the image has one recommendation in the SPI decision draft."""

import json
import re
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
DECISION = BACKEND / "docs" / "decisions" / "0021-keycloak-spi-exceptions.md"
KEYCLOAK = BACKEND / "identity" / "keycloak"
RULE_KEY = "keycloak_spi_inventory"
RECOMMENDATIONS = {"keep_exception", "temporary_exception", "remove"}
REQUIRED_FIELDS = {"id", "spi", "provides", "source", "recommendation", "reason", "contract_test"}


def read_inventory() -> dict:
    blocks = re.findall(r"```json\n(.*?)```", DECISION.read_text(encoding="utf-8"), re.S)
    found = [json.loads(block) for block in blocks if RULE_KEY in block]
    if len(found) != 1:
        raise AssertionError(f"{DECISION.name} needs exactly one {RULE_KEY} block")
    return found[0][RULE_KEY]


def service_classes() -> set:
    """Provider classes the repository registers through META-INF/services files."""
    classes = set()
    for path in KEYCLOAK.rglob("META-INF/services/*"):
        if "/target/" in path.as_posix():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                classes.add(line)
    return classes


def image_provider_jars() -> set:
    """Jar names the production image places under /opt/keycloak/providers."""
    dockerfile = (KEYCLOAK / "Dockerfile").read_text(encoding="utf-8")
    return set(re.findall(r"/opt/keycloak/providers/([A-Za-z0-9._-]+\.jar)", dockerfile))


class KeycloakSpiDecisionTests(unittest.TestCase):
    def setUp(self):
        self.inventory = read_inventory()
        self.entries = self.inventory["extensions"]

    def test_decision_is_a_draft_for_the_pm(self):
        text = DECISION.read_text(encoding="utf-8")
        self.assertEqual(self.inventory["status"], "draft")
        self.assertEqual(self.inventory["decider"], "Team SAFe PM")
        self.assertIn("Durum: taslak", text)

    def test_every_entry_has_a_recommendation_and_reason(self):
        for entry in self.entries:
            with self.subTest(entry=entry.get("id")):
                self.assertEqual(set(entry) & REQUIRED_FIELDS, REQUIRED_FIELDS)
                self.assertIn(entry["recommendation"], RECOMMENDATIONS)
                self.assertGreaterEqual(len(entry["reason"].split()), 8)
                self.assertTrue(entry["contract_test"].strip())
        ids = [entry["id"] for entry in self.entries]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_registered_provider_class_is_listed(self):
        listed = {cls for entry in self.entries for cls in entry["provides"]}
        self.assertEqual(service_classes() - listed, set())
        self.assertEqual(listed - service_classes() - self._external_classes(), set())

    def _external_classes(self) -> set:
        return {
            cls
            for entry in self.entries
            if entry["source"] != "repository"
            for cls in entry["provides"]
        }

    def test_every_image_jar_is_listed(self):
        listed = {entry["jar"] for entry in self.entries if entry.get("jar")}
        self.assertEqual(image_provider_jars() - listed, set())

    def test_only_the_identity_sync_bridge_is_the_g152_exception(self):
        bridges = [entry for entry in self.entries if entry.get("g152_bridge")]
        self.assertEqual([entry["id"] for entry in bridges], ["identity-sync-event-listener"])
        self.assertEqual(bridges[0]["recommendation"], "keep_exception")

    def test_temporary_exceptions_name_an_exit(self):
        for entry in self.entries:
            if not entry.get("g152_bridge"):
                with self.subTest(entry=entry["id"]):
                    self.assertTrue(entry.get("exit", "").strip(), "non-bridge SPI needs an exit")

    def test_keycloak_version_matches_the_image(self):
        dockerfile = (KEYCLOAK / "Dockerfile").read_text(encoding="utf-8")
        version = re.search(r"ARG KEYCLOAK_VERSION=(\S+)", dockerfile).group(1)
        self.assertEqual(self.inventory["keycloak_version"], version)

    def test_drift_report_and_contract_test_sections_exist(self):
        text = DECISION.read_text(encoding="utf-8")
        for heading in ("## Realm fark raporu", "## Alt sürüm sözleşme testi", "## Karar için sorular"):
            self.assertIn(heading, text)
        self.assertIn("--import-realm", text)
        self.assertIn("test_press_realm_drift.py", text)

    def test_decision_index_files_point_to_the_draft(self):
        older = (BACKEND / "docs" / "decisions" / "0003-keycloak-extensions.md").read_text(encoding="utf-8")
        self.assertIn("0021-keycloak-spi-exceptions.md", older)


if __name__ == "__main__":
    unittest.main()
