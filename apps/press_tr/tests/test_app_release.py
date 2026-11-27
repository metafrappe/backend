"""G-14: app release flow rules for Press.

The rules live in ``press_tr.app_release`` as plain code: App Source and Release Group
definitions, the scheduled deploy window and the pyproject rule. The test needs no Frappe
install, so it also runs outside the Press container.
"""

import sys
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]
sys.path.insert(0, str(APP))

from press_tr import app_release  # noqa: E402

VALID_PYPROJECT = """
[project]
name = "sample_app"

[tool.bench.frappe-dependencies]
frappe = ">=16.0.0,<17.0.0"
"""


class AppSourceTest(unittest.TestCase):
	def test_every_source_is_a_github_repository_on_the_v16_branch(self):
		self.assertTrue(app_release.APP_SOURCES)
		for app, source in app_release.APP_SOURCES.items():
			with self.subTest(app=app):
				self.assertEqual(source.app, app)
				self.assertTrue(source.repository_url.startswith("https://github.com/"))
				self.assertFalse(source.repository_url.endswith((".git", "/")))
				self.assertEqual(source.branch, "version-16")

	def test_known_source_is_accepted(self):
		source = app_release.APP_SOURCES["erpnext"]
		self.assertIs(
			app_release.validate_app_source("erpnext", source.repository_url, source.branch), source
		)

	def test_unknown_app_wrong_repository_and_wrong_branch_are_rejected(self):
		source = app_release.APP_SOURCES["erpnext"]
		cases = {
			"unknown app": ("unknown_app", source.repository_url, source.branch),
			"other repository": ("erpnext", "https://github.com/example/erpnext", source.branch),
			"other branch": ("erpnext", source.repository_url, "develop"),
		}
		for name, args in cases.items():
			with self.subTest(case=name), self.assertRaises(app_release.ReleaseRuleError):
				app_release.validate_app_source(*args)


class ReleaseGroupTest(unittest.TestCase):
	def test_staging_and_production_groups_are_separate(self):
		groups = app_release.RELEASE_GROUPS
		self.assertEqual(set(groups), {"erpnext-v16-tr-staging", "erpnext-v16-tr-prod"})
		staging = groups["erpnext-v16-tr-staging"]
		production = groups["erpnext-v16-tr-prod"]
		self.assertTrue(staging.enable_auto_deploy)
		self.assertFalse(staging.scheduled_deploy)
		self.assertFalse(production.enable_auto_deploy)
		self.assertTrue(production.scheduled_deploy)

	def test_groups_ship_the_same_apps_and_every_app_has_a_source(self):
		groups = app_release.RELEASE_GROUPS
		apps = {name: group.apps for name, group in groups.items()}
		self.assertEqual(apps["erpnext-v16-tr-staging"], apps["erpnext-v16-tr-prod"])
		for group in groups.values():
			self.assertEqual(group.apps[0], "frappe")
			for app in group.apps:
				with self.subTest(group=group.name, app=app):
					self.assertIn(app, app_release.APP_SOURCES)

	def test_scheduled_deploy_settings_list_only_production(self):
		self.assertEqual(app_release.scheduled_deploy_groups(), ("erpnext-v16-tr-prod",))


class ScheduledDeployTest(unittest.TestCase):
	def test_deploy_hours_match_press_hooks(self):
		self.assertEqual(app_release.DEPLOY_HOURS, frozenset({1, 2, 3, 4, 5, 21, 22, 23}))

	def test_production_deploys_only_inside_the_window(self):
		inside = datetime(2026, 11, 28, 2, 30, tzinfo=UTC)
		outside = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
		self.assertTrue(app_release.deploy_allowed("erpnext-v16-tr-prod", inside))
		self.assertFalse(app_release.deploy_allowed("erpnext-v16-tr-prod", outside))

	def test_staging_deploys_at_any_hour(self):
		for hour in range(24):
			with self.subTest(hour=hour):
				moment = datetime(2026, 11, 28, hour, 0, tzinfo=UTC)
				self.assertTrue(app_release.deploy_allowed("erpnext-v16-tr-staging", moment))

	def test_local_time_is_converted_to_utc(self):
		istanbul = timezone(timedelta(hours=3))
		# 23:30 in Istanbul is 20:30 UTC, outside the window.
		self.assertFalse(
			app_release.deploy_allowed("erpnext-v16-tr-prod", datetime(2026, 11, 28, 23, 30, tzinfo=istanbul))
		)
		# 04:00 in Istanbul is 01:00 UTC, inside the window.
		self.assertTrue(
			app_release.deploy_allowed("erpnext-v16-tr-prod", datetime(2026, 11, 28, 4, 0, tzinfo=istanbul))
		)

	def test_naive_time_and_unknown_group_are_rejected(self):
		with self.assertRaises(app_release.ReleaseRuleError):
			app_release.deploy_allowed("erpnext-v16-tr-prod", datetime(2026, 11, 28, 2, 0))
		with self.assertRaises(app_release.ReleaseRuleError):
			app_release.deploy_allowed("other-group", datetime(2026, 11, 28, 2, 0, tzinfo=UTC))


class PyprojectRuleTest(unittest.TestCase):
	def test_valid_pyproject_is_accepted(self):
		self.assertEqual(app_release.validate_pyproject(VALID_PYPROJECT), "sample_app")

	def test_space_separated_and_higher_minor_bounds_are_accepted(self):
		for spec in (">=16.0.0 <17.0.0", ">=16.56.0,<17.0.0", "<17.0.0, >=16.1.0"):
			with self.subTest(spec=spec):
				text = VALID_PYPROJECT.replace(">=16.0.0,<17.0.0", spec)
				self.assertEqual(app_release.validate_pyproject(text), "sample_app")

	def test_app_breaking_the_rule_is_rejected(self):
		cases = {
			"no frappe dependency": '[project]\nname = "sample_app"\n',
			"no project name": VALID_PYPROJECT.replace('name = "sample_app"', ""),
			"old major": VALID_PYPROJECT.replace(">=16.0.0,<17.0.0", ">=15.0.0,<16.0.0"),
			"no upper bound": VALID_PYPROJECT.replace(">=16.0.0,<17.0.0", ">=16.0.0"),
			"next major allowed": VALID_PYPROJECT.replace(">=16.0.0,<17.0.0", ">=16.0.0,<18.0.0"),
			"lower bound below v16": VALID_PYPROJECT.replace(">=16.0.0,<17.0.0", ">=15.9.0,<17.0.0"),
			"other operator": VALID_PYPROJECT.replace(">=16.0.0,<17.0.0", "~=16.0"),
			"not toml": "[project\nname = ",
		}
		for name, text in cases.items():
			with self.subTest(case=name), self.assertRaises(app_release.ReleaseRuleError):
				app_release.validate_pyproject(text)

	def test_apps_in_this_repository_follow_the_rule(self):
		paths = sorted((REPO / "apps").glob("*/pyproject.toml"))
		self.assertTrue(paths)
		for path in paths:
			with self.subTest(app=path.parent.name):
				self.assertEqual(app_release.validate_pyproject(path.read_text(encoding="utf-8")), path.parent.name)


if __name__ == "__main__":
	unittest.main()
