"""Signed ingress tests use the real endpoint wrapper and a minimal Frappe fixture."""

import hashlib
import hmac
import importlib.util
import json
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from platform_core.ai import press_events


class PressStatusEndpointTests(unittest.TestCase):
	def setUp(self):
		self.key = bytes(range(32))
		self.body = json.dumps(
			dict(
				capture="hook",
				event_id="event-1",
				event_type="press.job_status.changed.v1",
				occurred_at="2026-11-24T00:00:00Z",
				record_type="Agent Job",
				record_name="job-1",
				old_status="Running",
				new_status="Success",
				team="team-1",
				site="site.test",
			)
		).encode()
		self.rows = {}
		self.writes = 0
		self.f = types.ModuleType("frappe")
		self.f.conf = {"press_job_status_keys": {"current": self.key}}
		self.f.local = types.SimpleNamespace(response={})
		self.f.session = types.SimpleNamespace(user="Guest")
		self.f.form_dict = {}
		self.f.AuthenticationError = type("AuthenticationError", (Exception,), {})
		self.f.whitelist = lambda **kwargs: lambda function: function
		self.rate = types.ModuleType("frappe.rate_limiter")
		self.rate_counts = {}
		self.rate.rate_limit = self.rate_limit
		self.reads = 0
		self.f.RateLimitExceededError = type(
			"RateLimitExceededError", (self.f.AuthenticationError,), {"http_status_code": 429}
		)
		self.f.get_doc = self.document
		spec = importlib.util.spec_from_file_location(
			"press_status_route_under_test", Path(__file__).with_name("press_status.py")
		)
		self.route = importlib.util.module_from_spec(spec)
		with patch.dict(sys.modules, {"frappe": self.f, "frappe.rate_limiter": self.rate}):
			spec.loader.exec_module(self.route)

	def rate_limit(self, *, limit, seconds, endpoint=None, **kwargs):
		def decorate(function):
			def wrapped(*args, **kwargs):
				key = endpoint or function.__name__
				self.rate_counts[key] = self.rate_counts.get(key, 0) + 1
				if self.rate_counts[key] > limit:
					raise self.f.RateLimitExceededError("rate_limit")
				return function(*args, **kwargs)

			return wrapped

		return decorate

	def read_body(self, body):
		self.reads += 1
		return body

	def document(self, values):
		def insert(**kwargs):
			if values["event_id"] not in self.rows:
				self.rows[values["event_id"]] = values
				self.writes += 1

		return types.SimpleNamespace(insert=insert)

	def call(self, headers=None, body=None, secure=True, query=None, path=None):
		body = self.body if body is None else body
		now = str(int(time.time()))
		if headers is None:
			headers = {
				"X-Press-Event-Id": "event-1",
				"X-Press-Timestamp": now,
				"X-Press-Key-Id": "current",
				"X-Press-Signature": "v1="
				+ hmac.new(self.key, now.encode() + b".event-1." + body, hashlib.sha256).hexdigest(),
			}
		self.f.request = types.SimpleNamespace(
			headers=headers,
			is_secure=secure,
			get_data=lambda **kwargs: self.read_body(body),
			content_length=len(body),
			method="POST",
			mimetype="application/octet-stream",
			args=query or {},
			path=path or "/api/method/platform_core.api.press_status.receive",
		)
		self.f.local.response = {}
		with patch.dict(sys.modules, {"frappe": self.f, "frappe.rate_limiter": self.rate}):
			try:
				press_events.guard_request()
				result = self.route.receive()
			except self.f.AuthenticationError as error:
				self.f.local.response["http_status_code"] = error.http_status_code
				result = {"error": str(error)}
		return self.f.local.response.get("http_status_code", 200), result

	def test_receive_guest_denied(self):
		status, _response = self.call(headers={})
		self.assertEqual(status, 401)
		self.assertEqual(self.writes, 0)

	def test_receive_foreign_data_denied(self):
		status, _response = self.call(headers={"X-Press-Key-Id": "another-tenant"})
		self.assertEqual(status, 401)
		self.assertEqual(self.rows, {})

	def test_authenticated_event_is_inserted_once_across_retries(self):
		for _attempt in range(2):
			status, result = self.call()
			self.assertEqual(status, 200)
			self.assertEqual(result, {"accepted": True, "event_id": "event-1"})
		self.assertEqual(self.writes, 1)
		self.assertEqual(self.f.session.user, "Guest")

	def test_invalid_json_is_authenticated_before_parsing(self):
		status, _response = self.call(headers={}, body=b"{")
		self.assertEqual(status, 401)
		status, _response = self.call(body=b"{")
		self.assertEqual(status, 400)
		self.assertEqual(self.writes, 0)

	def test_unsigned_broken_unknown_key_and_old_events_do_not_write(self):
		now = str(int(time.time()))
		valid = {
			"X-Press-Event-Id": "event-1",
			"X-Press-Timestamp": now,
			"X-Press-Key-Id": "current",
			"X-Press-Signature": "v1="
			+ hmac.new(self.key, now.encode() + b".event-1." + self.body, hashlib.sha256).hexdigest(),
		}
		for changed in (
			{"X-Press-Signature": ""},
			{"X-Press-Signature": "broken"},
			{"X-Press-Key-Id": "unknown"},
			{"X-Press-Timestamp": str(int(now) - 301)},
		):
			status, _response = self.call(headers={**valid, **changed})
			self.assertEqual(status, 401)
		self.assertEqual(self.writes, 0)

	def test_agent_channel_requires_https(self):
		status, _response = self.call(secure=False)
		self.assertEqual(status, 401)
		self.assertEqual(self.writes, 0)

	def test_query_dispatch_and_noncanonical_aliases_are_rejected(self):
		status, _response = self.call(query={"cmd": "frappe.ping"})
		self.assertEqual(status, 401)
		status, _response = self.call(path="/api/v1/method/platform_core.api.press_status.receive")
		self.assertEqual(status, 401)
		self.assertEqual(self.writes, 0)

	def test_rejected_traffic_is_rate_limited_before_signature_verification(self):
		for _attempt in range(120):
			status, _response = self.call(headers={})
			self.assertEqual(status, 401)
		reads = self.reads
		status, _response = self.call(headers={})
		self.assertEqual(status, 429)
		self.assertEqual(self.reads, reads)
		self.assertEqual(self.writes, 0)

	def test_known_oversize_body_is_rejected_before_endpoint_reads_it(self):
		status, _response = self.call(body=b"x" * 16385)
		self.assertEqual(status, 413)
		self.assertEqual(self.reads, 0)
		self.assertEqual(self.writes, 0)
