"""G-142: security advisory sources, decision records and the emergency patch guide.

Every advisory decision is a JSON file in advisories/records/. A record with an empty
required field, an unknown decision or a component that is not on the watched source
list must fail here.
"""

import json
import tempfile
import unittest
from pathlib import Path

import advisory_records as advisories

HERE = Path(__file__).resolve().parent
FOLDER = HERE / "advisories"

REQUIRED_COMPONENTS = {
    "frappe", "erpnext", "hrms", "press", "agent", "crm", "helpdesk",
    "keycloak", "hocuspocus", "frontend-dependencies",
}


def valid_record(**changes):
    record = {
        "advisory_id": "GHSA-xxxx-xxxx-xxxx",
        "component": "frappe",
        "severity": "high",
        "known_exploited": False,
        "deployed_version": "16.0.0",
        "affected_range": "<16.0.1",
        "feature_enabled": "yes",
        "attack_precondition": "Signed-in desk user",
        "fixed_version": "16.0.1",
        "decision": "apply_now",
        "rationale": "Deployed version is affected and the feature is enabled.",
        "evidence": {"version": "", "configuration": ""},
        "decided_by": "DevOps owner",
        "decided_on": "2026-11-28",
    }
    record.update(changes)
    return record


class SourceListTests(unittest.TestCase):
    def test_every_required_component_is_watched(self):
        sources = advisories.load_sources()
        self.assertTrue(REQUIRED_COMPONENTS <= set(sources))

    def test_every_source_names_where_to_look(self):
        for component, source in advisories.load_sources().items():
            with self.subTest(component=component):
                self.assertTrue(source["advisory_feeds"])
                self.assertTrue(source["release_notes"])
                for url in source["advisory_feeds"] + [source["release_notes"]]:
                    self.assertTrue(url.startswith("https://"), url)


class TemplateTests(unittest.TestCase):
    def test_template_has_every_field(self):
        template = json.loads((FOLDER / "template.json").read_text())
        self.assertEqual(set(template), set(advisories.FIELDS))

    def test_empty_template_is_not_a_valid_record(self):
        template = json.loads((FOLDER / "template.json").read_text())
        self.assertTrue(advisories.validate(template))


class RecordTests(unittest.TestCase):
    def errors(self, record):
        return advisories.validate(record, advisories.load_sources())

    def test_complete_record_passes(self):
        self.assertEqual(self.errors(valid_record()), [])

    def test_empty_required_field_fails(self):
        for field in ("advisory_id", "deployed_version", "affected_range",
                      "attack_precondition", "fixed_version", "rationale", "decided_by"):
            with self.subTest(field=field):
                self.assertTrue(self.errors(valid_record(**{field: "  "})))

    def test_missing_field_fails(self):
        record = valid_record()
        del record["attack_precondition"]
        self.assertTrue(self.errors(record))

    def test_unknown_field_fails(self):
        self.assertTrue(self.errors(valid_record(decison="apply_now")))

    def test_decision_must_be_known(self):
        self.assertTrue(self.errors(valid_record(decision="later")))
        for decision in ("apply_now", "schedule"):
            with self.subTest(decision=decision):
                self.assertEqual(self.errors(valid_record(decision=decision)), [])

    def test_feature_state_must_be_known(self):
        self.assertTrue(self.errors(valid_record(feature_enabled="maybe")))

    def test_severity_must_be_known(self):
        self.assertTrue(self.errors(valid_record(severity="urgent")))

    def test_known_exploited_must_be_boolean(self):
        self.assertTrue(self.errors(valid_record(known_exploited="no")))

    def test_component_must_be_watched(self):
        self.assertTrue(self.errors(valid_record(component="unknown-app")))

    def test_decision_date_must_be_a_date(self):
        self.assertTrue(self.errors(valid_record(decided_on="28.11.2026")))

    def test_not_applicable_needs_version_and_configuration_evidence(self):
        base = {"decision": "not_applicable", "feature_enabled": "no"}
        self.assertTrue(self.errors(valid_record(**base)))
        self.assertTrue(self.errors(valid_record(
            **base, evidence={"version": "bench version output", "configuration": ""})))
        self.assertEqual(self.errors(valid_record(
            **base, evidence={"version": "bench version output",
                              "configuration": "site_config.json has no such key"})), [])

    def test_duplicate_advisory_for_same_component_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in ("one.json", "two.json"):
                (folder / name).write_text(json.dumps(valid_record()))
            self.assertTrue(advisories.check_folder(folder))

    def test_broken_json_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "broken.json").write_text("{")
            self.assertTrue(advisories.check_folder(folder))

    def test_repository_records_are_valid(self):
        self.assertEqual(advisories.check_folder(FOLDER / "records"), [])


class GuideTests(unittest.TestCase):
    def test_emergency_guide_exists_and_links_k26(self):
        guide = (FOLDER / "emergency-patch.md").read_text()
        self.assertIn("K-26", guide)
        self.assertIn("apply_now", guide)


if __name__ == "__main__":
    unittest.main()
