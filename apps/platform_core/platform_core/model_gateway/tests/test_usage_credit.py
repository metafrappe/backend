"""AJA-84: outbound privacy and single-settlement credit regressions."""

import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from platform_core.model_gateway import adapters, gateway, ledger, policy, routing


class OutboundPrivacyTests(unittest.TestCase):
	def test_card_is_hidden_with_numbers_on_either_side(self):
		for card in ("4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111"):
			for prefix in ("123", "12345678901", "4111 1111 1111 1111"):
				for suffix in ("123", "12345678901"):
					with self.subTest(card=card, prefix=prefix, suffix=suffix):
						masked = policy._mask(f"{prefix} {card} {suffix}")
						self.assertNotIn("4111", masked)
						self.assertNotIn("1111", masked)

	def test_card_followed_by_another_number_is_masked(self):
		masked = policy._mask("4111 1111 1111 1111 12345678901")
		# Overlapping sensitive spans may share a marker. The contract forbids raw
		# values and card fragments; it does not specify the number of markers.
		for value in ("4111", "1111", "12345678901"):
			self.assertNotIn(value, masked)
		self.assertEqual(policy._mask("4111 1111 1111 1111 123"), "[REDACTED] 123")

	def test_numeric_personal_data_is_rejected_before_reservation_or_dispatch(self):
		for value in (12345678901, 12345678901.0):
			with self.subTest(value_type=type(value).__name__):
				request = policy.parse(
					[{"role": "user", "content": "Use the schema."}],
					[],
					{"type": "number", "const": value},
					8,
				)
				with (
					patch.object(policy, "connection_policy", return_value=("external", (), ())),
					self.assertRaises(policy.Denied) as failure,
				):
					policy.outbound("https://provider.example.test", None, None, request)
				self.assertEqual(failure.exception.code, "data_policy_denied")

	def test_first_provider_payload_contains_only_masked_values(self):
		raw = "member@example.test +90 532 123 45 67 12345678901"
		request = policy.parse(
			[{"role": "user", "content": raw}],
			[{"name": "lookup", "description": raw, "parameters": {"description": raw}}],
			{"type": "string", "enum": [raw]},
			8,
		)
		endpoint = adapters.Endpoint(
			api="fixture",
			adapter="openai",
			base_url="https://provider.example.test",
			auth="none",
			kind="external",
		)
		target = SimpleNamespace(
			api=SimpleNamespace(name="fixture", health_status="healthy"),
			model=SimpleNamespace(name="fixture", model_id="fixture", output_tokens_per_second=30),
			base_url=endpoint.base_url,
			oauth_url=None,
			endpoint=lambda: endpoint,
		)
		candidate = routing.Candidate("fixture", "fixture")
		response = {
			"choices": [{"message": {"content": "OK"}}],
			"usage": {"prompt_tokens": 2, "completion_tokens": 1},
		}
		with (
			patch.object(gateway, "_choose", return_value=[(candidate, target)]),
			patch.object(gateway, "_target", return_value=target),
			patch.object(policy, "connection_policy", return_value=("external", (), ())),
			patch.object(gateway, "_reserve", return_value="usage-1") as reserve,
			patch.object(ledger, "is_pending", return_value=True),
			patch.object(ledger, "finish") as finish,
			patch.object(adapters, "_post_json", return_value=(200, response)) as send,
		):
			gateway._dispatch(None, [target], request, float("inf"))
		self.assertEqual(send.call_count, 1)
		payload = json.dumps(send.call_args.kwargs["json"])
		for value in ("member@example.test", "+90 532 123 45 67", "12345678901"):
			self.assertNotIn(value, payload)
			self.assertNotIn(value, repr(finish.call_args))
		self.assertIn("[REDACTED]", payload)
		self.assertNotIn(raw, repr(reserve.call_args))
		self.assertEqual(request.messages[0]["content"], raw)


class CreditSettlementTests(unittest.TestCase):
	def test_repeated_completion_keeps_the_first_charge(self):
		row = {"name": "usage-1", "result": "pending"}

		def settle(doctype, filters, values):
			if all(row.get(key) == value for key, value in filters.items()):
				row.update(values)

		db = Mock(set_value=settle)
		model = SimpleNamespace(prices_known=True, input_price="1000000", output_price="1000000")
		with patch.object(ledger.frappe, "db", db):
			ledger.finish("usage-1", model, "success", 10, {"input": 2, "output": 1})
			ledger.finish("usage-1", model, "success", 20, {"input": 100, "output": 100})
		self.assertEqual(row["cost"], Decimal("3"))
		self.assertEqual(row["duration_ms"], 10)

	def test_proven_unsent_timeout_releases_reservation(self):
		target = Mock()
		target.account.has_monthly_budget = True
		target.api.name = "fixture"
		with (
			patch.object(ledger, "is_pending", return_value=True),
			patch.object(ledger, "finish") as finish,
			patch.object(gateway, "_set_health"),
			patch.object(gateway.frappe, "cache", Mock()),
			patch.object(
				adapters, "complete", side_effect=adapters.GatewayError("timeout", may_be_billed=False)
			),
			self.assertRaises(policy.Denied),
		):
			gateway._attempt(
				routing.Candidate("fixture", "fixture"), target, Mock(), 30, float("inf"), "usage-1"
			)
		self.assertEqual(finish.call_args.args[2], "not_billed")
		self.assertNotIn("not_billed", ledger.POTENTIALLY_BILLED)

	def test_ambiguous_timeout_keeps_credit_until_reconciliation(self):
		target = Mock()
		target.account.has_monthly_budget = True
		target.api.name = "fixture"
		with (
			patch.object(ledger, "is_pending", return_value=True),
			patch.object(ledger, "finish") as finish,
			patch.object(gateway, "_set_health"),
			patch.object(gateway.frappe, "cache", Mock()),
			patch.object(
				adapters, "complete", side_effect=adapters.GatewayError("timeout", may_be_billed=True)
			),
			self.assertRaises(policy.Denied),
		):
			gateway._attempt(
				routing.Candidate("fixture", "fixture"), target, Mock(), 30, float("inf"), "usage-1"
			)
		self.assertEqual(finish.call_args.args[2], "unknown")
		self.assertIn("unknown", ledger.POTENTIALLY_BILLED)
