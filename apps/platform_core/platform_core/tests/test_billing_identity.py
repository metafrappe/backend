"""The server checks the billing address and tax number by billing country (AJA-1779, AJA-1733).

The rules come from the contract `contracts/billing_identity.schema.json` (AJA-1776). The billing
country selects the address format. The interface language never selects it.
"""

import json
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

from platform_core import billing_identity
from platform_core.billing_identity import (
	BillingIdentityError,
	TaxIdServiceUnavailable,
	address_format,
	save_draft,
)

# ToDo stands in for the billing draft record, so the test can count the drafts.
DOCTYPE = "ToDo"
MARKER = "billing identity draft"


def tr_billing(**address):
	return {
		"party": {"kind": "company", "name": "Örnek Yazılım", "tax_id": "1234567890"},
		"billing_address": {
			"billing_country": "TR",
			"line1": "Atatürk Caddesi 1",
			"district": "Kadıköy",
			"province": "İstanbul",
			**address,
		},
	}


def us_billing(**party):
	return {
		"party": {"kind": "person", "name": "Jane Doe", "tax_id": None, **party},
		"billing_address": {"billing_country": "US", "line1": "1 Main Street", "city": "Springfield"},
	}


def accepting_checker(country, tax_id):
	return True


def refusing_checker(country, tax_id):
	return False


def silent_checker(country, tax_id):
	raise TaxIdServiceUnavailable


def broken_checker(country, tax_id):
	raise TimeoutError


class BillingIdentityTest(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.local.response = frappe._dict()
		self.lang = frappe.local.lang
		frappe.db.delete(DOCTYPE, {"description": MARKER})

	def tearDown(self):
		frappe.local.lang = self.lang

	def count(self):
		return frappe.db.count(DOCTYPE, {"description": MARKER})

	def save(self, billing, checker=accepting_checker):
		return save_draft(DOCTYPE, {"description": MARKER}, billing, checker)

	def refused_fields(self, billing):
		frappe.local.response = frappe._dict()
		with self.assertRaises(BillingIdentityError) as error:
			self.save(billing)
		self.assertEqual(error.exception.http_status_code, 422)
		return {item["field"] for item in frappe.local.response["billing_errors"]}

	# 1. Province is required in Turkey. A country without a province field does not need one.

	def test_tr_address_without_province_is_refused(self):
		for province in (None, "", "  "):
			self.assertEqual(
				self.refused_fields(tr_billing(province=province)), {"billing_address.province"}
			)
		self.assertEqual(self.count(), 0)

	def test_province_is_required_in_tr_when_the_language_is_en(self):
		frappe.local.lang = "en"
		self.assertEqual(self.refused_fields(tr_billing(province=None)), {"billing_address.province"})

	def test_country_without_province_field_saves_without_province(self):
		doc, _check = self.save(us_billing())
		self.assertEqual(doc.doctype, DOCTYPE)
		self.assertEqual(self.count(), 1)
		self.assertNotIn("province", address_format("US")["required"])

	def test_tr_language_does_not_add_province_to_another_country(self):
		frappe.local.lang = "tr"
		self.save(us_billing())
		self.assertEqual(self.count(), 1)

	def test_default_country_needs_its_city(self):
		billing = us_billing()
		billing["billing_address"]["city"] = ""
		self.assertEqual(self.refused_fields(billing), {"billing_address.city"})

	def test_formats_come_from_the_contract(self):
		contract = json.loads(billing_identity.contract_file().read_text(encoding="utf-8"))
		formats = contract["x-address-formats"]
		self.assertEqual(address_format("TR"), formats["TR"])
		self.assertEqual(address_format("DE"), formats["default"])

	def test_lowercase_or_missing_country_is_refused(self):
		for country in ("tr", "", None, "TUR"):
			billing = tr_billing(billing_country=country)
			self.assertIn("billing_address.billing_country", self.refused_fields(billing))
		self.assertEqual(self.count(), 0)

	# 2. A one-part name is accepted. A long company title is kept whole.

	def test_one_part_name_is_accepted(self):
		doc, _check = self.save(us_billing(name="Madonna"))
		self.assertEqual(doc.doctype, DOCTYPE)
		self.assertEqual(self.count(), 1)

	def test_long_company_title_is_not_cut(self):
		title = "Örnek Uluslararası Bilgi Teknolojileri Danışmanlık Yazılım Sanayi ve Ticaret Anonim Şirketi " * 3
		billing = tr_billing()
		billing["party"]["name"] = title
		clean = billing_identity.validate(billing)
		self.assertEqual(clean["party"]["name"], title.strip())

	def test_empty_name_is_refused(self):
		self.assertEqual(self.refused_fields(us_billing(name="   ")), {"party.name"})

	# 3. The tax service is down. The server does not say "wrong number". The draft is kept.

	def test_tax_service_down_gives_unavailable_and_keeps_the_draft(self):
		for checker in (silent_checker, broken_checker):
			frappe.local.response = frappe._dict()
			_doc, check = self.save(tr_billing(), checker)
			self.assertEqual(check["result"], "unavailable")
			self.assertEqual(frappe.local.response["tax_id_check"], check)
			self.assertNotIn("billing_errors", frappe.local.response)
		self.assertEqual(self.count(), 2)

	def test_no_tax_service_gives_unavailable(self):
		_doc, check = self.save(tr_billing(), checker=None)
		self.assertEqual(check["result"], "unavailable")
		self.assertEqual(self.count(), 1)

	def test_tax_service_answers_valid_or_invalid(self):
		_doc, check = self.save(tr_billing(), accepting_checker)
		self.assertEqual(check["result"], "valid")
		self.assertEqual(check["billing_country"], "TR")
		_doc, check = self.save(tr_billing(), refusing_checker)
		self.assertEqual(check["result"], "invalid")
		self.assertEqual(self.count(), 2)

	def test_tax_check_matches_the_contract_values(self):
		contract = json.loads(billing_identity.contract_file().read_text(encoding="utf-8"))
		results = contract["$defs"]["tax_id_check"]["properties"]["result"]["enum"]
		_doc, check = self.save(tr_billing(), silent_checker)
		self.assertIn(check["result"], results)
		self.assertEqual(set(check), {"result", "checked_at", "billing_country"})

	def test_party_without_tax_id_skips_the_check(self):
		_doc, check = self.save(us_billing(), refusing_checker)
		self.assertIsNone(check)
		self.assertNotIn("tax_id_check", frappe.local.response)

	# Error messages come back with a translation key. No sentence is built from parts.

	def test_errors_carry_a_key_and_a_whole_translated_sentence(self):
		frappe.local.lang = "tr"
		frappe.local.response = frappe._dict()
		with self.assertRaises(BillingIdentityError):
			self.save(tr_billing(province=None))
		(item,) = frappe.local.response["billing_errors"]
		self.assertEqual(
			item,
			{
				"field": "billing_address.province",
				"code": "required",
				"message_key": "Enter the province.",
				"message": "İli yazın.",
			},
		)

	def test_every_message_key_has_a_tr_translation(self):
		csv = Path(billing_identity.__file__).parent / "translations" / "tr.csv"
		sources = {line.split(",", 1)[0] for line in csv.read_text(encoding="utf-8").splitlines()}
		for key in billing_identity.MESSAGE_KEYS.values():
			self.assertIn(key, sources)
			self.assertNotIn("{", key)
