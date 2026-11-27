"""G-37: the local restore drill backs up a site, restores it to a new site and compares them.

A fake bench stands in for the containers. It keeps the state of the sites, so the tests
check what the drill concludes from each answer, not only the order of the commands.
The last test checks the result of the real drill on the local stack (docs/evidence).
"""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence" / "g37-restore-drill.json"
spec = importlib.util.spec_from_file_location("restore_drill", ROOT / "deploy" / "restore_drill.py")
restore_drill = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = restore_drill
spec.loader.exec_module(restore_drill)

SOURCE = "tenant1.localhost"
TOKEN = "a1b2c3d4"
DRILL = f"restore-drill-{TOKEN}.localhost"
NOW = datetime(2026, 11, 28, 9, 0, tzinfo=UTC)


class FakeBench:
    """Answers the drill's commands like bench would, from an in-memory copy of the sites."""

    def __init__(self, *, lose_marker=False, lose_user=False, files=None, fail_on=None):
        self.sites = {SOURCE: {"DocType": 400, "User": 3, "Note": {"n-old"}}}
        self.backups = {}
        self.calls = []
        self.lose_marker = lose_marker
        self.lose_user = lose_user
        self.files = files
        self.fail_on = fail_on

    def __call__(self, argv):
        self.calls.append(list(argv))
        text = " ".join(argv)
        if self.fail_on and self.fail_on in text:
            raise restore_drill.DrillError(f"command failed: {self.fail_on}")
        if argv[:1] == ["bench"] and "execute" in argv:
            return self.execute(argv[2], argv[4], argv[5:])
        if argv[:1] == ["bench"] and "backup" in argv:
            path = argv[argv.index("--backup-path") + 1]
            self.backups[path] = self.copy(self.sites[argv[2]])
            return "Backup Summary\n"
        if argv[:2] == ["sh", "-c"] and "ls -1" in argv[2]:
            names = self.files or [
                "20261128_090000-tenant1_localhost-database.sql.gz",
                "20261128_090000-tenant1_localhost-files.tar",
                "20261128_090000-tenant1_localhost-private-files.tar",
                "20261128_090000-tenant1_localhost-site_config_backup.json",
            ]
            return "\n".join(names) + "\n"
        if argv[:2] == ["sh", "-c"] and " restore " in argv[2]:
            site, database = argv[4], argv[5]
            path = database.rsplit("/", 1)[0]
            copy = self.copy(self.backups[path])
            if self.lose_marker:
                copy["Note"] = {"n-old"}
            if self.lose_user:
                copy["User"] -= 1
            self.sites[site] = copy
            return f"Site {site} has been restored with files\n"
        if argv[:2] == ["sh", "-c"] and "drop-site" in argv[2]:
            self.sites.pop(argv[4])
            return ""
        if argv[:2] == ["rm", "-rf"]:
            self.backups.pop(argv[3], None)
            return ""
        raise AssertionError(f"unexpected command {argv}")

    @staticmethod
    def copy(site):
        return {"DocType": site["DocType"], "User": site["User"], "Note": set(site["Note"])}

    def execute(self, site, method, rest):
        data = self.sites[site]
        if method == "frappe.client.insert":
            doc = json.loads(rest[1])["doc"]
            assert doc["doctype"] == "Note" and doc["title"].startswith("restore-drill-")
            data["Note"].add("n-marker")
            return json.dumps({"name": "n-marker", "doctype": "Note"}) + "\n"
        args = json.loads(rest[1])
        if method == "frappe.db.count":
            value = len(data["Note"]) if args[0] == "Note" else data[args[0]]
            # bench execute prints nothing for a falsy result such as 0.
            return f"{value}\n" if value else ""
        if method == "frappe.db.exists":
            return f"{args[1]}\n" if args[1] in data["Note"] else ""
        if method == "frappe.client.delete":
            data["Note"].discard(args[1])
            return ""
        raise AssertionError(f"unexpected method {method}")


def drill(bench, site=SOURCE):
    return restore_drill.run_drill(site, bench, now=lambda: NOW, token=TOKEN)


