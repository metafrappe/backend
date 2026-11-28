"""Customer consent is bound to a requester, site, purpose and expiry."""

import copy
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from press_tr.support.policy import ConsentDenied, authorize, validate_change

NOW = datetime(2026, 11, 23, 12)


def request(**changes):
	value = {
		"name": "consent-1",
		"status": "Pending",
		"requested_by": "support@example.test",
		"requested_team": "support-team",
		"target_team": "customer-team",
		"reason": "Investigate failed backup",
		"resources": [{"document_type": "Site", "document_name": "tenant.example.test"}],
		"login_as_administrator": 0,
		"site_domains": 0,
		"site_release_group": 0,
		"bench_ssh": 0,
		"allowed_for": "3",
		"access_allowed_till": None,
	}
	value.update(changes)
	return value


def accepted(**changes):
	return request(status="Accepted", access_allowed_till=NOW + timedelta(hours=3), **changes)


class SupportConsentTest(unittest.TestCase):
	def validate(self, current, previous=None, actor="support@example.test"):
		return validate_change(current, previous, actor=actor, customer_owner="owner@example.test", now=NOW)

	def access(self, grant, **changes):
		args = dict(
			actor="support@example.test",
			team="support-team",
			site="tenant.example.test",
			administrator=False,
			now=NOW,
		)
		args.update(changes)
		return authorize(grant, **args)

	def test_new_request_must_wait_for_customer(self):
		self.validate(request())
		for status in ["Accepted", "Revoked", "Rejected", "Expired"]:
			with self.subTest(status=status), self.assertRaises(ConsentDenied):
				self.validate(request(status=status))

	def test_requester_cannot_forge_another_identity(self):
		with self.assertRaises(ConsentDenied):
			self.validate(request(requested_by="other@example.test"))

	def test_only_customer_owner_can_approve_even_for_system_user(self):
		self.validate(accepted(), request(), actor="owner@example.test")
		for actor in ["support@example.test", "Administrator", "stranger@example.test", "Guest"]:
			with self.subTest(actor=actor), self.assertRaises(ConsentDenied):
				self.validate(accepted(), request(), actor=actor)

	def test_reason_and_scope_are_required(self):
		for change in [
			{"reason": "  "},
			{"resources": []},
			{"target_team": ""},
			{"bench_ssh": 1},
			{"site_release_group": 1},
		]:
			with self.subTest(change=change), self.assertRaises(ConsentDenied):
				self.validate(request(**change))

	def test_scope_reason_identity_and_admin_mode_are_immutable(self):
		for field, value in [
			("reason", "Different purpose"),
			("requested_by", "other@example.test"),
			("requested_team", "other-team"),
			("target_team", "other-team"),
			("login_as_administrator", 1),
			("resources", [{"document_type": "Site", "document_name": "other.example.test"}]),
		]:
			with self.subTest(field=field), self.assertRaises(ConsentDenied):
				self.validate(accepted(**{field: value}), request(), actor="owner@example.test")

	def test_customer_chooses_bounded_duration_at_approval(self):
		self.validate(accepted(allowed_for="6"), request(), actor="owner@example.test")
		for duration in ["0", "-1", "invalid", "168"]:
			with self.subTest(duration=duration), self.assertRaises(ConsentDenied):
				self.validate(accepted(allowed_for=duration), request(), actor="owner@example.test")

	def test_missing_or_extended_expiry_is_rejected(self):
		for expiry in [None, NOW, NOW + timedelta(hours=25)]:
			current = accepted()
			current["access_allowed_till"] = expiry
			with self.subTest(expiry=expiry), self.assertRaises(ConsentDenied):
				self.validate(current, request(), actor="owner@example.test")

	def test_approved_duration_cannot_be_extended(self):
		old = accepted()
		new = copy.deepcopy(old)
		new["access_allowed_till"] += timedelta(seconds=1)
		with self.assertRaises(ConsentDenied):
			self.validate(new, old, actor="owner@example.test")

	def test_revocation_is_customer_only_and_cannot_be_reopened(self):
		old = accepted()
		closed = dict(old, status="Revoked")
		self.validate(closed, old, actor="owner@example.test")
		with self.assertRaises(ConsentDenied):
			self.validate(closed, old)
		with self.assertRaises(ConsentDenied):
			self.validate(old, closed, actor="owner@example.test")

	def test_every_access_checks_consent_and_expiry_without_scheduler(self):
		self.assertEqual(self.access(accepted()), "consent-1")
		for grant in [request(), dict(accepted(), status="Revoked")]:
			with self.assertRaises(ConsentDenied):
				self.access(grant)
		for when in [NOW + timedelta(hours=3), NOW + timedelta(hours=4)]:
			with self.subTest(when=when), self.assertRaises(ConsentDenied):
				self.access(accepted(), now=when)

	def test_access_is_bound_to_named_requester_team_and_site(self):
		for change in [
			{"actor": "other@example.test"},
			{"team": "other-team"},
			{"site": "other.example.test"},
		]:
			with self.subTest(change=change), self.assertRaises(ConsentDenied):
				self.access(accepted(), **change)

	def test_admin_login_requires_separate_customer_approved_request(self):
		with self.assertRaises(ConsentDenied):
			self.access(accepted(), administrator=True)
		admin = accepted(login_as_administrator=1)
		self.validate(admin, request(login_as_administrator=1), actor="owner@example.test")
		self.assertEqual(self.access(admin, administrator=True), "consent-1")
		with self.assertRaises(ConsentDenied):
			self.access(request(login_as_administrator=1), administrator=True)
		with self.assertRaises(ConsentDenied):
			self.validate(
				accepted(login_as_administrator=1, allowed_for="6"),
				request(login_as_administrator=1),
				actor="owner@example.test",
			)

	def test_admin_request_cannot_combine_sites_or_other_permissions(self):
		for change in [
			{
				"resources": [
					*request()["resources"],
					{"document_type": "Site", "document_name": "second.example.test"},
				]
			},
			{"site_domains": 1},
		]:
			with self.subTest(change=change), self.assertRaises(ConsentDenied):
				self.validate(request(login_as_administrator=1, **change))


if __name__ == "__main__":
	unittest.main()
