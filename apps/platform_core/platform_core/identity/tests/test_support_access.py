"""G-59 and G-82: support access needs valid customer consent and keeps the operator's identity.

The rule is checked on verified `ops-bff` token claims (oidc_verify has already checked the
signature, `exp`, `iss`, the single `aud` and `azp`). The Support Session record and the
`auth_hooks` wiring are not in this repository yet; the PR description lists that part.
These tests need no Frappe site.
"""

import unittest

from platform_core.identity.support_access import (
	OPS_BFF,
	SupportAccessDeniedError,
	SupportSession,
	authorize,
)

ISSUER = "https://id.example.test/realms/platform"
NOW = 1_800_000_000.0


def _claims(**changes):
	claims = {"iss": ISSUER, "sub": "operator-1", "azp": OPS_BFF, "aud": "site-tenant1", "exp": NOW + 60}
	claims.update(changes)
	return {key: value for key, value in claims.items() if value is not None}


def _session(**changes):
	values = {
		"name": "SUP-0001",
		"status": "Active",
		"operator_issuer": ISSUER,
		"operator_subject": "operator-1",
		"consent_given_at": NOW - 600,
		"consent_expires_at": NOW + 600,
		"consent_revoked_at": None,
	}
	values.update(changes)
	return SupportSession(**values)


class SupportConsentTest(unittest.TestCase):
	def assert_denied(self, reason, claims=None, session="default"):
		session = _session() if session == "default" else session
		with self.assertRaises(SupportAccessDeniedError) as caught:
			authorize(claims or _claims(), session, now=NOW)
		self.assertEqual(caught.exception.reason, reason)
		self.assertEqual(caught.exception.http_status_code, 403)

	def test_active_consented_session_is_allowed(self):
		grant = authorize(_claims(), _session(), now=NOW)
		self.assertEqual(grant["support_session"], "SUP-0001")
		self.assertTrue(grant["read_only"])

	def test_no_session_is_denied(self):
		self.assert_denied("no_support_session", session=None)

	def test_session_without_consent_is_denied(self):
		self.assert_denied("no_consent", session=_session(consent_given_at=None))

	def test_expired_consent_is_denied(self):
		self.assert_denied("consent_expired", session=_session(consent_expires_at=NOW))
		self.assert_denied("consent_expired", session=_session(consent_expires_at=None))

	def test_revoked_consent_is_denied(self):
		self.assert_denied("consent_revoked", session=_session(consent_revoked_at=NOW - 1))

	def test_consent_given_in_the_future_is_denied(self):
		self.assert_denied("no_consent", session=_session(consent_given_at=NOW + 5))

	def test_closed_session_is_denied(self):
		for status in ("Closed", "Requested", "Expired", "", None):
			with self.subTest(status=status):
				self.assert_denied("session_not_active", session=_session(status=status))

	def test_other_service_token_is_denied(self):
		for azp in ("identity-sync", "press-service", "agent-service", None):
			with self.subTest(azp=azp):
				self.assert_denied("not_support_service", claims=_claims(azp=azp))


class OperatorIdentityTest(unittest.TestCase):
	def test_the_operator_identity_is_carried_into_the_grant(self):
		grant = authorize(_claims(), _session(), now=NOW)
		self.assertEqual(grant["operator"], {"issuer": ISSUER, "subject": "operator-1"})

	def test_another_operator_cannot_use_the_session(self):
		with self.assertRaises(SupportAccessDeniedError) as caught:
			authorize(_claims(sub="operator-2"), _session(), now=NOW)
		self.assertEqual(caught.exception.reason, "operator_mismatch")

	def test_the_same_subject_from_another_issuer_is_another_operator(self):
		with self.assertRaises(SupportAccessDeniedError) as caught:
			authorize(_claims(iss="https://other.example.test/realms/platform"), _session(), now=NOW)
		self.assertEqual(caught.exception.reason, "operator_mismatch")

	def test_a_token_without_subject_is_denied(self):
		for sub in (None, "", 7):
			with self.subTest(sub=sub), self.assertRaises(SupportAccessDeniedError) as caught:
				authorize(_claims(sub=sub), _session(), now=NOW)
			self.assertEqual(caught.exception.reason, "operator_mismatch")

	def test_the_grant_cannot_change_the_session(self):
		session = _session()
		grant = authorize(_claims(), session, now=NOW)
		grant["operator"]["subject"] = "operator-2"
		self.assertEqual(authorize(_claims(), session, now=NOW)["operator"]["subject"], "operator-1")


if __name__ == "__main__":
	unittest.main()
