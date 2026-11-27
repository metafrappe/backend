"""G-48: upload security on a real site.

The test runs on a separate test site through `bin/test`.
"""

from unittest.mock import patch

import frappe
from frappe.core.doctype.file.file import FileTypeNotAllowed
from frappe.tests import IntegrationTestCase
from frappe.tests.utils import set_request

from platform_core.config import turkey_setup

EXPECTED = {
	"max_file_size": 25,
	"strip_exif_metadata_from_uploaded_images": 1,
	"allow_guests_to_upload_files": 0,
	"only_allow_system_managers_to_upload_public_files": 1,
}


class TestUploadSecurity(IntegrationTestCase):
	def tearDown(self):
		# Clean up even when a test fails half way, so no other test sees this state.
		frappe.db.rollback()
		frappe.set_user("Administrator")
		frappe.local.request = None
		for key in ("doctype", "docname", "file_name", "content"):
			frappe.form_dict.pop(key, None)

	def test_settings_are_applied(self):
		frappe.db.set_single_value(
			"System Settings",
			{
				"max_file_size": 100,
				"strip_exif_metadata_from_uploaded_images": 0,
				"allow_guests_to_upload_files": 1,
				"only_allow_system_managers_to_upload_public_files": 0,
			},
		)
		turkey_setup.apply()
		for field, value in EXPECTED.items():
			with self.subTest(field=field):
				self.assertEqual(frappe.db.get_single_value("System Settings", field), value)

	def test_guest_cannot_upload_a_file(self):
		frappe.db.set_single_value("System Settings", "allow_guests_to_upload_files", 1)
		turkey_setup.apply()
		from frappe.handler import upload_file

		set_request(method="POST", path="/api/method/upload_file")
		frappe.set_user("Guest")
		frappe.form_dict.update(doctype="User", docname="Guest", file_name="g48.txt", content="x")
		self.assertRaises(frappe.PermissionError, upload_file)

	def test_extension_outside_the_whitelist_is_rejected(self):
		with patch.object(turkey_setup, "ALLOWED_FILE_EXTENSIONS", ("pdf", "csv")):
			turkey_setup.apply()
		set_request(method="POST", path="/")
		name = frappe.generate_hash()
		bad = frappe.new_doc("File", file_name=f"{name}.exe", content=name)
		self.assertRaises(FileTypeNotAllowed, bad.insert)
		good = frappe.new_doc("File", file_name=f"{name}.csv", content=name)
		good.insert()

	def test_decided_whitelist_allows_csv_and_rejects_svg_and_html(self):
		frappe.db.set_single_value("System Settings", "allowed_file_extensions", "")
		turkey_setup.apply()
		set_request(method="POST", path="/")
		name = frappe.generate_hash()
		for ext in ("svg", "html"):
			with self.subTest(ext=ext):
				bad = frappe.new_doc("File", file_name=f"{name}.{ext}", content=name)
				self.assertRaises(FileTypeNotAllowed, bad.insert)
		frappe.new_doc("File", file_name=f"{name}.csv", content=name).insert()
