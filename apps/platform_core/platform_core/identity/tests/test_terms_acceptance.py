"""A terms acceptance keeps the terms version and the shown language (AJA-1781, AJA-1733).

The record shape is `contracts/terms_acceptance.schema.json` (AJA-1776). A new acceptance writes a
new record. An old record is never changed or deleted. The record keeps the language of the text
on the screen, not the account language of the user.
"""

import json

import frappe
from frappe.tests import IntegrationTestCase

from platform_core.identity import terms_acceptance
from platform_core.identity.terms_acceptance import (
	ACCEPTANCE_DOCTYPE,
	VERSION_DOCTYPE,
	TermsAcceptanceRefused,
	accept,
	publish_version,
	record,
)

TERMS = "test-terms-of-use"
SUBJECT = "00000000-0000-4000-8000-000000000781"


class TestTermsAcceptance(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.lang = frappe.local.lang
		self.addCleanup(setattr, frappe.local, "lang", self.lang)
		frappe.db.delete(ACCEPTANCE_DOCTYPE, {"terms_id": TERMS})
		frappe.db.delete(VERSION_DOCTYPE, {"terms_id": TERMS})
		publish_version(TERMS, "2026-11-01")

	def count(self):
		return frappe.db.count(ACCEPTANCE_DOCTYPE, {"terms_id": TERMS})

	def test_record_keeps_shown_language_after_language_change(self):
		# The account language is English. The user switched the sign-up screen to Turkish.
		frappe.local.lang = "en"
		row = accept(TERMS, "2026-11-01", "tr", SUBJECT)

		saved = record(row.name)
		self.assertEqual(saved["shown_locale"], "tr")
		self.assertEqual(saved["terms_version"], "2026-11-01")
		self.assertEqual(saved["terms_id"], TERMS)
		self.assertEqual(saved["user"], SUBJECT)
		self.assertTrue(saved["accepted_at"].endswith("Z"))

	def test_record_matches_contract_fields(self):
		schema = json.loads(terms_acceptance.contract_file().read_text(encoding="utf-8"))
		saved = record(accept(TERMS, "2026-11-01", "en-GB", SUBJECT).name)
		self.assertEqual(set(saved), set(schema["properties"]))
		self.assertEqual(set(schema["required"]), set(saved))

	def test_old_acceptance_keeps_old_version_after_new_version(self):
		old = accept(TERMS, "2026-11-01", "en", SUBJECT)
		publish_version(TERMS, "2026-12-01")
		new = accept(TERMS, "2026-12-01", "tr", SUBJECT)

		self.assertEqual(self.count(), 2)
		self.assertEqual(record(old.name)["terms_version"], "2026-11-01")
		self.assertEqual(record(old.name)["shown_locale"], "en")
		self.assertEqual(record(new.name)["terms_version"], "2026-12-01")

	def test_acceptance_is_append_only(self):
		row = accept(TERMS, "2026-11-01", "en", SUBJECT)
		doc = frappe.get_doc(ACCEPTANCE_DOCTYPE, row.name)
		doc.terms_version = "2026-12-01"
		with self.assertRaises(frappe.PermissionError):
			doc.save()
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc(ACCEPTANCE_DOCTYPE, row.name)
		self.assertEqual(record(row.name)["terms_version"], "2026-11-01")

	def test_unknown_version_is_refused(self):
		with self.assertRaises(TermsAcceptanceRefused) as caught:
			accept(TERMS, "1999-01-01", "en", SUBJECT)
		self.assertEqual(caught.exception.http_status_code, 422)
		self.assertEqual(self.count(), 0)

	def test_unknown_terms_is_refused(self):
		with self.assertRaises(TermsAcceptanceRefused):
			accept("test-no-such-terms", "2026-11-01", "en", SUBJECT)
		self.assertEqual(frappe.db.count(ACCEPTANCE_DOCTYPE, {"terms_id": "test-no-such-terms"}), 0)

	def test_closed_language_is_refused(self):
		# Only the languages in contracts/locales.json are open.
		for locale in ("de", "xx-YY", "", None, "TR"):
			with self.subTest(locale=locale), self.assertRaises(TermsAcceptanceRefused):
				accept(TERMS, "2026-11-01", locale, SUBJECT)
		self.assertEqual(self.count(), 0)

	def test_missing_user_is_refused(self):
		with self.assertRaises(TermsAcceptanceRefused):
			accept(TERMS, "2026-11-01", "en", "")
		self.assertEqual(self.count(), 0)
