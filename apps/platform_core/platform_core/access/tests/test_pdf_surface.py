"""PDF download and print: a hidden record is not printed on any print path (G-121).

Every path below checks the record through `validate_print_permission`
(`frappe/www/printview.py:544`) or `check_permission=True` (`printview.py:426`). The record hook
of the engine answers that check. The refusal comes before any PDF is made, so the tests do not
need a PDF engine.
"""

import json

from platform_core.access.tests.base import DOCTYPE, EMPLOYEE_1, MANAGER_1, AccessRuleTestCase

PRINT_FORMAT = "/api/method/frappe.utils.print_format."


class TestPdfSurface(AccessRuleTestCase):
	def setUp(self):
		super().setUp()
		self.client = self.login(EMPLOYEE_1)
		self.other = self.records[MANAGER_1]

	def test_single_pdf_of_a_hidden_record_is_refused(self):
		response = self.send(
			self.client, "GET", PRINT_FORMAT + "download_pdf", query={"doctype": DOCTYPE, "name": self.other}
		)

		self.assertEqual(response.status_code, 403)

	def test_multi_pdf_with_a_hidden_record_is_refused(self):
		response = self.send(
			self.client,
			"POST",
			PRINT_FORMAT + "download_multi_pdf",
			body={"doctype": DOCTYPE, "name": json.dumps([self.other])},
		)

		self.assertEqual(response.status_code, 403)
		self.assertNotEqual(response.headers.get("Content-Type"), "application/pdf")

	def test_multi_pdf_by_document_type_map_with_a_hidden_record_is_refused(self):
		response = self.send(
			self.client,
			"POST",
			PRINT_FORMAT + "download_multi_pdf",
			body={"doctype": {DOCTYPE: [self.other]}, "name": "g121"},
		)

		self.assertEqual(response.status_code, 403)

	def test_print_html_of_a_hidden_record_is_refused(self):
		response = self.send(
			self.client,
			"GET",
			"/api/method/frappe.www.printview.get_html_and_style",
			query={"doc": DOCTYPE, "name": self.other},
		)

		self.assertEqual(response.status_code, 403)
		self.assertNotIn(f"Talep {MANAGER_1}", response.get_data(as_text=True))

	def test_print_page_of_a_hidden_record_is_refused(self):
		response = self.send(self.client, "GET", "/printview", query={"doctype": DOCTYPE, "name": self.other})

		self.assertEqual(response.status_code, 403)
		self.assertNotIn(f"Talep {MANAGER_1}", response.get_data(as_text=True))
