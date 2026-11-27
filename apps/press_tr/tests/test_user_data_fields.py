"""G-52: Press TR declares its personal data records in the `user_data_fields` hook.

The checks need Frappe, but not a database:
- The hook lists every press_tr record that points to a person, or names why it is left out.
- Frappe's personal data download returns the press_tr records of the person.
- Account anonymization clears the person's recovery notes and keeps the record history.
"""

import ast
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frappe.website.doctype.personal_data_download_request import personal_data_download_request

from press_tr import hooks
from press_tr.press_identity import anonymization

APP = Path(__file__).resolve().parents[1] / "press_tr"
IDENTITY_LINK = "PTR Identity Link"
RECOVERY_REVIEW = "PTR Recovery Review"
# Keycloak session rows hold live session ids. A download file must not carry them.
# Anonymization deletes these rows in close_account.
LEFT_OUT = {"PTR Keycloak Session": "live session ids, deleted by close_account"}


def doctype_definitions() -> dict[str, dict]:
	definitions = {}
	for path in APP.rglob("doctype/*/*.json"):
		data = json.loads(path.read_text(encoding="utf-8"))
		if data.get("doctype") == "DocType":
			definitions[data["name"]] = data
	return definitions


def fields_of(definition: dict) -> dict[str, dict]:
	return {field["fieldname"]: field for field in definition["fields"]}


def hook_value() -> list[dict]:
	# Read the source too, so a commented-out example never counts as the hook.
	tree = ast.parse((APP / "hooks.py").read_text(encoding="utf-8"))
	for node in tree.body:
		if isinstance(node, ast.Assign) and [ast.unparse(t) for t in node.targets] == ["user_data_fields"]:
			return ast.literal_eval(node.value)
	raise AssertionError("press_tr hooks.py does not set user_data_fields")


class HookScopeTest(unittest.TestCase):
	def test_hook_is_set_in_source_and_matches_the_module(self):
		self.assertEqual(hook_value(), hooks.user_data_fields)

	def test_hook_lists_identity_link_and_recovery_review(self):
		self.assertEqual(
			hook_value(),
			[
				{"doctype": IDENTITY_LINK, "filter_by": "user"},
				{
					"doctype": RECOVERY_REVIEW,
					"filter_by": "identity_link.user",
					"redact_fields": ["review_note"],
				},
			],
		)

	def test_every_person_record_is_listed_or_left_out_with_a_reason(self):
		definitions = doctype_definitions()
		listed = {spec["doctype"] for spec in hook_value()}
		for name, definition in definitions.items():
			targets = {field.get("options") for field in definition["fields"] if field["fieldtype"] == "Link"}
			if targets & {"User", IDENTITY_LINK}:
				with self.subTest(doctype=name):
					self.assertTrue(name in listed or name in LEFT_OUT)
		self.assertFalse(listed & LEFT_OUT.keys())

	def test_filter_and_redacted_fields_exist(self):
		definitions = doctype_definitions()
		for spec in hook_value():
			with self.subTest(doctype=spec["doctype"]):
				fields = fields_of(definitions[spec["doctype"]])
				link, _dot, target = spec["filter_by"].partition(".")
				self.assertEqual(fields[link]["fieldtype"], "Link")
				if target:
					self.assertEqual(
						fields_of(definitions[fields[link]["options"]])[target]["options"], "User"
					)
				else:
					self.assertEqual(fields[link]["options"], "User")
				for field in spec.get("redact_fields", ()):
					self.assertIn(field, fields)
					self.assertFalse(fields[field].get("reqd"))


class PersonalDataDownloadTest(unittest.TestCase):
	def test_download_returns_press_tr_records_of_the_person(self):
		user = "person@example.test"
		rows = {
			(IDENTITY_LINK, "user"): [
				{"name": "link-1", "issuer": "https://id.example.test", "subject": "sub-1"}
			],
			(RECOVERY_REVIEW, "identity_link.user"): [
				{"name": "review-1", "identity_link": "link-1", "status": "Open", "review_note": "note"}
			],
		}

		def get_all(doctype, filters, fields):
			self.assertEqual(fields, ["*"])
			((field, value),) = filters.items()
			self.assertEqual(value, user)
			return list(rows.get((doctype, field), []))

		module = personal_data_download_request.frappe
		with (
			patch.object(module, "get_hooks", return_value=hooks.user_data_fields),
			patch.object(module, "get_all", side_effect=get_all),
		):
			data = json.loads(personal_data_download_request.get_user_data(user))

		self.assertEqual(data[IDENTITY_LINK][0]["subject"], "sub-1")
		self.assertEqual(data[RECOVERY_REVIEW][0]["name"], "review-1")


