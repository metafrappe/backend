"""Files and attachments: an attachment follows the rule of the record it is attached to (G-121).

Frappe decides on a private file through the attached record (`frappe/core/doctype/file/file.py:1088`).
Its list condition for files only asks whether the user may read the document type
(`file.py:1128`), so it listed the attachments of every record. A public file was readable by
anyone. The engine now narrows both: decision note, section 9.
"""

import frappe

from platform_core.access.tests.base import (
	DOCTYPE,
	EMPLOYEE_1,
	HR,
	MANAGER_1,
	RECORD_OWNERS,
	AccessRuleTestCase,
)

FILE_REST = "/api/v2/document/File"


class TestFileSurface(AccessRuleTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.private_files = {}
		cls.public_files = {}
		for owner in RECORD_OWNERS:
			cls.private_files[owner] = cls.attach(owner, is_private=1)
			cls.public_files[owner] = cls.attach(owner, is_private=0)
		# Committed on purpose: the request uses another connection.
		frappe.db.commit()  # nosemgrep: frappe-request-commit

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		for doc in (*cls.private_files.values(), *cls.public_files.values()):
			frappe.delete_doc("File", doc.name, force=True, ignore_permissions=True)
		# Committed on purpose: other connections must see this.
		frappe.db.commit()  # nosemgrep: frappe-request-commit
		super().tearDownClass()

	@classmethod
	def attach(cls, owner: str, is_private: int):
		# Frappe gives files with the same content the same address. Each file has its own content,
		# so a download asks about this file and not about another file with that address.
		token = frappe.generate_hash(length=10)
		return frappe.get_doc(
			doctype="File",
			file_name=f"g121-{token}.txt",
			content=f"Made-up attachment {token} of a request.".encode(),
			is_private=is_private,
			attached_to_doctype=DOCTYPE,
			attached_to_name=cls.records[owner],
		).insert(ignore_permissions=True)

	def listed_files(self, client) -> set[str]:
		response = self.rest_list(
			client, "File", filters=[["attached_to_doctype", "=", DOCTYPE]], fields=("name",)
		)
		self.assertEqual(response.status_code, 200)
		return {row["name"] for row in response.json["data"]}

	def files_of(self, owners) -> set[str]:
		return {files[owner].name for files in (self.private_files, self.public_files) for owner in owners}

	def test_private_attachment_of_a_hidden_record_is_refused(self):
		client = self.login(EMPLOYEE_1)
		other = self.private_files[MANAGER_1]

		self.assertEqual(self.rest_get(client, other.name, "File").status_code, 403)
		self.assertEqual(self.send(client, "GET", other.file_url).status_code, 403)

	def test_private_attachment_of_an_own_record_is_served(self):
		client = self.login(EMPLOYEE_1)
		own = self.private_files[EMPLOYEE_1]

		self.assertEqual(self.rest_get(client, own.name, "File").status_code, 200)
		self.assertEqual(self.send(client, "GET", own.file_url).status_code, 200)

	def test_public_attachment_record_of_a_hidden_record_is_refused(self):
		"""The file record names the hidden record. Only the record's readers may open it."""
		client = self.login(EMPLOYEE_1)

		response = self.rest_get(client, self.public_files[MANAGER_1].name, "File")

		self.assertEqual(response.status_code, 403)

	def test_file_list_shows_only_attachments_of_visible_records(self):
		client = self.login(EMPLOYEE_1)

		listed = self.listed_files(client)

		self.assertEqual(listed, self.files_of([EMPLOYEE_1]))

	def test_file_list_of_an_all_scope_user_shows_every_attachment(self):
		client = self.login(HR)

		self.assertEqual(self.listed_files(client), self.files_of(RECORD_OWNERS))
