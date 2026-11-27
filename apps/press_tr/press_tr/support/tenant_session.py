"""Bind a tenant support session to one approved consent, one site and one requester (O-65).

Secrets leave Press only in the response to their owner. Press stores their SHA-256 digests.
"""

import hashlib
import secrets
from typing import Any

from press_tr.support.policy import ConsentDenied

TICKET_SECONDS = 60
TICKET_PREFIX = "ptr_support_ticket:"
SESSION_PREFIX = "ptr_support_session:"
# token_urlsafe(32) yields 43 characters. Anything far outside that range is not ours.
SECRET_BYTES = 32
MIN_SECRET_LENGTH = 40
MAX_SECRET_LENGTH = 128
BINDING_FIELDS = ("consent", "site", "actor", "team")


def new_secret() -> str:
	return secrets.token_urlsafe(SECRET_BYTES)


def storage_key(prefix: str, secret: Any) -> str:
	if not isinstance(secret, str) or not MIN_SECRET_LENGTH <= len(secret) <= MAX_SECRET_LENGTH:
		raise ConsentDenied("Valid customer consent is required for support access.")
	return prefix + hashlib.sha256(secret.encode()).hexdigest()


def binding(*, consent: str, site: str, actor: str, team: str) -> dict[str, str]:
	return {"consent": consent, "site": site, "actor": actor, "team": team}


def match(record: Any, *, site: str) -> dict[str, str]:
	"""Return a stored binding only for the site that presents it."""
	if not isinstance(record, dict) or set(record) != set(BINDING_FIELDS):
		raise ConsentDenied("Valid customer consent is required for support access.")
	if any(not isinstance(record[field], str) or not record[field] for field in BINDING_FIELDS):
		raise ConsentDenied("Valid customer consent is required for support access.")
	if record["site"] != site:
		raise ConsentDenied("Valid customer consent is required for support access.")
	return record
