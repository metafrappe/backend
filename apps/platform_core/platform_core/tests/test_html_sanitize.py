"""G-145: HTML that a user writes is cleaned on the server before it is saved (AJA-2282).

Three paths store user HTML: rich text fields, comments and email.
Frappe cleans most of it in `Document._sanitize_content`. It skips a value that parses as JSON,
so `["<img src=x onerror=alert(1)>"]` was saved as written. The rich text and email tests below
fail without `platform_core.html_sanitize`. The comment tests pass on plain Frappe too:
`Comment.validate` always cleans. They stay, so a later change cannot lose that guarantee.
Rich text tests use the ToDo description, a Text Editor field with no cleaning of its own.
Note is not used there: `Note.validate` already cleans its content.
Each test reads the saved value back from the database.
"""

import frappe
from frappe.core.doctype.communication.email import make as make_email
from frappe.desk.form.utils import add_comment, update_comment
from frappe.tests import IntegrationTestCase

from platform_core import hooks

SANITIZE_HOOK = "platform_core.html_sanitize.sanitize_rich_text"
# Each value carries active content. None of these words may reach the database.
HARMFUL_VALUES = (
	"<p>hello</p><script>alert(1)</script>",
	'<img src="x" onerror="alert(1)">',
	'<a href="javascript:alert(1)">link</a>',
	'["<img src=x onerror=alert(1)>"]',
	'"<script>alert(1)</script>"',
	'{"a": "<svg onload=alert(1)>"}',
)
FORBIDDEN = ("<script", "onerror", "onload", "javascript:")
SAFE_VALUE = "<p>Hello <strong>team</strong></p>"


def _assert_clean(test, value, source):
	text = (value or "").lower()
	for word in FORBIDDEN:
		test.assertNotIn(word, text, f"{source} saved active content: {value!r}")


class TestHtmlSanitizeHook(IntegrationTestCase):
	def test_hook_runs_for_every_doctype(self):
		self.assertIn(SANITIZE_HOOK, hooks.doc_events["*"]["validate"])


class TestRichText(IntegrationTestCase):
	def test_new_todo_is_cleaned(self):
		for value in HARMFUL_VALUES:
			with self.subTest(value=value):
				todo = frappe.get_doc({"doctype": "ToDo", "description": value}).insert(
					ignore_permissions=True
				)
				_assert_clean(self, frappe.db.get_value("ToDo", todo.name, "description"), "ToDo")

	def test_edited_todo_is_cleaned(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": SAFE_VALUE}).insert(ignore_permissions=True)
		for value in HARMFUL_VALUES:
			with self.subTest(value=value):
				todo.reload()
				todo.description = value
				todo.save(ignore_permissions=True)
				_assert_clean(self, frappe.db.get_value("ToDo", todo.name, "description"), "ToDo")

	def test_client_insert_is_cleaned(self):
		for value in HARMFUL_VALUES:
			with self.subTest(value=value):
				saved = frappe.client.insert({"doctype": "ToDo", "description": value})
				_assert_clean(
					self, frappe.db.get_value("ToDo", saved["name"], "description"), "frappe.client.insert"
				)

	def test_safe_html_is_kept(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": SAFE_VALUE}).insert(ignore_permissions=True)
		saved = frappe.db.get_value("ToDo", todo.name, "description")
		self.assertIn("<strong>team</strong>", saved)

	def test_json_in_plain_text_field_is_kept(self):
		# A plain text field may hold JSON on purpose. Only rich text fields are cleaned.
		value = '{"a": "x<y"}'
		note = frappe.get_doc({"doctype": "Note", "title": value, "content": SAFE_VALUE})
		note.insert(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Note", note.name, "title"), value)


class TestComment(IntegrationTestCase):
	def setUp(self):
		self.note = frappe.get_doc({"doctype": "Note", "title": "G-145 comments", "content": SAFE_VALUE})
		self.note.insert(ignore_permissions=True)

	def test_added_comment_is_cleaned(self):
		for value in HARMFUL_VALUES:
			with self.subTest(value=value):
				comment = add_comment("Note", self.note.name, value, "Administrator", "Administrator")
				_assert_clean(self, frappe.db.get_value("Comment", comment.name, "content"), "add_comment")

	def test_edited_comment_is_cleaned(self):
		comment = add_comment("Note", self.note.name, SAFE_VALUE, "Administrator", "Administrator")
		for value in HARMFUL_VALUES:
			with self.subTest(value=value):
				update_comment(comment.name, value)
				_assert_clean(self, frappe.db.get_value("Comment", comment.name, "content"), "update_comment")


class TestEmail(IntegrationTestCase):
	def setUp(self):
		self.note = frappe.get_doc({"doctype": "Note", "title": "G-145 email", "content": SAFE_VALUE})
		self.note.insert(ignore_permissions=True)

	def test_email_body_is_cleaned(self):
		for value in HARMFUL_VALUES:
			with self.subTest(value=value):
				result = make_email(
					doctype="Note",
					name=self.note.name,
					content=value,
					subject="G-145",
					recipients="g145@example.test",
					send_email=False,
				)
				saved = frappe.db.get_value("Communication", result["name"], "content")
				_assert_clean(self, saved, "Communication")
