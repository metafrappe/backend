"""Support access rule on a tenant site (G-59, G-82, SA-40).

An `ops-bff` token opens tenant data only inside an active Support Session with valid customer
consent. The token's `(iss, sub)` pair must equal the operator recorded on that session, so the
operator's identity is kept for the whole call. The caller passes claims that oidc_verify has
already verified (signature, `exp`, `iss`, single `aud`, `azp` allowlist).

This module has no Frappe dependency. The Support Session record and the `auth_hooks` wiring
come in a later step; until then nothing calls `authorize` on a request.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

OPS_BFF = "ops-bff"
ACTIVE = "Active"


class SupportAccessDeniedError(Exception):
	"""Refusal with a fixed reason code. Frappe maps `http_status_code` to the response status."""

	http_status_code = 403

	def __init__(self, reason: str) -> None:
		super().__init__(reason)
		self.reason = reason


@dataclass(frozen=True)
class SupportSession:
	name: str
	status: str | None
	operator_issuer: str
	operator_subject: str
	consent_given_at: float | None
	consent_expires_at: float | None
	consent_revoked_at: float | None = None


def _time(value: object) -> float | None:
	if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
		return None
	return float(value)


def authorize(claims: dict, session: SupportSession | None, *, now: float) -> dict:
	"""Return the read-only support grant, or raise `SupportAccessDeniedError`."""
	if claims.get("azp") != OPS_BFF:
		raise SupportAccessDeniedError("not_support_service")
	if session is None:
		raise SupportAccessDeniedError("no_support_session")
	if session.status != ACTIVE:
		raise SupportAccessDeniedError("session_not_active")

	given = _time(session.consent_given_at)
	if given is None or given > now:
		raise SupportAccessDeniedError("no_consent")
	if _time(session.consent_revoked_at) is not None:
		raise SupportAccessDeniedError("consent_revoked")
	expires = _time(session.consent_expires_at)
	if expires is None or now >= expires:
		raise SupportAccessDeniedError("consent_expired")

	issuer, subject = claims.get("iss"), claims.get("sub")
	if (
		not isinstance(issuer, str)
		or not isinstance(subject, str)
		or not subject
		or (issuer, subject) != (session.operator_issuer, session.operator_subject)
	):
		raise SupportAccessDeniedError("operator_mismatch")

	return {
		"support_session": session.name,
		"operator": {"issuer": issuer, "subject": subject},
		"read_only": True,
	}
