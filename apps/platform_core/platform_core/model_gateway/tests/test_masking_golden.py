"""G-90 golden tests: personal data is masked locally before any external model call.

The tests need no Frappe site. When Frappe is not installed, a small stand-in module
supplies only ``frappe.conf``. The network record test also needs ``requests``.
"""

import importlib.util
import json
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

if importlib.util.find_spec("frappe") is None:
	stand_in = types.ModuleType("frappe")
	stand_in.conf = {}
	stand_in.PermissionError = PermissionError
	sys.modules["frappe"] = stand_in

import frappe

from platform_core.model_gateway import policy

EXTERNAL = "https://provider.example.test"
REDACTED = "[REDACTED]"

# Each raw value must leave the gateway as exactly one "[REDACTED]" marker.
GOLDEN_SENSITIVE = {
	"tckn": "10000000146",
	"tckn_spaced": "100 000 001 46",
	"vkn": "4840847211",
	"iban": "TR33 0006 1005 1978 6457 8413 26",
	"iban_compact": "TR330006100519786457841326",
	"iban_lowercase": "tr330006100519786457841326",
	"card_spaced": "4111 1111 1111 1111",
	"card_dashed": "5500-0000-0000-0004",
	"card_compact": "4111111111111111",
	"phone_international": "+90 532 000 00 01",
	"phone_national": "0532 000 00 02",
	"phone_parenthesis": "(212) 000 00 03",
	"email": "ayse.yilmaz@example.com",
}

# These values look numeric but are not personal data. They must reach the model unchanged.
GOLDEN_KEPT = {
	"order_number": "Order 12345678901234567890",
	"non_luhn_card_like": "4111 1111 1111 1112",
	"short_number": "Invoice 2026-11",
	"amount": "Total 1.250,00 TRY",
}


def endpoints(setting):
	# frappe.conf is unbound without a site, so replace it with a plain dict.
	return patch.object(frappe, "conf", {"model_gateway_endpoints": setting})


def external_conf():
	return endpoints({EXTERNAL: "external"})


def masked_route():
	return SimpleNamespace(name="golden-route", data_policy="masked")


def outbound(request, route=None):
	with external_conf():
		return policy.outbound(EXTERNAL, "", route, request)


def message_request(content, tools=(), schema=None):
	return policy.parse([{"role": "user", "content": content}], list(tools), schema, 32)


class TestGoldenMasking(unittest.TestCase):
	def test_each_sensitive_class_is_masked_in_messages(self):
		for label, raw in GOLDEN_SENSITIVE.items():
			with self.subTest(label=label):
				sent = outbound(message_request(f"Customer value: {raw}.")).messages[0]["content"]
				self.assertEqual(sent, f"Customer value: {REDACTED}.")

	def test_values_that_are_not_personal_data_are_kept(self):
		for label, text in GOLDEN_KEPT.items():
			with self.subTest(label=label):
				sent = outbound(message_request(text)).messages[0]["content"]
				self.assertEqual(sent, text)

	def test_mixed_message_masks_every_value_and_keeps_the_rest(self):
		text = " | ".join((*GOLDEN_SENSITIVE.values(), *GOLDEN_KEPT.values()))
		sent = outbound(message_request(text)).messages[0]["content"]
		self.assertEqual(sent.count(REDACTED), len(GOLDEN_SENSITIVE))
		for raw in GOLDEN_SENSITIVE.values():
			self.assertNotIn(raw, sent)
		for kept in GOLDEN_KEPT.values():
			self.assertIn(kept, sent)

	def test_every_message_role_is_masked(self):
		raw = GOLDEN_SENSITIVE["tckn"]
		messages = [{"role": role, "content": raw} for role in ("system", "user", "assistant")]
		sent = outbound(policy.parse(messages, [], None, 32))
		self.assertEqual([item["content"] for item in sent.messages], [REDACTED] * 3)

	def test_tool_definitions_and_schema_are_masked(self):
		raw = GOLDEN_SENSITIVE["email"]
		tool = {
			"name": "lookup_customer",
			"description": f"Example: {raw}",
			"parameters": {"type": "object", "examples": [raw, {"note": raw}]},
		}
		schema = {"type": "object", "description": raw}
		sent = outbound(message_request("Hello", [tool], schema))
		wire = json.dumps([sent.tools, sent.schema])
		self.assertNotIn(raw, wire)
		self.assertEqual(wire.count(REDACTED), 4)

	def test_personal_data_in_a_key_or_number_is_refused(self):
		cases = {
			"dict_key": message_request("Hello", schema={GOLDEN_SENSITIVE["tckn"]: "x"}),
			"integer": message_request("Hello", schema={"value": int(GOLDEN_SENSITIVE["tckn"])}),
		}
		for label, request in cases.items():
			with self.subTest(label=label):
				with self.assertRaises(policy.Denied) as failure:
					outbound(request)
				self.assertEqual(
					(failure.exception.status, failure.exception.code), (403, "data_policy_denied")
				)

	def test_masking_does_not_change_the_caller_request(self):
		raw = GOLDEN_SENSITIVE["iban"]
		request = message_request(raw)
		outbound(request)
		self.assertEqual(request.messages[0]["content"], raw)

	def test_external_route_without_masked_policy_is_refused(self):
		route = SimpleNamespace(name="golden-route", data_policy="local_only")
		with self.assertRaises(policy.Denied) as failure:
			outbound(message_request("Hello"), route)
		self.assertEqual((failure.exception.status, failure.exception.code), (403, "data_policy_denied"))

	def test_test_call_without_route_is_still_masked(self):
		# test_api dispatches with route=None. It must not bypass masking.
		raw = GOLDEN_SENSITIVE["tckn"]
		self.assertEqual(outbound(message_request(raw), None).messages[0]["content"], REDACTED)

	def test_unknown_endpoint_is_refused_before_any_call(self):
		with endpoints({}):
			with self.assertRaises(policy.Denied) as failure:
				policy.outbound(EXTERNAL, "", masked_route(), message_request("Hello"))
		self.assertEqual((failure.exception.status, failure.exception.code), (503, "endpoint_unavailable"))

	def test_only_deployment_approved_local_endpoint_gets_raw_text(self):
		raw = GOLDEN_SENSITIVE["tckn"]
		local = "http://127.0.0.1:11434"
		setting = {local: {"kind": "local", "addresses": ["127.0.0.1"]}}
		with endpoints(setting):
			sent = policy.outbound(local, "", masked_route(), message_request(raw))
		self.assertEqual(sent.messages[0]["content"], raw)