class RecoveryReviewAnonymizationTest(unittest.TestCase):
	def run_redaction(self, versions):
		frappe = MagicMock()
		frappe.get_hooks.return_value = hooks.user_data_fields
		frappe.parse_json.side_effect = json.loads
		frappe.as_json.side_effect = json.dumps
		reviews = [SimpleNamespace(name="review-1")]

		def get_all(doctype, filters, *, fields, order_by, limit):
			if doctype == RECOVERY_REVIEW:
				self.assertEqual(filters, {"identity_link": "link-1"})
				return reviews
			self.assertEqual(doctype, "Version")
			self.assertEqual(filters, {"ref_doctype": RECOVERY_REVIEW, "docname": "review-1"})
			return [SimpleNamespace(name=name, data=json.dumps(data)) for name, data in versions.items()]

		frappe.get_all.side_effect = get_all
		with patch.object(anonymization, "frappe", frappe):
			anonymization.redact_recovery_reviews("link-1")
		return frappe

	def test_review_note_is_cleared_without_touching_the_decision(self):
		frappe = self.run_redaction({})
		frappe.db.set_value.assert_called_once_with(
			RECOVERY_REVIEW, "review-1", {"review_note": None}, update_modified=False
		)
		frappe.db.delete.assert_not_called()

	def test_history_keeps_every_change_and_drops_only_note_values(self):
		changed = [
			["status", "Open", "Approved"],
			["review_note", None, "Called the person at +90 555 000 00 00"],
			["reviewed_by", None, "reviewer@example.test"],
		]
		frappe = self.run_redaction(
			{"version-1": {"changed": changed}, "version-2": {"changed": changed[:1]}}
		)

		version_writes = [call for call in frappe.db.set_value.call_args_list if call.args[0] == "Version"]
		self.assertEqual(len(version_writes), 1)
		doctype, name, field, value = version_writes[0].args
		self.assertEqual((doctype, name, field), ("Version", "version-1", "data"))
		self.assertEqual(
			json.loads(value)["changed"],
			[
				["status", "Open", "Approved"],
				["review_note", None, None],
				["reviewed_by", None, "reviewer@example.test"],
			],
		)
		self.assertEqual(version_writes[0].kwargs, {"update_modified": False})
		frappe.db.delete.assert_not_called()

	def test_anonymization_runs_the_recovery_step_for_the_link(self):
		link = SimpleNamespace(name="link-1", user="person@example.test", issuer="https://id.example.test")
		deleted = SimpleNamespace(name="link-1", user="person@example.test", issuer="deleted")
		profile = SimpleNamespace(name="person@example.test", user_type="Website User")
		frappe = MagicMock()
		frappe.conf.press_identity_sync_user = "sync@example.test"
		frappe.db.get_value.return_value = profile
		with (
			patch.object(anonymization, "frappe", frappe),
			patch.object(anonymization, "deleted_identity_subject", return_value="digest"),
			patch.object(anonymization, "find_identity", side_effect=[link, deleted]),
			patch.object(anonymization, "close_account"),
			patch.object(anonymization, "redact_profile") as redact_profile,
			patch.object(anonymization, "redact_recovery_reviews") as redact_reviews,
		):
			self.assertTrue(anonymization.anonymize_linked_user("https://id.example.test", "sub-1"))
		redact_reviews.assert_called_once_with("link-1")
		redact_profile.assert_called_once()

	def test_generic_hook_step_leaves_press_tr_records_to_their_own_steps(self):
		frappe = MagicMock()
		frappe.get_hooks.return_value = hooks.user_data_fields
		frappe.get_all.return_value = []
		frappe.db.get_table_columns.return_value = []
		profile = SimpleNamespace(name="person@example.test", email="person@example.test", user_image=None)
		with (
			patch.object(anonymization, "frappe", frappe),
			patch.object(anonymization, "rename_parent_and_child"),
			patch.object(anonymization, "get_link_fields", return_value=[]),
			patch.object(anonymization, "remove_encrypted_password"),
		):
			anonymization.redact_profile(profile, "deleted-x@invalid.example")
		touched = {call.args[0] for call in frappe.db.set_value.call_args_list}
		self.assertFalse(touched & {IDENTITY_LINK, RECOVERY_REVIEW})


if __name__ == "__main__":
	unittest.main()
