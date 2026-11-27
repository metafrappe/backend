"""Frappe link of the `atonota_login` action decision (G-161, G-166, G-167).

The rules live in the `atonota_login` package (`atonota_login.decision`). That package has no Frappe
code. This module is the thin Frappe layer around it:

1. It collects the evidence the server holds now, from Frappe records.
2. It turns "configuration_required" into one Frappe task per empty rule.
3. It runs the write of a final step only after `Policy.confirm` says "ready" again.

The caller never supplies evidence. Request fields and token roles are not read.
The paid plan step also checks the plan (`atonota_login.plans`, decision AJA-18).
The server has no payment card source yet: there is no Team Tier code. So `collect_evidence` never
gives a "payment-card" proof and no paid plan opens. A card proof must come from a server record.
Membership is read from the server's `User.user_type` for now. Frappe derives that field from the
user's desk roles on save, so a desk role on the server record gives membership evidence. This is a
known debt until the organisation membership record exists (G-160, PROJECT-RECORD.md).
Contract: `backend/contracts/platform_core-identity.openapi.yaml`, tag `atonota-login`.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import frappe
from atonota_login import decision, plans
from frappe import _

from platform_core.identity.exceptions import InvalidInput

MAX_ACTION_LENGTH = 140
# Evidence collected in one request holds for that moment only. It is not a proof lifetime
# (the "proof-lifetimes" rule has no value yet). The final step collects the evidence again.
SNAPSHOT = timedelta(microseconds=1)
TASK_ROLE = "System Manager"
TASK_MARK = "[atonota_login rule]"


class ActionRefused(frappe.PermissionError):
	"""The decision for the action is not "ready". The message names the decision state."""

	http_status_code = 403


class BillingNotConnected(frappe.ValidationError):
	"""The gate said "ready", but the P2 billing flow is not connected. Nothing is written."""

	http_status_code = 409


class PendingWrites(frappe.ValidationError):
	"""The request already holds writes. A final step does not start then (AJA-264)."""

	http_status_code = 409


def now_utc() -> datetime:
	return datetime.now(UTC)


def _load_policy() -> decision.Policy:
	# Read for every check. The final step compares the policy versions of its two checks.
	return decision.load_policy()


def _proof(now: datetime) -> dict:
	return {"status": "valid", "expiresAt": (now + SNAPSHOT).isoformat()}


def collect_evidence(user: str, now: datetime) -> dict:
	"""Evidence for `user` from Frappe records. Token and request roles are not read.

	Membership comes from `user_type`, which Frappe derives from the server record's desk roles
	(known debt, G-160).
	"""
	if not user or user == "Guest":
		return {}
	row = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	if not row or not row.enabled:
		return {}
	evidence = {}
	if frappe.db.exists("PLT Identity Link", {"user": user}):
		evidence["identity"] = _proof(now)
	if row.user_type == "System User":
		evidence["membership"] = _proof(now)
	return evidence


def _signed_in_user() -> str:
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Sign in to continue.", context="platform_core.identity"), frappe.PermissionError)
	return user


def _as_dict(result: decision.Result) -> dict:
	return {
		"status": result.status,
		"action": result.action,
		"policy_version": result.policy_version,
		"reasons": list(result.reasons),
		"owner_tasks": [dict(task) for task in result.owner_tasks],
	}


def _task_text(task: dict) -> str:
	return (
		f"{TASK_MARK} The rule {task['rule']} has no value yet. Owner: {task['owner']}. "
		f"Waiting action: {task['action']}. The action stays closed until the owner decides."
	)


def open_owner_tasks(result: decision.Result) -> None:
	"""One open task per empty rule and action, for the system manager role (G-167)."""
	for task in result.owner_tasks:
		text = _task_text(task)
		if frappe.db.exists("ToDo", {"status": "Open", "description": text}):
			continue
		frappe.get_doc({"doctype": "ToDo", "status": "Open", "description": text, "role": TASK_ROLE}).insert(
			ignore_permissions=True
		)


def _judge(action_id: str, user: str) -> decision.Result:
	now = now_utc()
	result = _load_policy().evaluate(action_id, collect_evidence(user, now), now)
	if result.status == decision.CONFIGURATION_REQUIRED:
		open_owner_tasks(result)
	return result


def _load_plans() -> plans.Plans:
	return plans.load_plans()


def _judge_plan(plan_id: str, user: str) -> decision.Result:
	now = now_utc()
	result = plans.judge(_load_policy(), _load_plans(), plan_id, collect_evidence(user, now), now)
	if result.status == decision.CONFIGURATION_REQUIRED:
		open_owner_tasks(result)
	return result


def _is_short_text(value: object) -> bool:
	return isinstance(value, str) and bool(value) and len(value) <= MAX_ACTION_LENGTH


def evaluate(action: object) -> dict:
	"""Decision for the signed-in user. Called by `platform_core.api.atonota_login.evaluate`."""
	user = _signed_in_user()
	if not _is_short_text(action):
		frappe.throw(
			_(
				"The action field must be a non-empty text of at most 140 characters.",
				context="platform_core.identity",
			),
			InvalidInput,
		)
	return _as_dict(_judge(action, user))


def _refuse(result: decision.Result) -> None:
	frappe.throw(
		_("The action {0} is not allowed now ({1}).", context="platform_core.identity").format(
			result.action, result.status
		),
		ActionRefused,
	)


def _start_final_step() -> str:
	user = _signed_in_user()
	# A refusal below may commit the owner task. That commit must never make a caller's earlier
	# writes permanent, so the final step starts only in a clean transaction (AJA-264).
	if frappe.db.transaction_writes:
		frappe.throw(
			_(
				"A final step cannot run inside a transaction with pending writes.",
				context="platform_core.identity",
			),
			PendingWrites,
		)
	return user


def _keep_owner_tasks(earlier: decision.Result) -> None:
	if earlier.owner_tasks:
		# The refusal rolls the request back. The owner task must stay (G-167), so it is committed first.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit


def _refuse_final(action_id: str, final: decision.Result) -> None:
	reason = ", ".join(final.reasons) or final.status
	frappe.throw(
		_("The action {0} is not allowed now ({1}: {2}).", context="platform_core.identity").format(
			action_id, final.status, reason
		),
		ActionRefused,
	)


def run_final_step[T](action_id: str, work: Callable[[], T]) -> T:
	"""Runs `work` only if the action is ready, and still ready at the final check (G-161).

	The final check loads the policy again and collects the evidence again. `Policy.confirm` refuses
	a result of another action, a changed policy and evidence that is gone. The caller must not hold
	pending writes: `PendingWrites` is raised before any decision.
	"""
	user = _start_final_step()
	earlier = _judge(action_id, user)
	if earlier.status != decision.READY:
		_keep_owner_tasks(earlier)
		_refuse(earlier)
	now = now_utc()
	final = _load_policy().confirm(earlier, action_id, collect_evidence(user, now), now)
	if final.status != decision.READY:
		_refuse_final(action_id, final)
	return work()


def _hand_to_billing(plan: plans.Plan) -> dict:
	# Billing uses the P2 commercial flow (AJA-18, decision 9). That flow is not connected to this
	# endpoint yet, so the passed gate writes nothing and says so. No own payment code is added.
	frappe.throw(
		_(
			"The plan {0} passed the gate, but billing is not connected yet. Nothing was written.",
			context="platform_core.identity",
		).format(plan.id),
		BillingNotConnected,
	)


def open_paid_plan(plan: object = None) -> dict:
	"""Final step: open the paid plan `plan` for the signed-in user (G-166, AJA-18).

	Starter and Growth need membership and a payment card proof from a server record. Enterprise
	is opened by a person and is always refused here. The plan and the evidence are checked again
	right before the write.
	"""
	user = _start_final_step()
	if not _is_short_text(plan):
		frappe.throw(
			_(
				"The plan field must be a non-empty text of at most 140 characters.",
				context="platform_core.identity",
			),
			InvalidInput,
		)
	earlier = _judge_plan(plan, user)
	if earlier.status != decision.READY:
		_keep_owner_tasks(earlier)
		_refuse_final(plans.ACTION, earlier)
	now = now_utc()
	plan_set = _load_plans()
	final = plans.confirm(_load_policy(), plan_set, earlier, plan, collect_evidence(user, now), now)
	if final.status != decision.READY:
		_refuse_final(plans.ACTION, final)
	return _hand_to_billing(plan_set.plans[plan])