class _RecordingHandler(BaseHTTPRequestHandler):
	def log_message(self, *args):
		pass

	def do_POST(self):
		raw = self.rfile.read(int(self.headers["Content-Length"]))
		self.server.records.append((self.path, bytes(raw)))
		body = json.dumps(
			{
				"message": {"role": "assistant", "content": "OK"},
				"done": True,
				"prompt_eval_count": 1,
				"eval_count": 1,
			}
		).encode()
		self.send_response(200)
		self.send_header("Content-Type", "application/json")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)


@unittest.skipIf(importlib.util.find_spec("requests") is None, "The network record test needs requests")
class TestNetworkRecord(unittest.TestCase):
	"""Send the masked request through the real adapter and inspect the bytes on the wire."""

	def setUp(self):
		self.server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
		self.server.records = []
		self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
		self.thread.start()
		self.addCleanup(self.thread.join, 5)
		self.addCleanup(self.server.server_close)
		self.addCleanup(self.server.shutdown)

	def test_wire_payload_has_no_raw_personal_value(self):
		from platform_core.model_gateway import adapters

		text = " | ".join((*GOLDEN_SENSITIVE.values(), *GOLDEN_KEPT.values()))
		tool = {
			"name": "lookup_customer",
			"description": f"Example: {GOLDEN_SENSITIVE['email']}",
			"parameters": {"type": "object"},
		}
		sent = outbound(message_request(text, [tool]), masked_route())
		# The recording server stands in for the external provider. The adapter must
		# reach it over plain HTTP, so it is declared as a pinned local address here.
		adapters.complete(
			adapters.Endpoint(
				"golden-api",
				"ollama",
				f"http://127.0.0.1:{self.server.server_port}",
				kind="local",
				addresses=("127.0.0.1",),
			),
			"golden-model",
			sent.messages,
			sent.limit,
			tools=sent.tools,
			schema=sent.schema,
		)
		self.assertEqual(len(self.server.records), 1)
		path, raw = self.server.records[0]
		self.assertEqual(path, "/api/chat")
		wire = raw.decode()
		for label, value in GOLDEN_SENSITIVE.items():
			with self.subTest(label=label):
				self.assertNotIn(value, wire)
				self.assertNotIn(json.dumps(value)[1:-1], wire)
		self.assertEqual(wire.count(REDACTED), len(GOLDEN_SENSITIVE) + 1)
		for kept in GOLDEN_KEPT.values():
			self.assertIn(kept, wire)


if __name__ == "__main__":
	unittest.main()
