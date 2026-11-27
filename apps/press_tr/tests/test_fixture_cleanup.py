"""G-8: press_tr closes Frappe Cloud defaults after every migrate.

Frappe imports Press fixtures before ``after_migrate`` runs. A fixture with a newer ``modified``
stamp overwrites local edits, so the cleanup must run again on every migrate.

The test needs no Frappe install: ``frappe`` is replaced with an in-memory stub.
"""

import importlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

APP_ROOT = Path(__file__).resolve().parents[1]
SIGNUP_METHOD = "press.signup_e2e.run_signup_e2e"
CLEANUP_ENTRY = "press_tr.fixture_cleanup.disable_cloud_defaults"
PRESS_TIERS = ("Beginner", "Growth", "Intermediate", "Advance", "Power", "Elite")


class FakeDatabase:
	"""Stores rows as ``{doctype: {name: {field: value}}}`` and records every write."""

	def __init__(self, test, records):
		self.test = test
		self.records = records
		self.writes = []

	def _matches(self, row, name, filters):
		for field, operator, expected in filters:
			value = name if field == "name" else row.get(field)
			if operator == "=" and value != expected:
				return False
			if operator == "in" and value not in expected:
				return False
			if operator == "not in" and (value or "") in expected:
				return False
			if operator == "is" and expected == "set" and not value:
				return False
		return True

	def get_all(self, doctype, filters=None, pluck=None):
		self.test.assertEqual(pluck, "name")
		rows = self.records.get(doctype, {})
		normalized = [(field, operator, value) for _doctype, field, operator, value in filters or []]
		return sorted(name for name, row in rows.items() if self._matches(row, name, normalized))

	def set_value(self, doctype, filters, field, value=None, *, update_modified):
		# Press document events must not run and the fixture stamp must stay as imported.
		self.test.assertFalse(update_modified)
		self.writes.append(doctype)
		values = field if isinstance(field, dict) else {field: value}
		rows = self.records[doctype]
		if isinstance(filters, str):
			names = [filters]
		else:
			operator, names = filters["name"]
			self.test.assertEqual(operator, "in")
			extra = [(key, "=", expected) for key, expected in filters.items() if key != "name"]
			names = [name for name in names if name in rows and self._matches(rows[name], name, extra)]
		for name in names:
			rows[name].update(values)

	def delete(self, doctype, filters):
		operator, names = filters["name"]
		self.test.assertEqual(operator, "in")
		self.writes.append(doctype)
		for name in names:
			self.records[doctype].pop(name, None)


# Orchestrator decisions of 24 and 25 November 2026. Values are USD, as Press compares them
# with price_usd. Press v0.154.1 does not test paying_user_since, so every tier writes 0.
DECIDED_TEAM_TIERS = {
	"Beginner": {"amount": 0.0, "last_invoice_amount": 0.0, "paying_user_since": 0},
	"Growth": {"amount": 1000.0, "last_invoice_amount": 0.0, "paying_user_since": 0},
	"Intermediate": {"amount": 2500.0, "last_invoice_amount": 400.0, "paying_user_since": 0},
	"Advance": {"amount": 10000.0, "last_invoice_amount": 750.0, "paying_user_since": 0},
}
CLEANUP_SOURCE = APP_ROOT / "press_tr" / "fixture_cleanup.py"
HANDOFF_NOTE = APP_ROOT.parents[1] / "docs" / "handoff" / "press-fixture-cleanup.md"
# Orchestrator decision of 25 November 2026: the table names only conditions Press tests.
HANDOFF_TIER_ROWS = (
	"| Beginner | Kart yok | 0 dolar |",
	"| Growth | Kart eklendi | 1.000 dolar |",
	"| Intermediate | Son fatura en az 400 dolar | 2.500 dolar |",
	"| Advance | Son fatura en az 750 dolar | 10.000 dolar |",
)
MONTH_CONDITIONS = re.compile(r"\b[0-9]+ (ay|paid months?|months?)\b", re.IGNORECASE)
STARTER_PLAN_USD = 400.0
GROWTH_PLAN_USD = 750.0


