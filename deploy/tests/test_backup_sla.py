"""G-37: the written backup service level must match the values the tools enforce.

The values come from requirement G-37 on the decision site, not from the code:
recovery point at most 24 hours, a monthly restore report, a full restore every
quarter and at least 6 calendar months of retention after a site is archived.
"""

import importlib.util
import re
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SLA = ROOT / "docs" / "contracts" / "backup-sla.md"

# The expected values come from G-37. A change here is a change of the promise.
EXPECTED = {
    "rpo_hours": "24",
    "restore_report_interval_months": "1",
    "full_restore_interval_months": "3",
    "archive_retention_months": "6",
    "export_parts": "database, public, private",
}


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "deploy" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sla_values() -> dict[str, str]:
    """Read the rows of the table whose first cell is a backticked key."""
    values = {}
    for line in SLA.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"\|\s*`([a-z_]+)`\s*\|\s*([^|]+?)\s*\|.*\|", line.strip())
        if match:
            if match.group(1) in values:
                raise AssertionError(f"{match.group(1)} is written twice")
            values[match.group(1)] = match.group(2).strip("` ")
    return values


class BackupSlaDocumentTests(unittest.TestCase):
    def test_document_writes_every_g37_value(self):
        self.assertEqual(sla_values(), EXPECTED)

    def test_document_names_its_requirement_and_open_server_proof(self):
        text = SLA.read_text(encoding="utf-8")
        self.assertIn("G-37", text)
        self.assertIn("docs/handoff/backup-restore.md", text)
        self.assertIn("deploy/restore_drill.py", text)


class BackupSlaCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.export = load("backup_export")
        cls.drill = load("restore_drill")
        cls.values = sla_values()

    def test_recovery_point_limit_matches_the_document(self):
        hours = int(self.values["rpo_hours"])
        self.assertEqual(self.export.RPO_HOURS, hours)
        self.export.check_plan(hours, 0, 0)
        with self.assertRaises(self.export.ExportError):
            self.export.check_plan(hours, 0, 0.5)
        now = datetime(2026, 11, 28, tzinfo=UTC)
        self.export.check_recovery_point(now - timedelta(hours=hours), now, True, True)
        with self.assertRaises(self.export.ExportError):
            self.export.check_recovery_point(
                now - timedelta(hours=hours, seconds=1), now, True, True
            )

    def test_retention_matches_the_document(self):
        months = int(self.values["archive_retention_months"])
        self.assertEqual(self.export.RETENTION_MONTHS, months)
        archived = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
        self.assertEqual(
            self.export.retention_until(archived),
            archived.replace(month=1 + months),
        )

    def test_restore_intervals_match_the_document(self):
        self.assertEqual(
            self.drill.REPORT_INTERVAL_MONTHS,
            int(self.values["restore_report_interval_months"]),
        )
        self.assertEqual(
            self.drill.FULL_RESTORE_INTERVAL_MONTHS,
            int(self.values["full_restore_interval_months"]),
        )

    def test_exported_and_restored_parts_match_the_document(self):
        parts = tuple(part.strip() for part in self.values["export_parts"].split(","))
        self.assertEqual(self.export.PARTS, parts)
        self.assertEqual(self.drill.PARTS, parts)


if __name__ == "__main__":
    unittest.main()
