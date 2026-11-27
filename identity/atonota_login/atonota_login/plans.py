# SPDX-License-Identifier: MIT
"""Paid plan check of the "open-paid-plan" action (G-166, AJA-18).

The plan decision (AJA-18) is kept in ``policy/plans.json``:

- Starter costs 400 US dollars a month. Growth costs 750 US dollars a month.
- Enterprise has no price. The screen says "Fiyat için bize ulaşın". A person opens an Enterprise
  tenant, so a customer cannot choose it here.
- Prices are kept in US dollars only. The lira amount belongs to the rate task (AJA-581).

``judge`` checks the plan first. Then it asks the action policy (``decision.py``), which needs
membership and a payment card proof. The server, not the caller, gives the "pricing-decision"
proof: it exists only for a known self-service plan with a price. A plan without a price gives
"configuration_required" and a task for the product owner (G-167).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping, Optional

from atonota_login import decision

PLANS_FILE = Path(__file__).resolve().parent / "policy" / "plans.json"
ACTION = "open-paid-plan"
CURRENCY = "USD"
PRICE_OWNER = "product-owner"
PRICING_EVIDENCE = "pricing-decision"
# The pricing proof holds for the moment of one check only. The final step checks again.
SNAPSHOT = timedelta(microseconds=1)
FILE_KEYS = {"currency", "plans"}
PLAN_KEYS = {"id", "monthlyUsd", "selfService", "priceText"}


class PlanError(ValueError):
    """The plan file breaks a rule."""


@dataclass(frozen=True)
class Plan:
    id: str
    monthly_usd: Optional[int]
    self_service: bool
    price_text: Optional[str]


def _plan(item: object) -> Plan:
    if not isinstance(item, dict) or set(item) != PLAN_KEYS:
        raise PlanError(f"A plan must have exactly these keys: {', '.join(sorted(PLAN_KEYS))}.")
    plan_id, price = item["id"], item["monthlyUsd"]
    self_service, text = item["selfService"], item["priceText"]
    if not isinstance(plan_id, str) or not plan_id:
        raise PlanError("A plan needs an id.")
    if not isinstance(self_service, bool):
        raise PlanError(f"Plan {plan_id}: selfService must be true or false.")
    if self_service:
        # None means the price is not decided yet. That keeps the plan closed (G-167).
        if price is not None and (isinstance(price, bool) or not isinstance(price, int) or price <= 0):
            raise PlanError(f"Plan {plan_id}: the monthly price must be whole dollars above zero.")
        if text is not None:
            raise PlanError(f"Plan {plan_id}: a self-service plan shows its price, not a text.")
    else:
        if price is not None:
            raise PlanError(f"Plan {plan_id}: a plan a person opens has no price.")
        if not isinstance(text, str) or not text.strip():
            raise PlanError(f"Plan {plan_id}: a plan without a price needs its screen text.")
    return Plan(plan_id, price, self_service, text)


class Plans:
    def __init__(self, data: dict):
        if not isinstance(data, dict) or set(data) != FILE_KEYS:
            raise PlanError("The plan file needs exactly 'currency' and 'plans'.")
        if data["currency"] != CURRENCY:
            raise PlanError("Prices are kept in US dollars (USD).")
        if not isinstance(data["plans"], list) or not data["plans"]:
            raise PlanError("The plan file needs a list of plans.")
        self.plans = {}
        for item in data["plans"]:
            plan = _plan(item)
            if plan.id in self.plans:
                raise PlanError(f"Plan {plan.id} is listed twice.")
            self.plans[plan.id] = plan
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.version = hashlib.sha256(canonical).hexdigest()


def load_plans(path: Path = PLANS_FILE) -> Plans:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as error:
        raise PlanError(f"The plan file is not valid JSON ({error.__class__.__name__}).") from None
    return Plans(data)


def _version(policy: decision.Policy, plans: Plans) -> str:
    # One version for both files. A change in either one refuses the final step.
    return hashlib.sha256(f"{policy.version}:{plans.version}".encode("ascii")).hexdigest()


def judge(
    policy: decision.Policy, plans: Plans, plan_id: object, evidence: Mapping[str, object], now: datetime
) -> decision.Result:
    """Judge "open-paid-plan" for one plan. ``evidence`` is what the server holds now."""
    version = _version(policy, plans)
    plan = plans.plans.get(plan_id) if isinstance(plan_id, str) else None
    if plan is None:
        return decision.Result(decision.DENIED, ACTION, version, ("unknown-plan",))
    subject = plan.id
    if not plan.self_service:
        return decision.Result(decision.DENIED, ACTION, version, ("not-self-service",), subject=subject)
    if plan.monthly_usd is None:
        task = {"rule": f"plan-price-{plan.id}", "owner": PRICE_OWNER, "action": ACTION}
        return decision.Result(
            decision.CONFIGURATION_REQUIRED,
            ACTION,
            version,
            ("configuration-required",),
            (task,),
            subject=subject,
        )
    if not isinstance(evidence, Mapping):
        return decision.Result(decision.DENIED, ACTION, version, ("bad-evidence",), subject=subject)
    # A caller's own pricing proof is dropped. The server gives it for this plan only.
    server = {key: value for key, value in evidence.items() if key != PRICING_EVIDENCE}
    server[PRICING_EVIDENCE] = {"status": "valid", "expiresAt": (now + SNAPSHOT).isoformat()}
    result = policy.evaluate(ACTION, server, now)
    return replace(result, policy_version=version, subject=subject)


def confirm(
    policy: decision.Policy,
    plans: Plans,
    earlier: decision.Result,
    plan_id: object,
    evidence: Mapping[str, object],
    now: datetime,
) -> decision.Result:
    """Final step: the earlier result must be for this plan and these files, and still hold."""
    version = _version(policy, plans)
    if earlier.status != decision.READY or earlier.action != ACTION or earlier.subject != plan_id:
        return decision.Result(decision.DENIED, ACTION, version, ("result-not-for-this-action",))
    if earlier.policy_version != version:
        return decision.Result(decision.DENIED, ACTION, version, ("policy-changed",))
    return judge(policy, plans, plan_id, evidence, now)
