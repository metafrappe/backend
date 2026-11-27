"""Authenticate a status event without granting any Press API permission."""

import hashlib
import hmac
import re

MAX_BODY_BYTES = 16_384
MAX_CLOCK_SKEW_SECONDS = 300


class InvalidSignature(ValueError):
	"""The event cannot be authenticated."""


def sign_event(body: bytes, secret: bytes, timestamp: int, *, event_id: str) -> str:
	"""Sign the original bytes with a dedicated, operator-managed shared key."""
	if not isinstance(body, bytes) or not 0 < len(body) <= MAX_BODY_BYTES:
		raise ValueError("Invalid event size")
	if not isinstance(secret, bytes) or len(secret) < 32:
		raise ValueError("The event signing key must contain at least 32 bytes")
	if type(timestamp) is not int or not 0 <= timestamp <= 9_999_999_999:
		raise ValueError("Invalid event timestamp")
	if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event_id):
		raise ValueError("Invalid event identifier")
	message = str(timestamp).encode("ascii") + b"." + event_id.encode("ascii") + b"." + body
	return "v1=" + hmac.new(secret, message, hashlib.sha256).hexdigest()


def verify_event(
	body: bytes, secret: bytes, timestamp: str, signature: str, *, now: int, event_id: str
) -> None:
	"""Reject unauthenticated or stale bytes before parsing or processing them.

	The receiver must additionally deduplicate authenticated event IDs in its
	transaction. This function provides neither replay storage nor API access.
	"""
	if not isinstance(timestamp, str) or not re.fullmatch(r"0|[1-9][0-9]{0,9}", timestamp):
		raise InvalidSignature("Invalid event signature")
	if not isinstance(signature, str) or not re.fullmatch(r"v1=[0-9a-f]{64}", signature):
		raise InvalidSignature("Invalid event signature")
	if type(now) is not int or abs(now - int(timestamp)) > MAX_CLOCK_SKEW_SECONDS:
		raise InvalidSignature("Invalid event signature")
	try:
		expected = sign_event(body, secret, int(timestamp), event_id=event_id)
	except ValueError as error:
		raise InvalidSignature("Invalid event signature") from error
	if not hmac.compare_digest(expected, signature):
		raise InvalidSignature("Invalid event signature")
