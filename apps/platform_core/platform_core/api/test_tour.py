"""G-139 tour progress endpoints over the Frappe request path.

Each user reads and writes only their own progress. A guest gets 403.
The expected results come from requirement G-139 and `contracts/platform_core-tour.openapi.yaml`.
"""

import json
import secrets

import frappe
from frappe.tests import IntegrationTestCase
from frappe.tests.test_api import make_request
from frappe.utils import get_test_client

API = "/api/method/platform_core.api.tour."
DOCTYPE = "PLT Tour Progress"
OWNER = "tour-owner@example.test"
OTHER = "tour-other@example.test"
TOUR = "test-leave-application"


class TestTourEndpoints(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.password = secrets.token_urlsafe(30)
		for email in (OWNER, OTHER):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Sample",
					"user_type": "Website User",
					"send_welcome_email": 0,
					"new_password": cls.password,
				}
			).insert(ignore_permissions=True)
		frappe.db.delete(DOCTYPE, {"tour_id": TOUR})
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete(DOCTYPE, {"tour_id": TOUR})
		for email in (OWNER, OTHER):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.delete(DOCTYPE, {"tour_id": TOUR})
		frappe.db.commit()

	def send(self, client, method, endpoint, *, body=None, query=None):
		headers = {"Accept": "application/json"}
		kwargs = {"path": API + endpoint, "method": method, "headers": headers}
		if body is not None:
			headers["Content-Type"] = "application/json"
			kwargs["data"] = json.dumps(body)
		if query:
			kwargs["query_string"] = query
		# Committed on purpose: the request uses another connection.
		frappe.db.commit()  # nosemgrep: frappe-request-commit
		try:
			return make_request(client.open, args=(), kwargs=kwargs, site=frappe.local.site)
		finally:
			frappe.db.rollback()

	def login(self, user):
		client = get_test_client(use_cookies=True)
		response = make_request(
			client.open,
			args=(),
			kwargs={
				"path": "/api/method/login",
				"method": "POST",
				"headers": {"Accept": "application/json", "Content-Type": "application/json"},
				"data": json.dumps({"usr": user, "pwd": self.password}),
			},
			site=frappe.local.site,
		)
		self.assertEqual(response.status_code, 200)
		return client

	def anonymous(self):
		return get_test_client(use_cookies=False)

	def progress(self, **changes):
		value = {
			"tour_id": TOUR,
			"version": 1,
			"status": "active",
			"current_step": "leave-type",
			"seen_steps": ["intro"],
		}
		value.update(changes)
		return value

	def save(self, client, **changes):
		return self.send(client, "POST", "save_tour_progress", body=self.progress(**changes))

	def read(self, client, tour_id=TOUR):
		return self.send(client, "GET", "get_tour_progress", query={"tour_id": tour_id})

	# --- security gate pairs ---

	def test_get_tour_progress_guest_denied(self):
		response = self.read(self.anonymous())
		self.assertEqual(response.status_code, 403)

	def test_get_tour_progress_foreign_data_denied(self):
		"""The other user cannot see the owner's progress. They read their own empty state."""
		self.assertEqual(self.save(self.login(OWNER), seen_steps=["intro", "secret-step"]).status_code, 200)

		response = self.read(self.login(OTHER))

		self.assertEqual(response.status_code, 200)
		self.assertIsNone(response.json["message"])
		self.assertNotIn("secret-step", response.get_data(as_text=True))

	def test_save_tour_progress_guest_denied(self):
		response = self.save(self.anonymous())
		self.assertEqual(response.status_code, 403)
		self.assertFalse(frappe.db.exists(DOCTYPE, {"tour_id": TOUR}))

	def test_save_tour_progress_foreign_data_denied(self):
		"""A body naming another user is rejected. The owner's record does not change."""
		owner = self.login(OWNER)
		self.assertEqual(self.save(owner, seen_steps=["intro"]).status_code, 200)

		response = self.send(
			self.login(OTHER), "POST", "save_tour_progress", body={**self.progress(), "user": OWNER}
		)

		self.assertEqual(response.status_code, 417)
		self.assertEqual(self.read(owner).json["message"]["seen_steps"], ["intro"])
		self.assertEqual(frappe.db.count(DOCTYPE, {"tour_id": TOUR}), 1)

	# --- behaviour ---

	def test_first_visit_has_no_progress(self):
		response = self.read(self.login(OWNER))
		self.assertEqual(response.status_code, 200)
		self.assertIsNone(response.json["message"])

	def test_progress_is_stored_by_user_and_tour_and_resumed(self):
		owner = self.login(OWNER)
		saved = self.save(owner, status="snoozed", current_step="dates", seen_steps=["intro", "leave-type"])
		self.assertEqual(saved.status_code, 200)

		message = self.read(owner).json["message"]

		self.assertEqual(
			message,
			{
				"tour_id": TOUR,
				"version": 1,
				"status": "snoozed",
				"current_step": "dates",
				"seen_steps": ["intro", "leave-type"],
			},
		)
		self.assertEqual(frappe.db.get_value(DOCTYPE, {"tour_id": TOUR}, "user"), OWNER)

	def test_two_users_keep_separate_records(self):
		self.save(self.login(OWNER), seen_steps=["intro"])
		self.save(self.login(OTHER), seen_steps=["leave-type"])
		self.assertEqual(frappe.db.count(DOCTYPE, {"tour_id": TOUR}), 2)

	def test_an_older_tab_does_not_erase_a_newer_version(self):
		owner = self.login(OWNER)
		self.save(owner, version=2, status="completed", seen_steps=["intro", "new-step"])

		response = self.save(owner, version=1, status="active", seen_steps=["intro"])

		self.assertEqual(response.status_code, 200)
		message = self.read(owner).json["message"]
		self.assertEqual((message["version"], message["status"]), (2, "completed"))
		self.assertEqual(message["seen_steps"], ["intro", "new-step"])

	def test_restart_clears_seen_steps(self):
		owner = self.login(OWNER)
		self.save(owner, status="completed", seen_steps=["intro", "leave-type"])

		response = self.send(
			owner,
			"POST",
			"save_tour_progress",
			body={**self.progress(status="active", current_step="intro", seen_steps=[]), "restart": True},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(self.read(owner).json["message"]["seen_steps"], [])

	def test_invalid_payload_is_rejected(self):
		response = self.save(self.login(OWNER), status="closed")
		self.assertEqual(response.status_code, 417)
		self.assertFalse(frappe.db.exists(DOCTYPE, {"tour_id": TOUR}))

	def test_get_requires_the_post_method_for_writes(self):
		response = self.send(self.login(OWNER), "GET", "save_tour_progress", query=self.progress())
		self.assertNotEqual(response.status_code, 200)

	def test_deleting_the_user_deletes_their_progress(self):
		leaver = "tour-leaver@example.test"
		if not frappe.db.exists("User", leaver):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": leaver,
					"first_name": "Sample",
					"user_type": "Website User",
					"send_welcome_email": 0,
					"new_password": self.password,
				}
			).insert(ignore_permissions=True)
		self.save(self.login(leaver), seen_steps=["intro"])
		self.assertTrue(frappe.db.exists(DOCTYPE, {"user": leaver}))

		frappe.set_user("Administrator")
		frappe.delete_doc("User", leaver, force=True, ignore_permissions=True)

		self.assertFalse(frappe.db.exists(DOCTYPE, {"user": leaver}))
