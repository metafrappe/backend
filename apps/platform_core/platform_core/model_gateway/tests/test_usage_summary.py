"""Manager usage totals preserve exact costs and the source user/account boundary."""

import hashlib
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from platform_core.model_gateway import ledger, policy


class UsageSummaryTests(unittest.TestCase):
	def setUp(self):
		from platform_core.model_gateway import usage

		self.enterContext(
			patch.object(
				usage,
				"get_permitted_fields",
				create=True,
				return_value=[
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
				],
			)
		)
		self.enterContext(patch.object(frappe, "session", SimpleNamespace(user="manager")))
		self.enterContext(patch.object(usage, "now_datetime", return_value=datetime(2026, 11, 23)))

	def test_hidden_cost_field_denies_summary_before_any_query(self):
		from platform_core.model_gateway import usage

		with (
			patch.object(policy, "require_user"),
			patch.object(usage, "get_permitted_fields", return_value=["name", "user", "account", "currency"]),
			patch.object(ledger, "_usage") as query,
			self.assertRaises(frappe.PermissionError),
		):
			usage.summary()
		query.assert_not_called()

	def row(self, user, account, currency, cost, **changes):
		return SimpleNamespace(
			**{
				"user": user,
				"account": account,
				"currency": currency,
				"result": "success",
				"cost": cost,
				"cost_known": 1,
				"usage_known": 1,
				"input_tokens": 2,
				"output_tokens": 1,
				"reserved_cost": "9",
				"reservation_known": 1,
				**changes,
			}
		)

	def test_summary_separates_users_accounts_and_currencies(self):
		from platform_core.model_gateway import usage

		rows = [
			self.row("first", "shared", "USD", "0.100000001"),
			self.row("second", "shared", "USD", "0.200000002"),
			self.row("first", "other", "EUR", "2"),
			self.row("first", "shared", "USD", "0", result="unknown", cost_known=0),
		]
		with (
			patch.object(policy, "require_user"),
			patch.object(ledger, "_usage", return_value=rows) as query,
			patch.object(usage, "now_datetime", return_value=datetime(2026, 11, 23)),
		):
			result = usage.summary()
		usd = next(row for row in result["team"] if row["currency"] == "USD")
		self.assertEqual(usd["cost"], "0.300000003")
		self.assertEqual(usd["reserved_cost"], "9")
		self.assertEqual(usd["cost_unknown"], 1)
		self.assertEqual(len(result["users"]), 3)
		self.assertEqual(len(result["accounts"]), 2)
		self.assertEqual(
			query.call_args.args[0]["attempted_at"],
			["between", [datetime(2026, 11, 1), datetime(2026, 11, 23)]],
		)
		self.assertEqual(query.call_args.kwargs, {"ignore_permissions": False})

	def test_permission_aware_summary_query_preserves_record_filters_on_every_page(self):
		with patch.object(ledger, "frappe") as framework, patch.object(ledger, "USAGE_PAGE_SIZE", 1):
			framework.qb.get_query.return_value.run.side_effect = [[SimpleNamespace(name="a")], []]
			list(ledger._usage({}, ignore_permissions=False))
		self.assertEqual(len(framework.qb.get_query.call_args_list), 2)
		for call in framework.qb.get_query.call_args_list:
			self.assertIs(call.kwargs["ignore_permissions"], False)

	def test_summary_refuses_nonmanagers_before_loading_any_usage(self):
		from platform_core.model_gateway import usage

		with (
			patch.object(policy, "require_user", side_effect=frappe.PermissionError) as require,
			patch.object(ledger, "_usage") as query,
			self.assertRaises(frappe.PermissionError),
		):
			usage.summary()
		require.assert_called_once_with(managers_only=True)
		query.assert_not_called()

	def test_unbilled_attempt_does_not_inflate_cost_or_unknown_totals(self):
		from platform_core.model_gateway import usage

		with (
			patch.object(policy, "require_user"),
			patch.object(usage, "now_datetime", return_value=datetime(2026, 11, 23)),
			patch.object(
				ledger,
				"_usage",
				return_value=[
					self.row("first", "shared", "USD", "0", result="not_billed", cost_known=0, usage_known=0)
				],
			),
		):
			row = usage.summary()["team"][0]
		self.assertEqual((row["cost"], row["reserved_cost"], row["cost_unknown"]), ("0", "0", 0))

	def test_reservation_uses_the_shared_conversation_digest(self):
		from platform_core import conversation

		stored = []

		def document(values):
			stored.append(values)
			return SimpleNamespace(name="usage-1", db_insert=lambda: None)

		with (
			patch.object(conversation.frappe, "request", object()),
			patch.object(conversation.frappe, "get_request_header", return_value="synthetic-conversation"),
			patch.object(ledger.frappe, "session", SimpleNamespace(user="first")),
			patch.object(ledger.frappe, "db", Mock()),
			patch.object(ledger.frappe, "get_doc", side_effect=document),
			patch.object(ledger, "now_datetime", return_value=datetime(2026, 11, 23)),
		):
			ledger.begin(
				None,
				SimpleNamespace(name="api"),
				SimpleNamespace(name="account"),
				SimpleNamespace(name="provider"),
				SimpleNamespace(name="model", cost_currency="USD"),
				cost=None,
				tokens=4,
			)
		self.assertEqual(stored[0]["session_id"], hashlib.sha256(b"synthetic-conversation").hexdigest())
		self.assertNotIn("synthetic-conversation", repr(stored))

	def test_missing_conversation_header_stays_empty(self):
		from platform_core import conversation

		with patch.object(conversation.frappe, "request", None):
			self.assertIsNone(conversation.session_id())
