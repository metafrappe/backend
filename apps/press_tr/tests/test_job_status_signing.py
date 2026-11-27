"""G-15: absent, altered and stale event signatures must be rejected.

The O-57 protocol signs ``<Unix seconds>.<event id>.<raw body>``
with HMAC-SHA256. A five-minute window includes its boundary. Authenticating
an event does not authenticate a Press user or authorize customer webhooks.
"""

import hashlib
import hmac
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from press_tr.job_status.signing import InvalidSignature, sign_event, verify_event


class StatusEventSignatureTests(unittest.TestCase):
	def setUp(self):
		self.secret = bytes(range(32))
		self.body = b'{"event_id":"event-1","status":"Success"}'
		self.timestamp = 1_800_000_000
		self.signature = (
			"v1=" + hmac.new(self.secret, b"1800000000.event-1." + self.body, hashlib.sha256).hexdigest()
		)

	def verify(self, *, body=None, secret=None, timestamp=None, signature=None, now=None):
		return verify_event(
			self.body if body is None else body,
			self.secret if secret is None else secret,
			str(self.timestamp) if timestamp is None else timestamp,
			self.signature if signature is None else signature,
			now=self.timestamp if now is None else now,
			event_id="event-1",
		)

	def test_sender_matches_the_documented_hmac_bytes(self):
		self.assertEqual(
			sign_event(self.body, self.secret, self.timestamp, event_id="event-1"), self.signature
		)

	def test_valid_signature_is_accepted(self):
		self.assertIsNone(self.verify())

	def test_unsigned_and_malformed_events_are_rejected(self):
		for signature in ("", "v1=", "sha1=" + "0" * 64, "v1=" + "z" * 64):
			with self.subTest(signature=signature), self.assertRaises(InvalidSignature):
				self.verify(signature=signature)

	def test_body_tampering_and_another_key_are_rejected(self):
		for change in ({"body": self.body + b" "}, {"secret": b"other-channel-key" * 2}):
			with self.subTest(change=tuple(change)), self.assertRaises(InvalidSignature):
				self.verify(**change)

	def test_timestamp_is_covered_by_signature(self):
		with self.assertRaises(InvalidSignature):
			self.verify(timestamp=str(self.timestamp + 1))

	def test_old_and_future_events_are_rejected(self):
		for offset in (-301, 301):
			with self.subTest(offset=offset), self.assertRaises(InvalidSignature):
				self.verify(now=self.timestamp + offset)

	def test_freshness_boundary_is_inclusive(self):
		for offset in (-300, 300):
			with self.subTest(offset=offset):
				self.assertIsNone(self.verify(now=self.timestamp + offset))

	def test_ambiguous_and_unbounded_timestamps_are_rejected(self):
		for timestamp in ("", "+1800000000", "01800000000", "1.8e9", "1" * 1000):
			with self.subTest(timestamp=timestamp[:20]), self.assertRaises(InvalidSignature):
				self.verify(timestamp=timestamp)

	def test_missing_or_short_shared_secret_fails_closed(self):
		for secret in (b"", b"short"):
			with self.subTest(length=len(secret)), self.assertRaises(ValueError):
				sign_event(self.body, secret, self.timestamp, event_id="event-1")
			with self.subTest(length=len(secret)), self.assertRaises(InvalidSignature):
				self.verify(secret=secret)

	def test_body_size_is_bounded_before_signing_or_verification(self):
		body = b"x" * 16_385
		with self.assertRaises(ValueError):
			sign_event(body, self.secret, self.timestamp, event_id="event-1")
		with self.assertRaises(InvalidSignature):
			self.verify(body=body)

	def test_signature_from_another_protocol_is_rejected(self):
		signature = (
			"sha256="
			+ hmac.new(
				self.secret, b"customer.webhook.v1\n1800000000\n" + self.body, hashlib.sha256
			).hexdigest()
		)
		with self.assertRaises(InvalidSignature):
			self.verify(signature=signature)

	def test_event_id_is_bound_to_the_signature(self):
		with self.assertRaises(InvalidSignature):
			verify_event(
				self.body,
				self.secret,
				str(self.timestamp),
				self.signature,
				now=self.timestamp,
				event_id="another-event",
			)

	def test_invalid_event_ids_are_rejected(self):
		for event_id in ("", "id.with.dots", "a" * 129, "olay-\u0131"):
			with self.subTest(event_id=event_id), self.assertRaises(ValueError):
				sign_event(self.body, self.secret, self.timestamp, event_id=event_id)