class RestoreDrillTests(unittest.TestCase):
    def test_full_drill_passes_and_leaves_no_trace(self):
        bench = FakeBench()
        result = drill(bench)
        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(restore_drill.evaluate(result), [])
        self.assertEqual(result["source_site"], SOURCE)
        self.assertEqual(result["drill_site"], DRILL)
        self.assertEqual(result["parts"], ["database", "public", "private"])
        self.assertTrue(result["checks"]["marker_restored"])
        self.assertEqual(result["checks"]["counts"]["Note"], [2, 2])
        self.assertEqual(
            result["cleanup"],
            {"drill_site_dropped": True, "backup_removed": True, "marker_removed": True},
        )
        # The source is as before and the drill site and backup are gone.
        self.assertEqual(bench.sites, {SOURCE: {"DocType": 400, "User": 3, "Note": {"n-old"}}})
        self.assertEqual(bench.backups, {})

    def test_missing_marker_fails_the_drill_and_still_cleans_up(self):
        bench = FakeBench(lose_marker=True)
        result = drill(bench)
        self.assertEqual(result["status"], "fail")
        self.assertIn("marker", " ".join(restore_drill.evaluate(result)))
        self.assertNotIn(DRILL, bench.sites)
        self.assertEqual(bench.backups, {})

    def test_different_record_count_fails_the_drill(self):
        result = drill(FakeBench(lose_user=True))
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["checks"]["counts"]["User"], [3, 2])
        self.assertIn("User", " ".join(restore_drill.evaluate(result)))

    def test_backup_without_private_files_stops_before_restore(self):
        bench = FakeBench(files=[
            "x-database.sql.gz",
            "x-files.tar",
        ])
        result = drill(bench)
        self.assertEqual(result["status"], "fail")
        self.assertIn("private", result["error"])
        self.assertFalse(any("restore" in " ".join(call[:3]) for call in bench.calls if call[0] == "sh"
                             and " restore " in call[2]))
        self.assertEqual(bench.backups, {})
        self.assertEqual(bench.sites[SOURCE]["Note"], {"n-old"})

    def test_failed_restore_is_reported_and_the_drill_site_is_dropped(self):
        bench = FakeBench(fail_on="--force restore")
        bench.sites[DRILL] = {"DocType": 0, "User": 0, "Note": set()}  # half-created by restore
        result = drill(bench)
        self.assertEqual(result["status"], "fail")
        self.assertIn("restore", result["error"])
        self.assertNotIn(DRILL, bench.sites)
        self.assertTrue(result["cleanup"]["drill_site_dropped"])

    def test_only_local_development_sites_are_accepted(self):
        for site in ["demo.app.example.com", "tenant1.localhost.evil.com", "../x.localhost", ""]:
            with self.subTest(site=site), self.assertRaises(restore_drill.DrillError):
                drill(FakeBench(), site=site)

    def test_passwords_stay_inside_the_container(self):
        bench = FakeBench()
        drill(bench)
        for call in bench.calls:
            text = " ".join(call)
            if "--db-root-password" in text:
                self.assertIn('"$MARIADB_ROOT_PASSWORD"', text)
            self.assertNotIn("--admin-password ", " ".join(call[:2]))

    def test_evaluate_rejects_incomplete_cleanup(self):
        result = drill(FakeBench())
        result["cleanup"]["backup_removed"] = False
        self.assertIn("cleanup", " ".join(restore_drill.evaluate(result)))

    def test_cli_writes_the_result_and_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "result.json"
            with redirect_stdout(io.StringIO()) as printed:
                code = restore_drill.main(
                    ["--site", SOURCE, "--result", str(out)],
                    runner=FakeBench(), now=lambda: NOW, token=TOKEN,
                )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.read_text())["status"], "pass")
            self.assertIn("pass", printed.getvalue())
            with redirect_stdout(io.StringIO()):
                code = restore_drill.main(
                    ["--site", SOURCE, "--result", str(out)],
                    runner=FakeBench(lose_marker=True), now=lambda: NOW, token=TOKEN,
                )
            self.assertEqual(code, 1)


class RestoreDrillEvidenceTests(unittest.TestCase):
    def test_last_local_drill_passed(self):
        result = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(result["requirement"], "G-37")
        self.assertEqual(result["stack"], "local")
        self.assertTrue(result["source_site"].endswith(".localhost"))
        self.assertEqual(restore_drill.evaluate(result), [])
        self.assertEqual(result["status"], "pass")


if __name__ == "__main__":
    unittest.main()
