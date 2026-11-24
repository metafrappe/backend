"""Organisation membership and the enterprise sign-in role (G-160, AJA-363, design AJA-361).

Expected rules, from the G-160 design:
- `PLT Organization Membership` holds a user's membership of an organisation. Its status is
  `active` or `ended`. A user has at most one active membership in one organisation.
- The system writes `added_by`. The user cannot pick it.
- `PLT Organization Sign-in Policy` holds one record per organisation. It may require corporate sign-in.
- `required_realm_roles(user)` returns `enterprise-sso-required` when an active membership belongs
  to an organisation that requires corporate sign-in. Otherwise it returns no role.
- Frappe never writes Keycloak. The sync step writes a file for `atonota-login apply`. The file
  names the Keycloak user by the identity link subject, never by the e-mail.
"""

import json
import os
import tempfile

import frappe
from frappe.tests import IntegrationTestCase

from platform_core.identity import enterprise_membership, enterprise_sync
from platform_core.identity.tests import helpers as h

MEMBERSHIP = "PLT Organization Membership"
POLICY = "PLT Organization Sign-in Policy"
ROLE = "enterprise-sso-required"
MEMBER = "uyelik.uye@example.test"
OTHER = "uyelik.diger@example.test"
ADMIN = "uyelik.yonetici@example.test"
REQUIRED_ORG = "test-org-required"
FREE_ORG = "test-org-free"


class TestOrganizationMembership(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		h.ensure_user(MEMBER)
		h.ensure_user(OTHER)
		h.ensure_user(ADMIN, "System User", ["System Manager"])

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.clear()
		self.addCleanup(self.clear)
		self.policy(REQUIRED_ORG, True)
		self.policy(FREE_ORG, False)

	def clear(self):
		frappe.set_user("Administrator")
		frappe.db.delete(MEMBERSHIP, {"organization": ("like", "test-org-%")})
		frappe.db.delete(POLICY, {"organization": ("like", "test-org-%")})
		frappe.db.delete("PLT Identity Link", {"user": ("in", [MEMBER, OTHER])})

	def policy(self, organization, required):
		return frappe.get_doc(
			{"doctype": POLICY, "organization": organization, "enterprise_sso_required": int(required)}
		).insert()

	def member(self, organization, user=MEMBER, status="active", **changes):
		frappe.set_user(ADMIN)
		try:
			return frappe.get_doc(
				{"doctype": MEMBERSHIP, "organization": organization, "user": user, "status": status, **changes}
			).insert()
		finally:
			frappe.set_user("Administrator")

	def test_member_of_required_organisation_gets_the_enterprise_role(self):
		self.member(REQUIRED_ORG)
		self.assertEqual(enterprise_membership.required_realm_roles(MEMBER), [ROLE])

	def test_role_name_is_the_one_the_sign_in_flow_refuses(self):
		self.assertEqual(enterprise_membership.ENTERPRISE_SSO_ROLE, ROLE)

	def test_member_of_free_organisation_gets_no_role(self):
		self.member(FREE_ORG)
		self.assertEqual(enterprise_membership.required_realm_roles(MEMBER), [])

	def test_organisation_without_policy_gives_no_role(self):
		self.member("test-org-no-policy")
		self.assertEqual(enterprise_membership.required_realm_roles(MEMBER), [])

	def test_ended_membership_gives_no_role(self):
		self.member(REQUIRED_ORG, status="ended")
		self.assertEqual(enterprise_membership.required_realm_roles(MEMBER), [])

	def test_ending_the_membership_takes_the_role_back(self):
		doc = self.member(REQUIRED_ORG)
		frappe.set_user(ADMIN)
		doc.status = "ended"
		doc.save()
		frappe.set_user("Administrator")
		self.assertEqual(enterprise_membership.required_realm_roles(MEMBER), [])

	def test_one_member_of_two_organisations_needs_the_role_once(self):
		self.member(REQUIRED_ORG)
		self.member(FREE_ORG)
		self.assertEqual(enterprise_membership.required_realm_roles(MEMBER), [ROLE])

	def test_desk_role_alone_gives_no_enterprise_role(self):
		self.assertEqual(enterprise_membership.required_realm_roles(ADMIN), [])

	def test_one_active_membership_per_user_and_organisation(self):
		self.member(REQUIRED_ORG)
		with self.assertRaises(frappe.ValidationError):
			self.member(REQUIRED_ORG)
		# An ended membership and a new active one may stand side by side.
		self.member(FREE_ORG, status="ended")
		self.member(FREE_ORG)

	def test_added_by_is_the_session_user(self):
		doc = self.member(REQUIRED_ORG, added_by=OTHER)
		self.assertEqual(doc.added_by, ADMIN)
		frappe.set_user(ADMIN)
		doc.added_by = OTHER
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		frappe.set_user("Administrator")

	def test_member_and_organisation_never_change(self):
		doc = self.member(REQUIRED_ORG)
		frappe.set_user(ADMIN)
		try:
			for field, value in (("user", OTHER), ("organization", FREE_ORG)):
				with self.subTest(field=field):
					fresh = frappe.get_doc(MEMBERSHIP, doc.name)
					fresh.set(field, value)
					with self.assertRaises(frappe.ValidationError):
						fresh.save()
		finally:
			frappe.set_user("Administrator")

	def test_one_policy_per_organisation(self):
		with self.assertRaises(frappe.DuplicateEntryError):
			self.policy(REQUIRED_ORG, False)

	def test_sync_exports_roles_by_link_subject(self):
		self.member(REQUIRED_ORG)
		self.member(REQUIRED_ORG, user=OTHER)
		self.member(FREE_ORG, user=ADMIN)
		with h.SiteSettings():
			h.make_link("sub-uyelik-uye", MEMBER)
			# A link of another issuer is not a user of the platform realm.
			h.make_link("sub-uyelik-diger", OTHER, issuer="https://other.example/realms/platform")
			folder = tempfile.TemporaryDirectory()
			self.addCleanup(folder.cleanup)
			path = os.path.join(folder.name, "roles.json")
			frappe.set_user(ADMIN)
			try:
				enterprise_sync.export_realm_roles(path)
			finally:
				frappe.set_user("Administrator")
		with open(path, encoding="utf-8") as handle:
			entries = json.load(handle)
		self.assertEqual(entries, [{"subject": "sub-uyelik-uye", "realm_roles": [ROLE]}])
		self.assertNotIn(MEMBER, json.dumps(entries))
		self.assertEqual(os.stat(path).st_mode & 0o077, 0)

	def test_sync_export_needs_the_approver_role(self):
		frappe.set_user(MEMBER)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			enterprise_sync.export_realm_roles(os.devnull)
