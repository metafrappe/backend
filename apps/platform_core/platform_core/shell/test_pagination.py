"""Check native Frappe paging over HTTP on the isolated shell site."""

import json
from urllib.parse import quote, urlencode
from uuid import uuid4

import frappe

from platform_core.tests.shell_http_fixture import (
	CHILD_DOCTYPE,
	DOCTYPE,
	PROTECTED_DOCTYPE,
	ShellHTTPFixture,
)

PAGE_SIZE = 20
ROW_COUNT = 45
COLLECTION_LIST = "/api/method/platform_core.api.collection.list_records"


class TestServerPagination(ShellHTTPFixture):
	def make_record(self, title, entries=()):
		record = frappe.get_doc(doctype=DOCTYPE, title=title, test_entries=list(entries)).insert()
		self.addCleanup(self.remove_record, record.name)
		return record

	@staticmethod
	def remove_record(name):
		frappe.delete_doc(DOCTYPE, name, force=True)
		frappe.db.commit()

	def get_page(self, path, start, response_key, **parameters):
		query = urlencode(dict(parameters, limit_start=start, limit_page_length=PAGE_SIZE))
		status, _headers, body = self.request(f"{path}?{query}", self.reader_sid)
		self.assertEqual(status, 200)
		return json.loads(body)[response_key]

	def test_parent_list_is_paginated(self):
		prefix = uuid4().hex
		titles = [f"{prefix}-{index:02}" for index in range(ROW_COUNT)]
		for title in titles:
			self.make_record(title)
		frappe.db.commit()

		path = f"/api/resource/{quote(DOCTYPE, safe='')}"
		for start in (0, PAGE_SIZE, 2 * PAGE_SIZE, ROW_COUNT):
			with self.subTest(start=start):
				page = self.get_page(
					path,
					start,
					"data",
					filters=json.dumps({"title": ["like", f"{prefix}-%"]}),
					fields=json.dumps(["title"]),
					order_by="title asc, name asc",
				)
				self.assertEqual([row["title"] for row in page], titles[start : start + PAGE_SIZE])

	def test_child_list_is_paginated_for_the_selected_parent(self):
		entries = [{"entry": f"Item {index:02}"} for index in range(ROW_COUNT)]
		record = self.make_record("Paging parent", entries)
		self.make_record("Other parent", [{"entry": "Other item"}])
		frappe.db.commit()

		for start in (0, PAGE_SIZE, 2 * PAGE_SIZE, ROW_COUNT):
			with self.subTest(start=start):
				page = self.get_page(
					COLLECTION_LIST,
					start,
					"message",
					doctype=CHILD_DOCTYPE,
					parent=DOCTYPE,
					filters=json.dumps({"parent": record.name, "parenttype": DOCTYPE, "parentfield": "test_entries"}),
					fields=json.dumps(["entry"]),
					order_by="idx asc",
				)
				self.assertEqual(page, entries[start : start + PAGE_SIZE])

	def request_collection(self, doctype, filters, fields, **parameters):
		query = urlencode({
			"doctype": doctype,
			"filters": json.dumps(filters),
			"fields": json.dumps(fields),
			**parameters,
		})
		status, _headers, body = self.request(f"{COLLECTION_LIST}?{query}", self.reader_sid)
		return status, json.loads(body)

	def test_collection_caps_an_oversized_page(self):
		prefix = uuid4().hex
		titles = [f"{prefix}-{index:02}" for index in range(ROW_COUNT)]
		for title in titles:
			self.make_record(title)
		frappe.db.commit()

		status, body = self.request_collection(
			DOCTYPE, {"title": ["like", f"{prefix}-%"]}, ["title"],
			limit_start=PAGE_SIZE, limit_page_length=ROW_COUNT, order_by="title asc",
		)

		self.assertEqual(status, 200)
		self.assertEqual([row["title"] for row in body["message"]], titles[PAGE_SIZE : 2 * PAGE_SIZE])

	def test_collection_denies_a_protected_parent_type(self):
		record = frappe.get_doc(doctype=PROTECTED_DOCTYPE, title="Protected paging parent").insert()
		self.addCleanup(self.remove_protected_record, record.name)
		frappe.db.commit()

		status, _body = self.request_collection(
			CHILD_DOCTYPE,
			{"parent": record.name, "parenttype": PROTECTED_DOCTYPE, "parentfield": "entries"},
			["entry"], parent=PROTECTED_DOCTYPE,
		)
		self.assertEqual(status, 403)

	@staticmethod
	def remove_protected_record(name):
		frappe.delete_doc(PROTECTED_DOCTYPE, name, force=True)
		frappe.db.commit()

	def test_collection_denies_a_private_child_field(self):
		record = self.make_record("Paging parent", [{"entry": "Public", "private_entry": "Private"}])
		frappe.db.commit()

		status, _body = self.request_collection(
			CHILD_DOCTYPE,
			{"parent": record.name, "parenttype": DOCTYPE, "parentfield": "test_entries"},
			["private_entry"], parent=DOCTYPE,
		)
		self.assertEqual(status, 403)

	def test_collection_requires_each_child_scope_filter(self):
		record = self.make_record("Paging parent", [{"entry": "Public"}])
		frappe.db.commit()
		filters = {"parent": record.name, "parenttype": DOCTYPE, "parentfield": "test_entries"}

		for missing in filters:
			with self.subTest(missing=missing):
				status, _body = self.request_collection(
					CHILD_DOCTYPE,
					{key: value for key, value in filters.items() if key != missing},
					["entry"], parent=DOCTYPE,
				)
				self.assertEqual(status, 417)
