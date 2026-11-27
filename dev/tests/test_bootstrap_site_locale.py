"""A new tenant site starts in en-GB with a filled IANA time zone (AJA-1778)."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

BOOTSTRAP = Path(__file__).resolve().parents[1] / "bootstrap.py"


def load_bootstrap():
    spec = importlib.util.spec_from_file_location("dev_bootstrap_under_test", BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NewTenantSiteLocaleTests(unittest.TestCase):
    def setUp(self):
        self.bootstrap = load_bootstrap()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bench = Path(self.temp.name)
        (self.bench / "sites").mkdir()
        self.system_settings = {}
        self.defaults = {}
        self.set_language = Mock(side_effect=lambda lang: self.defaults.update(lang=lang))
        self.frappe = ModuleType("frappe")
        self.frappe.init = Mock()
        self.frappe.connect = Mock()
        self.frappe.destroy = Mock()
        self.frappe.db = SimpleNamespace(
            set_single_value=Mock(side_effect=lambda doctype, values: self.system_settings.update(values)),
            set_default=Mock(side_effect=lambda key, value: self.defaults.update({key: value})),
            commit=Mock(),
        )
        self.new_site = Mock(side_effect=self.create_site_files)
        site_commands = ModuleType("frappe.commands.site")
        site_commands.new_site = SimpleNamespace(main=self.new_site)
        self.modules = {
            "frappe": self.frappe,
            "frappe.commands": ModuleType("frappe.commands"),
            "frappe.commands.site": site_commands,
            "frappe.translate": SimpleNamespace(set_default_language=self.set_language),
        }

    def create_site_files(self, arguments, standalone_mode):
        site = Path(arguments[0])
        site.mkdir()
        (site / "site_config.json").write_text("{}")

    def run_in_sites(self, site="test-locale.localhost", time_zone=None):
        environment = {
            "FS_TENANT_SOCKET_PORT": "9000",
            "FS_TENANT_WEB_PORT": "8000",
            "MARIADB_ROOT_PASSWORD": "not-a-real-password",
            "ADMIN_PASSWORD": "not-a-real-password",
        }
        (self.bench / "sites/apps.txt").write_text("frappe\n")
        arguments = [] if time_zone is None else [time_zone]
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        with (
            patch.object(self.bootstrap, "BENCH", self.bench),
            patch.dict(sys.modules, self.modules),
            patch.dict("os.environ", environment),
            patch.object(self.bootstrap.subprocess, "run"),
        ):
            self.bootstrap.prepare(site, [], *arguments)

    def test_new_site_language_is_en_gb(self):
        self.run_in_sites()
        self.new_site.assert_called_once()
        self.assertEqual(self.system_settings["language"], "en-GB")
        self.set_language.assert_called_once_with("en-GB")
        self.assertEqual(self.defaults["lang"], "en-GB")

    def test_new_site_time_zone_is_filled_when_none_is_given(self):
        self.run_in_sites()
        time_zone = self.system_settings.get("time_zone")
        self.assertTrue(time_zone)
        self.assertEqual(time_zone, self.bootstrap.DEFAULT_TIME_ZONE)
        self.assertEqual(self.defaults["time_zone"], time_zone)
        self.frappe.db.commit.assert_called_once_with()

    def test_given_iana_time_zone_is_written(self):
        self.run_in_sites(time_zone="Europe/Berlin")
        self.assertEqual(self.system_settings["time_zone"], "Europe/Berlin")

    def test_invalid_time_zone_stops_before_the_site_is_created(self):
        for value in ("Mars/Olympus", "", "GMT+3", "../etc/passwd"):
            with self.subTest(value=value):
                with self.assertRaises(SystemExit) as raised:
                    self.run_in_sites(time_zone=value)
                self.assertIn("time zone", str(raised.exception))
                self.assertIn("IANA", str(raised.exception))
                self.new_site.assert_not_called()
                self.assertEqual(self.system_settings, {})

    def test_cli_rejects_invalid_time_zone(self):
        stderr = StringIO()
        argv = ["bootstrap.py", "test-a.localhost", "--time-zone", "Nowhere/City"]
        with patch.object(sys, "argv", argv), redirect_stderr(stderr), self.assertRaises(SystemExit):
            self.bootstrap.main()
        self.assertIn("IANA", stderr.getvalue())
        self.new_site.assert_not_called()

    def test_existing_site_is_not_created_again(self):
        self.run_in_sites()
        self.new_site.reset_mock()
        self.system_settings.clear()
        self.run_in_sites()
        self.new_site.assert_not_called()
        self.assertEqual(self.system_settings, {})
        config = self.bench / "sites/test-locale.localhost/site_config.json"
        self.assertTrue(json.loads(config.read_text())["allow_tests"])


if __name__ == "__main__":
    unittest.main()
