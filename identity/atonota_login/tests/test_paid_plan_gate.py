"""Paid plan gate bound to the plan decision (G-166, AJA-18, AJA-585).

Expected rules, from the plan decision (AJA-18) and the task AJA-585:
- The Starter plan costs 400 US dollars a month. The Growth plan costs 750 US dollars a month.
- The Enterprise plan has no price. The screen text is "Fiyat için bize ulaşın".
  A customer cannot buy it alone. A person opens an Enterprise tenant.
- Prices are kept in US dollars. The lira amount is another task (AJA-581), so no rate is here.
- A customer without a payment card cannot take a paid plan (Team Tier table).
  The card proof is server evidence. The caller cannot bring it.
- A rule or a price without a value keeps the action closed with "configuration required" (G-167).
- The action file holds no price. Prices live in one plan file only.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atonota_login import decision, plans

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
VALID = {"status": "valid", "expiresAt": (NOW + timedelta(hours=1)).isoformat()}
EXPIRED = {"status": "valid", "expiresAt": (NOW - timedelta(seconds=1)).isoformat()}
ACTION = "open-paid-plan"
FULL = {"membership": VALID, "payment-card": VALID}
# Words that would mean the action file carries a price. Matched against every key, in any case.
PRICE_WORDS = ("price", "pricing_value", "currency", "amount", "cost", "fee", "tariff", "usd")


def walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_keys(item)


def plan_data():
    return json.loads(plans.PLANS_FILE.read_text(encoding="utf-8"))


def policy_data():
    return json.loads(decision.POLICY_FILE.read_text(encoding="utf-8"))


class GateTestCase(unittest.TestCase):
    def setUp(self):
        self.policy = decision.load_policy()
        self.plans = plans.load_plans()

    def judge(self, plan_id, evidence, policy=None, plan_set=None):
        return plans.judge(policy or self.policy, plan_set or self.plans, plan_id, evidence, NOW)


class OpensForCardHoldersTest(GateTestCase):
    """Acceptance 1: Starter and Growth open for a customer with a card record."""

    def test_1a_starter_is_ready_with_membership_and_card(self):
        result = self.judge("starter", FULL)
        self.assertEqual(result.status, decision.READY)
        self.assertEqual(result.action, ACTION)
        self.assertEqual(result.subject, "starter")

    def test_1b_growth_is_ready_with_membership_and_card(self):
        result = self.judge("growth", FULL)
        self.assertEqual(result.status, decision.READY)
        self.assertEqual(result.subject, "growth")

    def test_1c_the_final_check_confirms_the_same_plan(self):
        earlier = self.judge("starter", FULL)
        again = plans.confirm(self.policy, self.plans, earlier, "starter", FULL, NOW)
        self.assertEqual(again.status, decision.READY)

    def test_1d_a_ready_result_of_one_plan_does_not_open_another(self):
        earlier = self.judge("starter", FULL)
        again = plans.confirm(self.policy, self.plans, earlier, "growth", FULL, NOW)
        self.assertEqual(again.status, decision.DENIED)
        self.assertEqual(again.reasons, ("result-not-for-this-action",))

    def test_1e_a_changed_plan_file_refuses_the_final_check(self):
        earlier = self.judge("starter", FULL)
        data = plan_data()
        data["plans"][0]["id"] = "starter-two"
        data["plans"].append(dict(plan_data()["plans"][0]))
        changed = plans.Plans(data)
        again = plans.confirm(self.policy, changed, earlier, "starter", FULL, NOW)
        self.assertEqual(again.status, decision.DENIED)
        self.assertEqual(again.reasons, ("policy-changed",))

    def test_1f_the_plain_policy_result_cannot_be_confirmed_as_a_plan(self):
        forged = decision.Result(decision.READY, ACTION, self.policy.version)
        again = plans.confirm(self.policy, self.plans, forged, "starter", FULL, NOW)
        self.assertEqual(again.status, decision.DENIED)


class CardIsRequiredTest(GateTestCase):
    """Acceptance 2: no card, no paid plan."""

    def test_2a_membership_without_card_is_denied(self):
        result = self.judge("starter", {"membership": VALID})
        self.assertEqual(result.status, decision.DENIED)
        self.assertEqual(result.reasons, ("payment-card",))

    def test_2b_expired_card_proof_is_denied(self):
        result = self.judge("growth", {"membership": VALID, "payment-card": EXPIRED})
        self.assertEqual(result.status, decision.DENIED)
        self.assertEqual(result.reasons, ("payment-card",))

    def test_2c_card_without_membership_is_denied(self):
        result = self.judge("growth", {"payment-card": VALID})
        self.assertEqual(result.status, decision.DENIED)
        self.assertEqual(result.reasons, ("membership",))

    def test_2d_the_plain_action_also_needs_the_card(self):
        # Without a plan there is no pricing proof either. Only `judge` gives it, for one plan.
        result = self.policy.evaluate(ACTION, {"membership": VALID}, NOW)
        self.assertEqual(result.status, decision.DENIED)
        self.assertEqual(result.reasons, ("pricing", "payment-card"))

    def test_2e_old_pricing_decision_proof_does_not_replace_the_card(self):
        result = self.judge("starter", {"membership": VALID, "pricing-decision": VALID})
        self.assertEqual(result.status, decision.DENIED)


class EnterpriseIsNotSelfServiceTest(GateTestCase):
    """Acceptance 3: a customer cannot buy the Enterprise plan alone."""

    def test_3a_enterprise_is_denied_even_with_full_evidence(self):
        result = self.judge("enterprise", FULL)
        self.assertEqual(result.status, decision.DENIED)
        self.assertEqual(result.reasons, ("not-self-service",))
        self.assertEqual(result.owner_tasks, ())

    def test_3b_unknown_plan_is_denied(self):
        for plan_id in ("trial", "free", "", None, 7, "STARTER"):
            with self.subTest(plan=plan_id):
                result = self.judge(plan_id, FULL)
                self.assertEqual(result.status, decision.DENIED)
                self.assertEqual(result.reasons, ("unknown-plan",))

    def test_3c_enterprise_cannot_be_confirmed(self):
        forged = decision.Result(decision.READY, ACTION, "x" * 64, subject="enterprise")
        again = plans.confirm(self.policy, self.plans, forged, "enterprise", FULL, NOW)
        self.assertEqual(again.status, decision.DENIED)


class EmptyValueNeedsConfigurationTest(GateTestCase):
    """Acceptance 4: an empty rule or price keeps the action closed (G-167)."""

    def test_4a_empty_pricing_rule_gives_configuration_required(self):
        data = policy_data()
        next(r for r in data["rules"] if r["id"] == "paid-plan-pricing")["value"] = None
        result = self.judge("starter", FULL, policy=decision.Policy(data))
        self.assertEqual(result.status, decision.CONFIGURATION_REQUIRED)
        self.assertEqual(
            list(result.owner_tasks),
            [{"rule": "paid-plan-pricing", "owner": "product-owner", "action": ACTION}],
        )

    def test_4b_empty_plan_price_gives_configuration_required(self):
        data = plan_data()
        next(p for p in data["plans"] if p["id"] == "growth")["monthlyUsd"] = None
        result = self.judge("growth", FULL, plan_set=plans.Plans(data))
        self.assertEqual(result.status, decision.CONFIGURATION_REQUIRED)
        self.assertEqual(
            list(result.owner_tasks),
            [{"rule": "plan-price-growth", "owner": "product-owner", "action": ACTION}],
        )

    def test_4c_configuration_required_cannot_be_confirmed(self):
        data = plan_data()
        next(p for p in data["plans"] if p["id"] == "growth")["monthlyUsd"] = None
        empty = plans.Plans(data)
        earlier = plans.judge(self.policy, empty, "growth", FULL, NOW)
        again = plans.confirm(self.policy, empty, earlier, "growth", FULL, NOW)
        self.assertNotEqual(again.status, decision.READY)


class PlanFileTest(unittest.TestCase):
    """Acceptance 5: only the decided prices appear, in one place."""

    def test_5a_the_plans_and_prices_are_the_decided_ones(self):
        data = plan_data()
        self.assertEqual(data["currency"], "USD")
        found = {p["id"]: (p["monthlyUsd"], p["selfService"], p["priceText"]) for p in data["plans"]}
        self.assertEqual(
            found,
            {
                "starter": (400, True, None),
                "growth": (750, True, None),
                "enterprise": (None, False, "Fiyat için bize ulaşın"),
            },
        )

    def test_5b_loaded_plans_carry_the_same_values(self):
        loaded = plans.load_plans()
        self.assertEqual(loaded.plans["starter"].monthly_usd, 400)
        self.assertEqual(loaded.plans["growth"].monthly_usd, 750)
        self.assertIsNone(loaded.plans["enterprise"].monthly_usd)
        self.assertEqual(loaded.plans["enterprise"].price_text, "Fiyat için bize ulaşın")

    def test_5c_action_file_has_no_price_currency_or_amount(self):
        data = policy_data()
        keys = [key.lower() for key in walk_keys(data)]
        found = [key for key in keys for word in PRICE_WORDS if word in key]
        self.assertEqual(found, [])
        rule = next(r for r in data["rules"] if r["id"] == "paid-plan-pricing")
        self.assertEqual(rule["owner"], "product-owner")
        self.assertIsInstance(rule["value"], str)
        self.assertIn("AJA-18", rule["value"])

    def test_5d_the_plan_file_holds_no_exchange_rate_or_lira(self):
        text = plans.PLANS_FILE.read_text(encoding="utf-8").lower()
        for word in ("try", "lira", "rate", "kur"):
            self.assertNotIn(f'"{word}', text)

    def test_5e_bad_plan_files_are_refused(self):
        bad_cases = {
            "lira": lambda d: d.update(currency="TRY"),
            "zero price": lambda d: d["plans"][0].update(monthlyUsd=0),
            "text price": lambda d: d["plans"][0].update(monthlyUsd="400"),
            "priced enterprise": lambda d: d["plans"][2].update(monthlyUsd=1),
            "enterprise without text": lambda d: d["plans"][2].update(priceText=None),
            "extra key": lambda d: d["plans"][0].update(discount=1),
            "twice": lambda d: d["plans"].append(dict(d["plans"][0])),
        }
        for name, change in bad_cases.items():
            with self.subTest(case=name):
                data = plan_data()
                change(data)
                with self.assertRaises(plans.PlanError):
                    plans.Plans(data)

    def test_5f_bad_json_is_a_plan_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plans.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(plans.PlanError):
                plans.load_plans(path)


if __name__ == "__main__":
    unittest.main()
