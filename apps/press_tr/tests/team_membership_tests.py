"""G-16: team roles, resource limits, invitations, child teams and organization mapping.

`IdentityHttpTest` mixes these tests in. They need its local issuer, service token and sign-in.
"""

import json
from uuid import uuid4

import frappe

SITE_LIST_ROUTE = "/api/method/press.api.client.get_list"
SITE_GET_ROUTE = "/api/method/press.api.client.get"


class TeamMembershipTests:
	def ensure_member(self, subject, organization_id, **options):
		return self.call(
			"ensure_team",
			{
				"issuer": self.token_issuer,
				"subject": subject,
				"email": f"{subject}@example.test",
				"email_verified": True,
				"organization_id": organization_id,
				**options,
			},
			self.token(),
		)

	def organization_team(self, organization_id):
		owner = uuid4().hex
		status, result = self.ensure_member(owner, organization_id)
		self.assertEqual(status, 200)
		return owner, result["message"]["team"]

	def change_site(self, change):
		frappe.init("press.localhost")
		frappe.connect()
		try:
			result = change()
			frappe.db.commit()
			return result
		finally:
			frappe.destroy()

	def add_sites(self, team, count):
		def insert():
			names = []
			for _index in range(count):
				name = f"g16-{uuid4().hex[:12]}.example.test"
				# A list row is enough here. The Site controller would provision a real site.
				frappe.get_doc({"doctype": "Site", "name": name, "team": team, "status": "Active"}).db_insert()
				names.append(name)
			return names

		return self.change_site(insert)

	def add_role(self, team, title, *, users=(), sites=(), **flags):
		def insert():
			doc = frappe.get_doc(
				{
					"doctype": "Press Role",
					"title": title,
					"team": team,
					"users": [{"user": user} for user in users],
					"resources": [{"document_type": "Site", "document_name": site} for site in sites],
					**flags,
				}
			)
			doc.insert(ignore_permissions=True)
			return doc.name

		return self.change_site(insert)

	def role_titles(self, team, user):
		def read():
			roles = frappe.get_all("Press Role", {"team": team}, ["name", "title"])
			return {
				role.title
				for role in roles
				if frappe.db.exists("Press Role User", {"parent": role.name, "user": user})
			}

		return self.change_site(read)

	def member_teams(self, user):
		return set(
			self.change_site(
				lambda: frappe.get_all("Team Member", {"user": user, "parenttype": "Team"}, pluck="parent")
			)
		)

	def member_session(self, subject):
		return self.sign_in(subject, f"{subject}@example.test", uuid4().hex)

	def visible_sites(self, session, team=None):
		headers = {**session, "Content-Type": "application/json"}
		if team:
			headers["X-Press-Team"] = team
		body = json.dumps({"doctype": "Site", "fields": ["name"], "limit": 100})
		status, _headers, payload = self.exchange("POST", SITE_LIST_ROUTE, headers, body)
		self.assertEqual(status, 200, payload)
		return {row["name"] for row in json.loads(payload)["message"]}

	def open_site(self, session, name):
		headers = {**session, "Content-Type": "application/json"}
		body = json.dumps({"doctype": "Site", "name": name})
		return self.exchange("POST", SITE_GET_ROUTE, headers, body)[0]

	def test_team_role_limits_member_to_its_resources(self):
		organization_id = uuid4().hex
		owner, team = self.organization_team(organization_id)
		member = uuid4().hex
		self.assertEqual(self.ensure_member(member, organization_id)[0], 200)
		permitted, other = self.add_sites(team, 2)
		self.add_role(team, "Site operator", users=[f"{member}@example.test"], sites=[permitted])

		member_session = self.member_session(member)
		self.assertEqual(self.visible_sites(member_session), {permitted})
		self.assertEqual(self.open_site(member_session, other), 403)
		self.assertEqual(self.visible_sites(self.member_session(owner)), {permitted, other})

	def test_invited_member_receives_the_requested_role(self):
		organization_id = uuid4().hex
		_owner, team = self.organization_team(organization_id)
		permitted, other = self.add_sites(team, 2)
		self.add_role(team, "Site operator", sites=[permitted])
		self.add_role(team, "Finance", allow_billing=1)
		invited, plain = uuid4().hex, uuid4().hex

		status, result = self.ensure_member(invited, organization_id, press_role="Site operator")
		self.assertEqual(status, 200, result)
		self.assertEqual(self.role_titles(team, f"{invited}@example.test"), {"Site operator"})
		self.assertEqual(self.visible_sites(self.member_session(invited)), {permitted})

		# A repeated request keeps the membership and the role unchanged.
		self.assertEqual(self.ensure_member(invited, organization_id, press_role="Site operator")[0], 200)
		self.assertEqual(self.role_titles(team, f"{invited}@example.test"), {"Site operator"})

		# Without a role the member gets no role and no site of the team.
		self.assertEqual(self.ensure_member(plain, organization_id)[0], 200)
		self.assertEqual(self.role_titles(team, f"{plain}@example.test"), set())
		self.assertEqual(self.visible_sites(self.member_session(plain)), set())
		self.assertNotIn(other, self.visible_sites(self.member_session(invited)))

	def test_invitation_with_a_role_of_another_team_adds_no_member(self):
		organization_id, other_organization = uuid4().hex, uuid4().hex
		_owner, team = self.organization_team(organization_id)
		_other_owner, other_team = self.organization_team(other_organization)
		self.add_role(other_team, "Foreign role", all_sites=1)
		invited = uuid4().hex

		for role in ("Foreign role", "", ["Foreign role"], "x" * 141):
			with self.subTest(role=role):
				status, _result = self.ensure_member(invited, organization_id, press_role=role)
				self.assertEqual(status, 400)
		self.assertEqual(self.member_teams(f"{invited}@example.test"), set())

	def test_child_team_member_sees_only_its_own_resources(self):
		organization_id = uuid4().hex
		owner, parent = self.organization_team(organization_id)
		member = uuid4().hex
		member_user = f"{member}@example.test"

		def create_child():
			from press.press.doctype.team.team import Team

			Team.create_user(first_name=member, email=member_user)
			child = frappe.get_doc(
				{
					"doctype": "Team",
					"team_title": "Branch office",
					"user": f"{owner}@example.test",
					"parent_team": parent,
					"enabled": 1,
					"team_members": [{"user": f"{owner}@example.test"}, {"user": member_user}],
				}
			)
			# The same insert as Press `create_child_team`, with the member in the child team only.
			child.insert(ignore_permissions=True, ignore_links=True)
			return child.name

		child = self.change_site(create_child)
		(parent_site,) = self.add_sites(parent, 1)
		(child_site,) = self.add_sites(child, 1)

		member_session = self.member_session(member)
		self.assertEqual(self.member_teams(member_user), {child})
		self.assertEqual(self.visible_sites(member_session), {child_site})
		self.assertEqual(self.visible_sites(member_session, team=parent), {child_site})
		self.assertEqual(self.open_site(member_session, parent_site), 403)
		self.assertIn(parent_site, self.visible_sites(self.member_session(owner), team=parent))

	def test_identity_mapping_adds_member_only_to_its_organization_team(self):
		first_organization, second_organization = uuid4().hex, uuid4().hex
		_first_owner, first_team = self.organization_team(first_organization)
		_second_owner, second_team = self.organization_team(second_organization)
		member = uuid4().hex
		member_user = f"{member}@example.test"

		status, result = self.ensure_member(member, first_organization)
		self.assertEqual(status, 200)
		self.assertEqual(result["message"], {"team": first_team, "created": False})
		self.assertEqual(self.member_teams(member_user), {first_team})

		# MariaDB compares the organization id without case. Press must not treat it as the same team.
		status, _result = self.ensure_member(member, second_organization.upper())
		self.assertEqual(status, 403)
		self.assertEqual(self.member_teams(member_user), {first_team})
		self.assertNotIn(second_team, self.member_teams(member_user))
