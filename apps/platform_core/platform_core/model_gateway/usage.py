"""Read-only monthly totals of the manager's readable tenant usage records."""

from decimal import Decimal
from typing import NotRequired, TypedDict

import frappe
from frappe.model import get_permitted_fields
from frappe.utils import now_datetime

from platform_core.model_gateway import ledger, policy

REQUIRED_FIELDS = frozenset(
	{
		"name",
		"user",
		"account",
		"currency",
		"attempted_at",
		"result",
		"usage_known",
		"input_tokens",
		"output_tokens",
		"cost",
		"cost_known",
		"reserved_cost",
		"reservation_known",
	}
)


class UsageTotal(TypedDict):
	currency: str
	requests: int
	input_tokens: int
	output_tokens: int
	usage_unknown: int
	cost: str
	reserved_cost: str
	cost_unknown: int
	user: NotRequired[str]
	account: NotRequired[str]


class UsageSummary(TypedDict):
	period_start: str
	as_of: str
	team: list[UsageTotal]
	users: list[UsageTotal]
	accounts: list[UsageTotal]


def _add(groups, key, row):
	total = groups.setdefault(
		key,
		{
			"currency": row.currency,
			"requests": 0,
			"input_tokens": 0,
			"output_tokens": 0,
			"usage_unknown": 0,
			"cost": Decimal(0),
			"reserved_cost": Decimal(0),
			"cost_unknown": 0,
		},
	)
	total["requests"] += 1
	if row.usage_known:
		total["input_tokens"] += row.input_tokens
		total["output_tokens"] += row.output_tokens
	else:
		total["usage_unknown"] += 1
	if row.result in ledger.POTENTIALLY_BILLED:
		if row.result not in ledger.UNSETTLED and row.cost_known:
			total["cost"] += Decimal(str(row.cost))
		else:
			total["cost_unknown"] += 1
			if row.reservation_known:
				total["reserved_cost"] += Decimal(str(row.reserved_cost))


def _rows(groups, dimension=None):
	result = []
	for key, total in sorted(groups.items()):
		row = {
			**total,
			"cost": format(total["cost"], "f"),
			"reserved_cost": format(total["reserved_cost"], "f"),
		}
		if dimension:
			row[dimension] = key[0]
		result.append(row)
	return result


def summary() -> UsageSummary:
	"""Require a manager before reading the site's accounting records."""
	policy.require_user(managers_only=True)
	# Frappe accepts prebuilt Cast terms without checking their source field's
	# permlevel. Deny a partial financial report instead of exposing hidden costs.
	readable = get_permitted_fields(
		"PLT AI Usage Log", permission_type="read", ignore_virtual=True, user=frappe.session.user
	)
	if not REQUIRED_FIELDS.issubset(readable):
		raise frappe.PermissionError
	cutoff = now_datetime()
	start = cutoff.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
	team, users, accounts = {}, {}, {}
	for row in ledger._usage({"attempted_at": ["between", [start, cutoff]]}, ignore_permissions=False):
		_add(team, (row.currency,), row)
		_add(users, (row.user, row.currency), row)
		_add(accounts, (row.account, row.currency), row)
	return {
		"period_start": start.isoformat(),
		"as_of": cutoff.isoformat(),
		"team": _rows(team),
		"users": _rows(users, "user"),
		"accounts": _rows(accounts, "account"),
	}
