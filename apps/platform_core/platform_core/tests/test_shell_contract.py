"""Exercise projection shapes in the normal Frappe test runner."""

import json
import os
import re
import unittest
from pathlib import Path

from platform_core.shell.bootstrap import project_sidebar
from platform_core.shell.contract_tests.contract_json import parse_json
from platform_core.shell.serialization import project_meta

SCHEMA_FILE = Path(__file__).with_name("shell_contract_components.json")
JSON_TYPES = {
	"array": (list,),
	"object": (dict,),
	"string": (str,),
	"integer": (int,),
	"number": (int, float),
	"boolean": (bool,),
	"null": (type(None),),
}


SCHEMA_KEYWORDS = {
	"$ref",
	"type",
	"enum",
	"const",
	"description",
	"default",
	"pattern",
	"minimum",
	"not",
	"required",
	"properties",
	"additionalProperties",
	"items",
	"maxItems",
	"maxProperties",
	"uniqueItems",
	"allOf",
	"if",
	"then",
	"else",
}


def matches(value, schema, components):
	if unknown := schema.keys() - SCHEMA_KEYWORDS:
		raise ValueError(f"Unsupported projection test schema keywords: {sorted(unknown)}")
	if "$ref" in schema:
		return matches(value, components[schema["$ref"].rsplit("/", 1)[1]], components)
	if kinds := schema.get("type"):
		kinds = [kinds] if isinstance(kinds, str) else kinds
		if not any(type(value) in JSON_TYPES[kind] for kind in kinds):
			return False
	if "enum" in schema and value not in schema["enum"]:
		return False
	if "const" in schema and value != schema["const"]:
		return False
	if "pattern" in schema and isinstance(value, str) and not re.search(schema["pattern"], value):
		return False
	if "minimum" in schema and value < schema["minimum"]:
		return False
	if "not" in schema and matches(value, schema["not"], components):
		return False
	if isinstance(value, dict):
		if "maxProperties" in schema and len(value) > schema["maxProperties"]:
			return False
		if set(schema.get("required", [])) - value.keys():
			return False
		properties = schema.get("properties", {})
		additional = schema.get("additionalProperties", True)
		for key, item in value.items():
			if key in properties and not matches(item, properties[key], components):
				return False
			if key not in properties and (
				additional is False
				or (isinstance(additional, dict) and not matches(item, additional, components))
			):
				return False
	if isinstance(value, list):
		if "maxItems" in schema and len(value) > schema["maxItems"]:
			return False
		if "items" in schema and not all(matches(item, schema["items"], components) for item in value):
			return False
		if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(
			value
		):
			return False
	if "if" in schema:
		branch = "then" if matches(value, schema["if"], components) else "else"
		if not matches(value, schema.get(branch, {}), components):
			return False
	return all(matches(value, rule, components) for rule in schema.get("allOf", []))


class TestShellProjectionContract(unittest.TestCase):
	def test_projection_snapshot_matches_openapi(self):
		contract_path = os.environ.get("SHELL_TEST_OPENAPI")
		if not contract_path:
			self.skipTest("Canonical contract is mounted by the repository test runner.")
		contract = parse_json(Path(contract_path).read_bytes())
		schemas = contract["components"]["schemas"]
		snapshot = parse_json(SCHEMA_FILE.read_bytes())
		self.assertEqual(snapshot, {name: schemas[name] for name in snapshot})

	def check(self, component, payload):
		components = parse_json(SCHEMA_FILE.read_bytes())
		self.assertTrue(matches(payload, components[component], components), (component, payload))

	def test_field_condition_and_choices_match_the_contract(self):
		raw = {
			"name": "Sample",
			"fields": [
				{
					"fieldname": "choice",
					"fieldtype": "Select",
					"options": "Draft",
					"depends_on": "eval:doc.choice === 'Draft'",
					"read_only_depends_on": "eval:unsupported(doc.choice)",
				}
			],
		}
		field = project_meta(raw, {"choice"}, {"choice"})["fields"][0]
		# The Frappe metadata service adds these catalog and locale properties.
		field.update(
			component="select", sensitivity="standard", choices=[{"value": "Draft", "label": "Draft"}]
		)
		self.check("Field", field)
		self.assertIs(field["read_only"], True)

	def test_sidebar_with_no_module_and_report_matches_the_contract(self):
		source = {
			"name": "Example",
			"label": "Example",
			"module": None,
			"workspaces": [],
			"items": [
				{
					"key": "list",
					"type": "Link",
					"link_type": "DocType",
					"link_to": "Sample",
					"report": {"report_type": "Script Report", "ref_doctype": "Sample"},
				}
			],
		}
		self.check("SidebarData", project_sidebar(source))


