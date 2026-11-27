"""Realtime events: a user does not join the room of a record or a list they may not see (G-121).

The realtime server asks the web process before a socket joins a room
(`frappe/realtime/auth.py:87`). It calls `/api/method/frappe.realtime.has_permission`:

- with a record name for the record room (`doc_subscribe`, `doc_open`),
- with an empty name for the list room of a document type (`doctype_subscribe`).

Frappe sends `list_update` to the list room with the name of the changed record and the user
who changed it (`frappe/model/document.py:1784`). On a governed type that tells a narrowed user
about records they cannot see. So the list room is open only to users whose rules show every
record. Decision note, section 9.
"""

from platform_core.access.tests.base import (
	DOCTYPE,
	EMPLOYEE_1,
	FREE_DOCTYPE,
	HR,
	MANAGER_1,
	NO_RULE,
	AccessRuleTestCase,
)

ROOM_CHECK = "/api/method/frappe.realtime.has_permission"


class TestRealtimeRooms(AccessRuleTestCase):
	def room_check(self, client, doctype: str, name: str = ""):
		return self.send(client, "GET", ROOM_CHECK, query={"doctype": doctype, "name": name})

	def test_has_permission_guest_denied(self):
		client = self.anonymous()

		self.assertEqual(self.room_check(client, DOCTYPE, self.records[EMPLOYEE_1]).status_code, 403)
		self.assertEqual(self.room_check(client, DOCTYPE).status_code, 403)

	def test_has_permission_foreign_data_denied(self):
		"""The record room of a record outside the rule is closed."""
		client = self.login(EMPLOYEE_1)

		response = self.room_check(client, DOCTYPE, self.records[MANAGER_1])

		self.assertEqual(response.status_code, 403)

	def test_record_room_of_an_own_record_is_open(self):
		client = self.login(EMPLOYEE_1)

		response = self.room_check(client, DOCTYPE, self.records[EMPLOYEE_1])

		self.assertEqual(response.status_code, 200)
		self.assertIs(response.json["message"], True)

	def test_list_room_of_a_governed_type_is_closed_to_a_narrowed_user(self):
		"""The list room would carry the names of hidden records and the user who changed them."""
		for user in (EMPLOYEE_1, MANAGER_1, NO_RULE):
			with self.subTest(user=user):
				response = self.room_check(self.login(user), DOCTYPE)

				self.assertEqual(response.status_code, 403)

	def test_list_room_is_open_to_a_user_who_sees_every_record(self):
		response = self.room_check(self.login(HR), DOCTYPE)

		self.assertEqual(response.status_code, 200)

	def test_list_room_of_a_type_without_rules_does_not_change(self):
		response = self.room_check(self.login(EMPLOYEE_1), FREE_DOCTYPE)

		self.assertEqual(response.status_code, 200)
