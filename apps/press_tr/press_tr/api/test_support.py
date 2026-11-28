"""HTTP regressions mixed into the isolated Press identity test harness."""

import json
import re
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import frappe

PREFIX = "/api/method/press_tr.api.support."


class SupportAccessTests:
	@contextmanager
	def _support_database(self):
		frappe.init("press.localhost")
		frappe.connect()
		try:
			yield
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			raise
		finally:
			frappe.destroy()

	def _support_identity(self, *, support=False):
		subject = uuid4().hex
		email = f"{subject}@example.test"
		session = self.sign_in(subject, email, uuid4().hex)
		with self._support_database():
			if support:
				frappe.get_doc("User", email).add_roles("Press Support Agent")
			self.assertEqual("Press Support Agent" in frappe.get_roles(email), support)
			self.assertEqual(frappe.db.get_value("User", email, "user_type"), "Website User")
			team = frappe.db.get_value("Team", {"user": email}, "name")
		# Sign in again with the actual support role, through the same browser callback.
		if support:
			session = self.sign_in(subject, email, uuid4().hex)
		status, _headers, page = self.exchange("GET", "/account-deletion", session)
		self.assertEqual(status, 200)
		csrf = re.search(rb'name="csrf_token" value="([^"]+)"', page).group(1).decode()
		return {
			"email": email,
			"team": team,
			"headers": {
				**session,
				"Content-Type": "application/json",
				"X-Frappe-CSRF-Token": csrf,
				"X-Press-Team": team,
			},
		}

	def _customer_headers(self):
		return self._support_identity()["headers"]

	def _support_fixture(self):
		customer = self._support_identity()
		support = self._support_identity(support=True)
		site = "support-" + uuid4().hex + ".example.test"
		with self._support_database():
			# Only synthetic infrastructure is inserted directly. Consent uses real HTTP below.
			frappe.get_doc(
				{"doctype": "Site", "name": site, "team": customer["team"], "status": "Active"}
			).db_insert()

		def cleanup():
			with self._support_database():
				for name in frappe.get_all(
					"Support Access", filters={"target_team": customer["team"]}, pluck="name"
				):
					frappe.db.delete(
						"Comment", {"reference_doctype": "Support Access", "reference_name": name}
					)
					frappe.db.delete("Support Access Resource", {"parent": name})
					frappe.db.delete("Support Access", {"name": name})
				frappe.db.delete("Site", {"name": site})

		self.addCleanup(cleanup)
		status, _headers, payload = self.exchange(
			"POST",
			PREFIX + "request_access",
			support["headers"],
			json.dumps({"site": site, "reason": "Investigate failed backup"}),
		)
		self.assertEqual(status, 200)
		return customer, support, site, json.loads(payload)["message"]["name"]

	def _approve_support_fixture(self):
		customer, support, site, name = self._support_fixture()
		self.assertEqual(self._support_post("approve_access", customer["headers"], name=name), 200)
		return customer, support, site, name

	def _foreign_support_record(self):
		# This helper is only used by the isolated site's HTTP tests. It never runs in a request.
		subject = uuid4().hex
		email = f"{subject}@example.test"
		self.sign_in(subject, email, uuid4().hex)
		name = "support-test-" + uuid4().hex
		frappe.init("press.localhost")
		frappe.connect()
		try:
			team = frappe.db.get_value("Team", {"user": email}, "name")
			self.assertTrue(team)
			frappe.get_doc(
				{
					"doctype": "Support Access",
					"name": name,
					"status": "Pending",
					"target_team": team,
					"requested_team": team,
					"requested_by": email,
					"reason": "Foreign customer fixture",
					"allowed_for": "3",
				}
			).db_insert()
			frappe.db.commit()
		finally:
			frappe.destroy()

		def cleanup():
			frappe.init("press.localhost")
			frappe.connect()
			try:
				frappe.db.delete("Support Access", {"name": name})
				frappe.db.commit()
			finally:
				frappe.destroy()

		self.addCleanup(cleanup)
		return name

	def _support_post(self, method, headers=None, **payload):
		return self.exchange("POST", PREFIX + method, headers, json.dumps(payload))[0]

	def test_request_access_guest_denied(self):
		self.assertEqual(
			self._support_post("request_access", site="foreign.example.test", reason="Investigate"), 403
		)

	def test_request_access_foreign_data_denied(self):
		self.assertEqual(
			self._support_post(
				"request_access", self._customer_headers(), site="foreign.example.test", reason="Investigate"
			),
			403,
		)

	def test_approve_access_guest_denied(self):
		self.assertEqual(self._support_post("approve_access", name="foreign-consent"), 403)

	def test_approve_access_foreign_data_denied(self):
		name = self._foreign_support_record()
		self.assertEqual(self._support_post("approve_access", self._customer_headers(), name=name), 403)

	def test_revoke_access_guest_denied(self):
		self.assertEqual(self._support_post("revoke_access", name="foreign-consent"), 403)

	def test_revoke_access_foreign_data_denied(self):
		name = self._foreign_support_record()
		self.assertEqual(self._support_post("revoke_access", self._customer_headers(), name=name), 403)

	def test_site_status_guest_denied(self):
		self.assertEqual(self._support_post("site_status", name="foreign-consent"), 403)

	def test_site_status_foreign_data_denied(self):
		name = self._foreign_support_record()
		self.assertEqual(self._support_post("site_status", self._customer_headers(), name=name), 403)

	def _tenant_ticket(self):
		customer, support, site, name = self._approve_support_fixture()
		status, _headers, payload = self.exchange(
			"POST", PREFIX + "open_tenant_session", support["headers"], json.dumps({"name": name})
		)
		self.assertEqual(status, 200)
		return customer, site, name, json.loads(payload)["message"]

	def _tenant_exchange(self, method, **payload):
		status, _headers, body = self.exchange(
			"POST", PREFIX + method, {"Content-Type": "application/json"}, json.dumps(payload)
		)
		return status, json.loads(body).get("message") if status == 200 else None

	def test_open_tenant_session_guest_denied(self):
		self.assertEqual(self._support_post("open_tenant_session", name="foreign-consent"), 403)

	def test_open_tenant_session_foreign_data_denied(self):
		name = self._foreign_support_record()
		self.assertEqual(self._support_post("open_tenant_session", self._customer_headers(), name=name), 403)

	def test_redeem_tenant_session_guest_denied(self):
		status, _message = self._tenant_exchange(
			"redeem_tenant_session", ticket="t" * 43, site="tenant.example.test"
		)
		self.assertEqual(status, 403)

	def test_redeem_tenant_session_foreign_data_denied(self):
		_customer, site, _name, opened = self._tenant_ticket()
		self.assertEqual(opened["site"], site)
		status, _message = self._tenant_exchange(
			"redeem_tenant_session", ticket=opened["ticket"], site="other-" + site
		)
		self.assertEqual(status, 403)
		# The foreign attempt consumed the single-use ticket.
		status, _message = self._tenant_exchange("redeem_tenant_session", ticket=opened["ticket"], site=site)
		self.assertEqual(status, 403)

	def test_check_tenant_session_guest_denied(self):
		status, _message = self._tenant_exchange(
			"check_tenant_session", session_key="k" * 43, site="tenant.example.test"
		)
		self.assertEqual(status, 403)

	def test_check_tenant_session_foreign_data_denied(self):
		_customer, site, name, opened = self._tenant_ticket()
		status, session = self._tenant_exchange("redeem_tenant_session", ticket=opened["ticket"], site=site)
		self.assertEqual(status, 200)
		key = session["session_key"]
		self.assertEqual(self._tenant_exchange("check_tenant_session", session_key=key, site=site)[0], 200)
		self.assertEqual(
			self._tenant_exchange("check_tenant_session", session_key=key, site="other-" + site)[0], 403
		)
		with self._support_database():
			comments = frappe.get_all(
				"Comment",
				filters={"reference_doctype": "Support Access", "reference_name": name},
				pluck="content",
			)
		self.assertTrue(any("tenant_session_opened" in comment for comment in comments))

	def _assert_tenant_session_ends(self, end_consent):
		# Each test gets its own request IP in setUp, so sign-ins stay under the rate limit.
		customer, site, name, opened = self._tenant_ticket()
		status, session = self._tenant_exchange("redeem_tenant_session", ticket=opened["ticket"], site=site)
		self.assertEqual(status, 200)
		key = session["session_key"]
		self.assertEqual(self._tenant_exchange("check_tenant_session", session_key=key, site=site)[0], 200)
		end_consent(customer, name)
		self.assertEqual(self._tenant_exchange("check_tenant_session", session_key=key, site=site)[0], 403)

	def test_tenant_session_ends_when_consent_is_revoked(self):
		def revoke(customer, name):
			self.assertEqual(self._support_post("revoke_access", customer["headers"], name=name), 200)

		self._assert_tenant_session_ends(revoke)

	def test_tenant_session_ends_when_consent_expires(self):
		def expire(_customer, name):
			with self._support_database():
				frappe.db.set_value(
					"Support Access",
					name,
					"access_allowed_till",
					frappe.utils.now_datetime() - timedelta(seconds=1),
				)

		self._assert_tenant_session_ends(expire)

	def test_support_role_without_consent_is_denied(self):
		_customer, support, _site, name = self._support_fixture()
		self.assertEqual(self._support_post("site_status", support["headers"], name=name), 403)

	def test_support_browser_csrf_allows_approved_read_but_not_desk(self):
		_customer, support, site, name = self._approve_support_fixture()
		status, _headers, payload = self.exchange(
			"POST", PREFIX + "site_status", support["headers"], json.dumps({"name": name})
		)
		self.assertEqual(status, 200)
		self.assertEqual(json.loads(payload)["message"], {"site": site, "status": "Active"})
		for path in ("/app", "/dashboard", "/account-deletion/other"):
			with self.subTest(path=path):
				self.assertEqual(self.exchange("GET", path, support["headers"])[0], 403)

	def test_support_role_expired_consent_is_denied(self):
		_customer, support, _site, name = self._approve_support_fixture()
		with self._support_database():
			frappe.db.set_value(
				"Support Access",
				name,
				"access_allowed_till",
				frappe.utils.now_datetime() - timedelta(seconds=1),
			)
		self.assertEqual(self._support_post("site_status", support["headers"], name=name), 403)

	def test_support_role_revoked_consent_is_denied(self):
		customer, support, _site, name = self._approve_support_fixture()
		self.assertEqual(self._support_post("revoke_access", customer["headers"], name=name), 200)
		self.assertEqual(self._support_post("site_status", support["headers"], name=name), 403)

	def test_support_role_other_employee_or_team_is_denied(self):
		_customer, support, _site, name = self._approve_support_fixture()
		other = self._support_identity(support=True)
		with self._support_database():
			for team, user in ((support["team"], other["email"]), (other["team"], support["email"])):
				doc = frappe.get_doc("Team", team)
				doc.append("team_members", {"user": user})
				doc.save()
		for identity, team in ((other, support["team"]), (support, other["team"])):
			with self.subTest(actor=identity["email"], team=team):
				self.assertEqual(
					self._support_post(
						"site_status", {**identity["headers"], "X-Press-Team": team}, name=name
					),
					403,
				)

	def test_support_role_transferred_site_is_denied(self):
		_customer, support, site, name = self._approve_support_fixture()
		other = self._support_identity()
		with self._support_database():
			frappe.db.set_value("Site", site, "team", other["team"])
		self.assertEqual(self._support_post("site_status", support["headers"], name=name), 403)

	def test_support_role_each_successful_read_adds_one_comment(self):
		_customer, support, _site, name = self._approve_support_fixture()
		for expected in (1, 2):
			self.assertEqual(self._support_post("site_status", support["headers"], name=name), 200)
			with self._support_database():
				comments = frappe.get_all(
					"Comment",
					filters={
						"reference_doctype": "Support Access",
						"reference_name": name,
						"content": ("like", "%site_status_read%"),
					},
					fields=["comment_email", "content"],
				)
				self.assertEqual(len(comments), expected)
				self.assertTrue(all(row.comment_email == support["email"] for row in comments))
				self.assertTrue(all("Investigate failed backup" in row.content for row in comments))

	def test_customer_member_four_native_login_routes(self):
		from press.overrides import before_request
		from press.press.doctype.site.site import Site
		from werkzeug.wrappers import Request

		customer, _support, site_name, _name = self._support_fixture()
		member = self._support_identity()
		with self._support_database():
			team = frappe.get_doc("Team", customer["team"])
			team.append("team_members", {"user": member["email"]})
			team.save()
			site = frappe.get_doc("Site", site_name)
			site.additional_system_user_created = 1
			frappe.set_user(member["email"])
			frappe.local.request = Request.from_values(headers={"X-Press-Team": customer["team"]})
			before_request()
			with (
				patch.object(Site, "get_login_sid", return_value="fixture-sid"),
				patch("press.press.doctype.site.site.log_site_activity"),
			):
				self.assertIn("sid=fixture-sid", site.login_as_admin())
				self.assertIn("sid=fixture-sid", site.login_as_team())
				with patch.object(frappe, "get_doc", return_value=site):
					from press.press.doctype.site_user.site_user import SiteUser
					from press.saas.doctype.product_trial_request.product_trial_request import (
						ProductTrialRequest,
					)

					user = SiteUser(
						{"doctype": "Site User", "site": site_name, "user": member["email"], "enabled": 1}
					)
					self.assertIn("sid=fixture-sid", user.login_to_site())
					trial = ProductTrialRequest(
						{"doctype": "Product Trial Request", "site": site_name, "team": customer["team"]}
					)
					with patch.object(trial, "check_site_accessible"):
						self.assertIn("sid=fixture-sid", trial.get_login_sid())
				frappe.set_user("Administrator")
				frappe.get_doc("User", member["email"]).add_roles("Press Support Agent")
				frappe.set_user(member["email"])
				before_request()
				with self.assertRaises(frappe.PermissionError):
					site.login_as_admin()

	def test_administrator_setup_sync_uses_native_sid_only_in_worker_context(self):
		from press.press.doctype.site.site import Site
		from press.press.doctype.site.sync import sync_setup_wizard_status

		_customer, _support, site_name, _name = self._support_fixture()
		with self._support_database():
			frappe.set_user("Administrator")
			frappe.local.job = frappe._dict(method="press.press.doctype.site.sync.sync_setup_wizard_status")
			site = frappe.get_doc("Site", site_name)
			with (
				patch.object(frappe, "get_all", return_value=[site_name]),
				patch.object(frappe, "get_doc", return_value=site),
				patch.object(Site, "get_login_sid", return_value="fixture-sid") as sid,
				patch("press.press.doctype.site.site.FrappeClient") as client,
				patch.object(site, "reload"),
				patch.object(site, "save"),
				patch.object(site, "capture_signup_event"),
				patch.object(frappe.db, "rollback") as rollback,
			):
				client.return_value.get_value.return_value = {"setup_complete": 1}
				sync_setup_wizard_status()
				sid.assert_called_once_with(user="Administrator")
				self.assertEqual(site.setup_wizard_complete, 1)
				rollback.assert_not_called()