# GILT opening data (AJA-1766). Each locale and market value is a separate field.
LOCALE_FIELDS = {
	"language_tag",
	"language",
	"region",
	"time_zone",
	"transaction_currency",
	"billing_country",
	"measurement_system",
	"selected_market",
	"open_markets",
}
# German interface, Turkish billing address and euro prices in the same session.
LOCALE_MIXED = {
	"language_tag": "de-DE",
	"language": "de",
	"region": "DE",
	"time_zone": "Europe/Istanbul",
	"transaction_currency": "EUR",
	"billing_country": "TR",
	"measurement_system": "metric",
	"selected_market": "TR",
	"open_markets": ["TR"],
}
# The user and the tenant have no settings.
LOCALE_EMPTY = {
	"language_tag": "en-GB",
	"language": "en",
	"region": "GB",
	"time_zone": "Europe/Istanbul",
	"transaction_currency": None,
	"billing_country": None,
	"measurement_system": "metric",
	"selected_market": "TR",
	"open_markets": ["TR"],
}


class TestLocaleContract(unittest.TestCase):
	def setUp(self):
		self.components = parse_json(SCHEMA_FILE.read_bytes())

	def valid(self, component, payload):
		return matches(payload, self.components[component], self.components)

	def test_every_locale_value_is_a_required_field_of_its_own(self):
		locale = self.components["Locale"]
		self.assertEqual(set(locale["required"]), LOCALE_FIELDS)
		self.assertEqual(set(locale["properties"]), LOCALE_FIELDS)
		self.assertIs(locale["additionalProperties"], False)
		for name in LOCALE_FIELDS:
			missing = {key: value for key, value in LOCALE_MIXED.items() if key != name}
			self.assertFalse(self.valid("Locale", missing), name)

	def test_mixed_language_billing_and_currency_session_is_valid(self):
		self.assertTrue(self.valid("Locale", LOCALE_MIXED))

	def test_empty_settings_fall_back_to_en_gb(self):
		properties = self.components["Locale"]["properties"]
		self.assertEqual(properties["language_tag"]["default"], "en-GB")
		self.assertEqual(properties["language"]["default"], "en")
		self.assertEqual(properties["region"]["default"], "GB")
		self.assertEqual(properties["measurement_system"]["default"], "metric")
		self.assertIsNone(properties["transaction_currency"]["default"])
		self.assertIsNone(properties["billing_country"]["default"])
		self.assertTrue(self.valid("Locale", LOCALE_EMPTY))

	def test_selected_market_that_is_not_open_is_null(self):
		self.assertTrue(self.valid("Locale", {**LOCALE_EMPTY, "selected_market": None}))

	def test_malformed_codes_are_rejected(self):
		for name, value in (
			("language_tag", "en_GB"),
			("language_tag", "english"),
			("language", "EN"),
			("region", "gb"),
			("time_zone", "+03:00"),
			("transaction_currency", "eur"),
			("transaction_currency", "EURO"),
			("billing_country", "TUR"),
			("measurement_system", "us"),
			("selected_market", "tr"),
			("open_markets", ["TR", "TR"]),
			("open_markets", "TR"),
		):
			self.assertFalse(self.valid("Locale", {**LOCALE_MIXED, name: value}), (name, value))

	def test_calendar_date_has_no_time_zone(self):
		self.assertTrue(self.valid("CalendarDate", "2026-11-27"))
		for value in ("2026-11-27T00:00:00Z", "27.11.2026", "2026-11-27+03:00"):
			self.assertFalse(self.valid("CalendarDate", value), value)

	def test_instant_carries_a_time_zone_offset(self):
		for value in ("2026-11-27T09:30:00+03:00", "2026-11-27T06:30:00Z", "2026-11-27T06:30:00.125Z"):
			self.assertTrue(self.valid("Instant", value), value)
		for value in ("2026-11-27T09:30:00", "2026-11-27", "09:30:00+03:00"):
			self.assertFalse(self.valid("Instant", value), value)

	def test_bootstrap_adds_locale_and_keeps_the_old_fields(self):
		contract_path = os.environ.get("SHELL_TEST_OPENAPI")
		if not contract_path:
			self.skipTest("Canonical contract is mounted by the repository test runner.")
		schemas = parse_json(Path(contract_path).read_bytes())["components"]["schemas"]
		bootstrap = schemas["Bootstrap"]
		self.assertEqual(bootstrap["properties"]["locale"], {"$ref": "#/components/schemas/Locale"})
		self.assertNotIn("locale", bootstrap["required"])
		self.assertIn("formatting", bootstrap["required"])
		self.assertIn("language", schemas["User"]["required"])
		self.assertIn("time_zone", schemas["Formatting"]["required"])