def press_is_limits_exceeded(spending_limit, subscribed, plan_price):
	"""Press v0.154.1 press/api/account.py is_limits_exceeded, for a team with apply_limits."""
	return spending_limit <= subscribed + plan_price


def press_spending_limit_for_new_beginner(records):
	"""Press gives a new team the Beginner tier. A later tier change reads the Team Tier amount.

	Press v0.154.1 team.py writes 100 for a new team and falls back to 100 when the amount is 0.
	Both values must block a paid plan, so the test checks the larger one.
	"""
	return max(records["Team Tier"]["Beginner"]["amount"] or 100, 100)


def press_spending_limit_after_card_added(records):
	"""Press v0.154.1 team.py upgrade_beginner_tier_for_new_card moves the team to Growth."""
	return records["Team Tier"]["Growth"]["amount"]


def press_fixture(count=686):
	return [{"name": f"fc-plan-{index}", "enabled": 1} for index in range(count)]


class FixtureCleanupTest(unittest.TestCase):
	def setUp(self):
		fixture_path = os.environ.get("PRESS_SITE_PLAN_FIXTURE")
		if fixture_path:
			self.fixtures = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
		else:
			self.fixtures = press_fixture()
		self.fixture_names = {row["name"] for row in self.fixtures}
		self.assertEqual(len(self.fixture_names), 686)

		self.records = {
			"Site Plan": {name: {"enabled": 1} for name in self.fixture_names} | {"local-plan": {"enabled": 1}},
			"Scheduled Job Type": {
				SIGNUP_METHOD: {"method": SIGNUP_METHOD, "stopped": 0},
				"press.other_job": {"method": "press.other_job", "stopped": 0},
			},
			"Team Tier": {
				tier: {"amount": 100.0, "last_invoice_amount": 0.0, "paying_user_since": 0} for tier in PRESS_TIERS
			},
			"Cluster": {"used": {"public": 1}, "unused": {"public": 1}},
			"Server Plan": {
				"used-plan": {"cluster": "used", "enabled": 1},
				"unused-plan": {"cluster": "unused", "enabled": 1},
				"no-cluster-plan": {"cluster": "", "enabled": 1},
			},
			"Cloud Region": {"used-region": {}, "unused-region": {}},
			"Team": {"small-team": {"tier": "Growth"}},
		}
		self.conf = {}
		self.db = FakeDatabase(self, self.records)

		directory = tempfile.TemporaryDirectory()
		self.addCleanup(directory.cleanup)
		fixture = Path(directory.name) / "site_plan.json"
		fixture.write_text(json.dumps(self.fixtures), encoding="utf-8")

		def get_app_path(*parts):
			self.assertEqual(parts, ("press", "fixtures", "site_plan.json"))
			return str(fixture)

		frappe = ModuleType("frappe")
		frappe.get_app_path = get_app_path
		frappe.db = self.db
		self.db.exists = lambda doctype, name: name in self.records.get(doctype, {})
		frappe.get_all = self.db.get_all
		frappe.conf = SimpleNamespace(get=self.conf.get)
		frappe.throw = self.fail_with
		frappe._ = lambda text: text
		for patcher in (
			patch.object(sys, "path", [str(APP_ROOT), *sys.path]),
			patch.dict(sys.modules, {"frappe": frappe}),
		):
			patcher.start()
			self.addCleanup(patcher.stop)
		for name in ("press_tr.hooks", "press_tr.fixture_cleanup"):
			sys.modules.pop(name, None)
		self.hooks = importlib.import_module("press_tr.hooks")
		module, _separator, function = CLEANUP_ENTRY.rpartition(".")
		self.cleanup = getattr(importlib.import_module(module), function)

	def fail_with(self, message, *args, **kwargs):
		raise ValueError(message)

	def plans(self):
		return {name: row["enabled"] for name, row in self.records["Site Plan"].items()}

	def test_after_migrate_is_a_list_with_one_cleanup_entry(self):
		self.assertIsInstance(self.hooks.after_migrate, list)
		self.assertEqual(self.hooks.after_migrate.count(CLEANUP_ENTRY), 1)

	def test_cleanup_keeps_other_after_migrate_steps(self):
		# A second after_migrate assignment would silently drop the AJA-421 reviewer role step.
		self.assertIn("press_tr.press_identity.recovery.ensure_reviewer_role", self.hooks.after_migrate)

	def test_migration_disables_press_fixtures_and_old_signup_job(self):
		for _attempt in range(2):
			self.cleanup()
			self.assertEqual(self.plans(), dict.fromkeys(self.fixture_names, 0) | {"local-plan": 1})
			jobs = {name: row["stopped"] for name, row in self.records["Scheduled Job Type"].items()}
			self.assertEqual(jobs, {SIGNUP_METHOD: 1, "press.other_job": 0})

	def test_our_plan_stays_enabled_after_migrate(self):
		self.records["Site Plan"]["our-growth-plan"] = {"enabled": 1}
		self.cleanup()
		self.assertEqual(self.records["Site Plan"]["our-growth-plan"]["enabled"], 1)
		self.assertEqual(self.records["Site Plan"]["local-plan"]["enabled"], 1)

	def test_fixture_with_new_modified_stamp_is_closed_again(self):
		self.cleanup()
		# The next migrate imports the fixture again with a newer stamp and enables every plan.
		for name in self.fixture_names:
			self.records["Site Plan"][name].update(enabled=1, modified="2027-01-01 00:00:00")
		self.cleanup()
		self.assertTrue(all(self.records["Site Plan"][name]["enabled"] == 0 for name in self.fixture_names))
		self.assertEqual(self.records["Site Plan"]["local-plan"]["enabled"], 1)

	def test_team_tiers_match_our_table(self):
		table = {
			tier: {"amount": 1000.0 + index, "last_invoice_amount": 10.0 * index, "paying_user_since": index}
			for index, tier in enumerate(PRESS_TIERS)
		}
		self.conf["press_tr_team_tiers"] = table
		for _attempt in range(2):
			self.cleanup()
			self.assertEqual(self.records["Team Tier"], table)

	def test_decided_team_tiers_apply_without_a_site_setting(self):
		# Orchestrator decision of 24 November 2026; the product owner may change it later.
		for _attempt in range(2):
			self.cleanup()
			self.assertEqual(self.records["Team Tier"], DECIDED_TEAM_TIERS)

	def test_power_and_elite_tiers_are_closed(self):
		for _attempt in range(2):
			# Every migrate imports the Press fixture again and brings both tiers back.
			for tier in ("Power", "Elite"):
				self.records["Team Tier"].setdefault(tier, {"amount": 7500.0, "last_invoice_amount": 1500.0})
			self.cleanup()
			self.assertNotIn("Power", self.records["Team Tier"])
			self.assertNotIn("Elite", self.records["Team Tier"])

	def test_closed_tier_in_use_stops_migrate_before_any_tier_changes(self):
		self.records["Team"] = {"big-team": {"tier": "Elite"}}
		before = json.loads(json.dumps(self.records["Team Tier"]))
		with self.assertRaises(ValueError):
			self.cleanup()
		self.assertEqual(self.records["Team Tier"], before)

	def test_customer_without_a_card_cannot_buy_a_paid_plan(self):
		self.cleanup()
		limit = press_spending_limit_for_new_beginner(self.records)
		self.assertTrue(press_is_limits_exceeded(limit, subscribed=0, plan_price=STARTER_PLAN_USD))
		self.assertTrue(press_is_limits_exceeded(limit, subscribed=0, plan_price=GROWTH_PLAN_USD))

	def test_customer_with_a_card_can_buy_the_growth_plan(self):
		self.cleanup()
		limit = press_spending_limit_after_card_added(self.records)
		self.assertEqual(limit, 1000.0)
		self.assertFalse(press_is_limits_exceeded(limit, subscribed=0, plan_price=GROWTH_PLAN_USD))

	def test_site_setting_overrides_the_decided_table(self):
		table = json.loads(json.dumps(DECIDED_TEAM_TIERS))
		table["Growth"]["amount"] = 1500.0
		self.conf["press_tr_team_tiers"] = table
		self.cleanup()
		self.assertEqual(self.records["Team Tier"]["Growth"]["amount"], 1500.0)
		self.assertNotIn("Power", self.records["Team Tier"])

	def test_new_press_tier_stops_migrate_until_the_table_lists_it(self):
		self.records["Team Tier"]["Platinum"] = {"amount": 50000.0, "last_invoice_amount": 5000.0}
		before = json.loads(json.dumps(self.records["Team Tier"]))
		with self.assertRaises(ValueError):
			self.cleanup()
		self.assertEqual(self.records["Team Tier"], before)

	def test_incomplete_team_tier_table_is_rejected_before_any_tier_changes(self):
		before = json.loads(json.dumps(self.records["Team Tier"]))
		self.conf["press_tr_team_tiers"] = {"Beginner": {"amount": 1.0, "last_invoice_amount": 0.0}}
		with self.assertRaises(ValueError):
			self.cleanup()
		self.assertEqual(self.records["Team Tier"], before)

	def test_unused_server_plan_and_cluster_are_closed(self):
		self.conf["press_tr_enabled_clusters"] = ["used"]
		for _attempt in range(2):
			self.cleanup()
			plans = {name: row["enabled"] for name, row in self.records["Server Plan"].items()}
			self.assertEqual(plans, {"used-plan": 1, "unused-plan": 0, "no-cluster-plan": 1})
			clusters = {name: row["public"] for name, row in self.records["Cluster"].items()}
			self.assertEqual(clusters, {"used": 1, "unused": 0})
		# Cloud Region has no enabled field; the record is kept and never written.
		self.assertEqual(set(self.records["Cloud Region"]), {"used-region", "unused-region"})
		self.assertNotIn("Cloud Region", self.db.writes)

	def test_unknown_cluster_name_is_rejected_before_any_cluster_changes(self):
		# A typo would match every Cluster with "not in" and close them all.
		self.conf["press_tr_enabled_clusters"] = ["used", "typo-cluster"]
		with self.assertRaises(ValueError):
			self.cleanup()
		self.assertTrue(all(row["public"] == 1 for row in self.records["Cluster"].values()))
		self.assertTrue(all(row["enabled"] == 1 for row in self.records["Server Plan"].values()))

	def test_paying_user_since_must_be_a_whole_number(self):
		table = {
			tier: {"amount": 1.0, "last_invoice_amount": 0.0, "paying_user_since": 1} for tier in PRESS_TIERS
		}
		table["Growth"]["paying_user_since"] = 1.5
		self.conf["press_tr_team_tiers"] = table
		with self.assertRaises(ValueError):
			self.cleanup()
		self.assertNotIn("Team Tier", self.db.writes)

	def test_server_plans_and_clusters_stay_unchanged_without_a_region_list(self):
		self.cleanup()
		self.assertTrue(all(row["enabled"] == 1 for row in self.records["Server Plan"].values()))
		self.assertTrue(all(row["public"] == 1 for row in self.records["Cluster"].values()))


if __name__ == "__main__":
	unittest.main()


class TeamTierConditionTextTest(unittest.TestCase):
	"""G-8: the note and the code comments name only the conditions Press v0.154.1 tests."""

	def test_no_month_condition_in_note_or_code(self):
		for path in (CLEANUP_SOURCE, HANDOFF_NOTE):
			with self.subTest(path=path.name):
				found = MONTH_CONDITIONS.findall(path.read_text(encoding="utf-8"))
				self.assertEqual(found, [])

	def test_note_table_lists_only_press_conditions(self):
		note = HANDOFF_NOTE.read_text(encoding="utf-8")
		rows = [line for line in note.splitlines() if line.startswith(("| Beginner", "| Growth", "| Inter", "| Adv"))]
		self.assertEqual(tuple(rows), HANDOFF_TIER_ROWS)

	def test_default_table_sets_no_paying_months(self):
		source = CLEANUP_SOURCE.read_text(encoding="utf-8")
		self.assertNotRegex(source, r'"paying_user_since": [1-9]')
