"""G-88: page hints cross the HTTP boundary without granting write permission."""

import unittest

import frappe

from platform_core.ai.tests.base import DOCTYPE, USER_A, USER_B, AiTestCase


# The G-88 server code is not written yet (AJA-2436). Remove this skip in that change.
@unittest.skip("G-88 page_context server code is not written yet")
class TestPageContext(AiTestCase):
	def contextual_call(self, client, tool, arguments, context):
		response = self.rpc(
			client,
			"tools/call",
			{
				"name": tool,
				"arguments": arguments,
				"_meta": {"page_context": context},
			},
		)
		self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
		return response.json["result"]

	def test_open_record_and_selection_are_acknowledged(self):
		name = self.make_record(USER_A)
		context = {"doctype": DOCTYPE, "name": name, "selected_names": [name]}
		result = self.contextual_call(
			self.login(USER_A), "plt_get_document", {"doctype": DOCTYPE, "name": name}, context
		)
		self.assertFalse(result["isError"], result)
		self.assertEqual(result.get("_meta", {}).get("page_context"), context)

	def test_foreign_selection_is_denied_and_logged_before_preview(self):
		own = self.make_record(USER_A, title="Before")
		foreign = self.make_record(USER_B, title="Private selection")
		result = self.contextual_call(
			self.login(USER_A),
			"plt_update_document",
			{"doctype": DOCTYPE, "name": own, "data": {"title": "After"}},
			{"doctype": DOCTYPE, "name": own, "selected_names": [foreign]},
		)
		self.assert_denied(result, "permission")
		self.assertEqual(frappe.db.get_value(DOCTYPE, own, "title"), "Before")
		log = self.last_log(tool="plt_update_document", target_name=own)
		self.assertEqual(log.decision, "denied")
		self.assertFalse(log.proposal)
		self.assertNotIn("Private selection", str(result))

	def test_foreign_open_record_is_denied(self):
		own = self.make_record(USER_A)
		foreign = self.make_record(USER_B)
		result = self.contextual_call(
			self.login(USER_A),
			"plt_get_document",
			{"doctype": DOCTYPE, "name": own},
			{"doctype": DOCTYPE, "name": foreign},
		)
		self.assert_denied(result, "permission")

	def test_malformed_or_oversized_context_is_denied(self):
		name = self.make_record(USER_A)
		client = self.login(USER_A)
		for context in [
			None,
			[],
			{},
			{"doctype": DOCTYPE, "selected_names": [name] * 201},
			{"doctype": DOCTYPE, "approved": True},
			{"doctype": DOCTYPE, "name": 12},
			{"doctype": DOCTYPE, "selected_names": "all"},
		]:
			with self.subTest(context_type=type(context).__name__):
				result = self.contextual_call(
					client, "plt_get_document", {"doctype": DOCTYPE, "name": name}, context
				)
				self.assert_denied(result, "invalid_arguments")

	def test_context_cannot_grant_permission_to_the_target(self):
		own = self.make_record(USER_A)
		foreign = self.make_record(USER_B)
		result = self.contextual_call(
			self.login(USER_A),
			"plt_get_document",
			{"doctype": DOCTYPE, "name": foreign},
			{"doctype": DOCTYPE, "name": own},
		)
		self.assert_denied(result, "permission")

	def test_one_click_still_needs_preview_digest_and_human_approval(self):
		name = self.make_record(USER_A, title="Before")
		client = self.login(USER_A)
		result = self.contextual_call(
			client,
			"plt_update_document",
			{"doctype": DOCTYPE, "name": name, "data": {"title": "After"}},
			{"doctype": DOCTYPE, "name": name},
		)
		proposal = result["structuredContent"]
		self.assertEqual(proposal["status"], "approval_required")
		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "title"), "Before")
		self.assertTrue(proposal["preview"]["changes"])
		proposal_id = proposal["proposal_id"]
		denied = self.human(
			client, "POST", "approve_proposal", body={"proposal_id": proposal_id, "digest": "0" * 64}
		)
		self.assertEqual(denied.status_code, 200)
		self.assertFalse(denied.json["message"]["executed"])
		self.assertEqual(denied.json["message"]["deny_reason"], "digest_mismatch")
		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "title"), "Before")
		approved = self.approve(client, proposal_id)
		self.assertEqual(approved.status_code, 200)
		self.assertTrue(approved.json["message"]["executed"])
		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "title"), "After")
