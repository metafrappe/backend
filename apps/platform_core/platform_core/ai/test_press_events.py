"""O-57 acceptance: signed metadata, rejected credentials and strict payloads."""

import hashlib
import hmac
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from platform_core.ai.press_events import RejectedEventError, authenticate, parse_event


class PressEventProtocolTests(unittest.TestCase):
	def setUp(self):
		self.key = bytes(range(32))
		self.event = dict(
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
		self.body = json.dumps(self.event).encode()
		self.headers = {
			"X-Press-Event-Id": "event-1",
			"X-Press-Timestamp": "1800000000",
			"X-Press-Key-Id": "current",
			"X-Press-Signature": "v1="
			+ hmac.new(self.key, b"1800000000.event-1." + self.body, hashlib.sha256).hexdigest(),
		}

	def check(self, headers=None, body=None, keys=None, now=1800000000):
		return authenticate(
			self.body if body is None else body,
			self.headers if headers is None else headers,
			{"current": self.key} if keys is None else keys,
			now=now,
		)

	def test_valid_signature_accepts_exact_event_id(self):
		self.assertEqual(self.check(), "event-1")
		self.assertEqual(parse_event(self.body, "event-1"), self.event)

	def test_unsigned_malformed_unknown_key_and_stale_requests_return_401(self):
		cases = [
			{},
			{**self.headers, "X-Press-Signature": "broken"},
			{**self.headers, "X-Press-Key-Id": "unknown"},
			{**self.headers, "X-Press-Timestamp": "1799999699"},
		]
		for headers in cases:
			with self.subTest(headers=tuple(headers)), self.assertRaises(RejectedEventError) as caught:
				self.check(headers=headers)
			self.assertEqual(caught.exception.status, 401)

	def test_key_rotation_preserves_old_and_new_keys(self):
		self.assertEqual(self.check(keys={"current": self.key, "next": b"n" * 32}), "event-1")
		with self.assertRaises(RejectedEventError):
			self.check(keys={"next": b"n" * 32})

	def test_timestamp_and_event_id_and_raw_body_are_bound(self):
		for change in ({"X-Press-Timestamp": "1800000001"}, {"X-Press-Event-Id": "event-2"}):
			with self.subTest(change=change), self.assertRaises(RejectedEventError):
				self.check(headers={**self.headers, **change})
		with self.assertRaises(RejectedEventError):
			self.check(body=self.body + b" ")

	def test_time_window_has_two_boundaries(self):
		for offset in (-300, 300):
			self.assertEqual(self.check(now=1800000000 + offset), "event-1")
		for offset in (-301, 301):
			with self.assertRaises(RejectedEventError):
				self.check(now=1800000000 + offset)

	def test_body_size_and_key_strength_are_bounded(self):
		with self.assertRaises(RejectedEventError) as caught:
			self.check(body=b"x" * 16385)
		self.assertEqual(caught.exception.status, 413)
		with self.assertRaises(RejectedEventError):
			self.check(keys={"current": b"short"})

	def test_secret_execution_fields_and_unknown_fields_are_rejected(self):
		for field in ("data", "output", "traceback", "unexpected"):
			with self.subTest(field=field), self.assertRaises(RejectedEventError) as caught:
				parse_event(json.dumps({**self.event, field: "private"}).encode(), "event-1")
			self.assertEqual(caught.exception.status, 400)

	def test_body_event_id_must_match_signed_header(self):
		with self.assertRaises(RejectedEventError):
			parse_event(self.body, "another-event")

	def test_missing_invalid_and_duplicate_json_fields_are_rejected(self):
		cases = [b"[]", b"null", b"{", self.body[:-1] + b',"event_id":"event-1"}']
		for key, value in (
			("occurred_at", "tomorrow"),
			("record_type", "User"),
			("new_status", ""),
			("record_name", 123),
			("team", []),
			("new_status", "x" * 141),
		):
			cases.append(json.dumps({**self.event, key: value}).encode())
		for body in cases:
			with self.subTest(body=body[:25]), self.assertRaises(RejectedEventError):
				parse_event(body, "event-1")

	def test_non_utf8_and_compact_dates_are_rejected(self):
		cases = [
			self.body.decode().encode("utf-16"),
			json.dumps({**self.event, "occurred_at": "20261124T000000Z"}).encode(),
		]
		for body in cases:
			with self.subTest(body=body[:10]):
				with self.assertRaises(RejectedEventError) as caught:
					parse_event(body, "event-1")
				self.assertEqual(caught.exception.status, 400)
