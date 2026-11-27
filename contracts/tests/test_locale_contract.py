"""Checks for the language and notification contract (AJA-1776, parent AJA-1733).

The contract files are:
- contracts/locales.json: the only list of open languages.
- contracts/critical_messages.json: critical message keys and where they are used.
- contracts/terms_acceptance.schema.json: the terms acceptance record.
- contracts/billing_identity.schema.json: address schema and tax number result.
- contracts/locale-and-notifications.md: the rules in plain words.

Standard library only. Keycloak and Frappe are not needed.

Run: python3 -I -m unittest discover -s contracts/tests -v
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import unittest
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[1]
ROOT = CONTRACTS.parent
LOCALES = CONTRACTS / "locales.json"
CRITICAL = CONTRACTS / "critical_messages.json"
TERMS = CONTRACTS / "terms_acceptance.schema.json"
BILLING = CONTRACTS / "billing_identity.schema.json"
DOC = CONTRACTS / "locale-and-notifications.md"
CONTRACTS_DOC = ROOT / "docs" / "contracts.md"
KEYCLOAK_THEME = ROOT / "identity" / "keycloak" / "themes" / "atonota"

SURFACES = {"backend", "keycloak", "ui"}
KEYCLOAK_THEME_TYPES = {"login", "account", "email"}
TAX_ID_RESULTS = {"valid", "invalid", "unavailable"}
LANGUAGE = re.compile(r"^[a-z]{2}$")
LOCALE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
CRITICAL_KEY = re.compile(r"^[a-z]+(\.[a-z_]+)+$")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def open_languages() -> list[str]:
    return load(LOCALES)["open_languages"]


def read_properties(path: Path) -> dict[str, str]:
    messages = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "!")):
            continue
        key, separator, value = line.partition("=")
        if separator:
            messages[key.strip()] = value.strip()
    return messages


def read_frappe_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.reader(handle) if row and not row[0].startswith("#")]


def tracked_source_files(app_dir: Path) -> list[Path]:
    """Return tracked files of a Frappe app, without its translation files."""
    output = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--", str(app_dir.relative_to(ROOT))],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    files = []
    for name in output.splitlines():
        path = ROOT / name
        if "/translations/" in name or "/tests/" in name or path.name.startswith("test_"):
            continue
        if path.suffix in {".py", ".js", ".html", ".json"}:
            files.append(path)
    return files


def resolve_notification_locale(recipient: str | None, tenant: str | None) -> str:
    """Executable form of the notification language rule in the contract.

    The order comes from locales.json. A value counts only when its language is open.
    """
    data = load(LOCALES)
    values = {"recipient": recipient, "tenant": tenant, "default": data["default_locale"]}
    for source in data["notification_locale_order"]:
        value = values[source]
        if value and value.split("-")[0] in data["open_languages"]:
            return value
    raise AssertionError("the default locale must always resolve")


class OpenLanguagesTest(unittest.TestCase):
    def test_list_shape(self):
        data = load(LOCALES)
        languages = data["open_languages"]
        self.assertEqual(languages, ["en", "tr"])
        self.assertEqual(len(languages), len(set(languages)))
        for language in languages:
            self.assertRegex(language, LANGUAGE)

    def test_default_locale_is_en_gb_and_open(self):
        data = load(LOCALES)
        self.assertEqual(data["default_locale"], "en-GB")
        self.assertIn(data["default_locale"].split("-")[0], data["open_languages"])

    def test_open_markets(self):
        self.assertEqual(load(LOCALES)["open_markets"], ["TR"])

    def test_no_other_contract_file_copies_the_list(self):
        for path in sorted(CONTRACTS.glob("*.json")):
            if path == LOCALES:
                continue
            with self.subTest(path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn('"open_languages"', text)
                self.assertNotIn('"supported_locales"', text)
                self.assertNotIn('"supportedLocales"', text)


class CriticalMessagesTest(unittest.TestCase):
    def setUp(self):
        self.messages = load(CRITICAL)["messages"]

    def test_examples_from_the_task_are_critical(self):
        keys = {message["key"] for message in self.messages}
        for key in ("auth.sign_in_failed", "auth.account_locked", "billing.payment_failed"):
            self.assertIn(key, keys)

    def test_every_entry_has_name_purpose_and_places(self):
        keys = [message["key"] for message in self.messages]
        self.assertEqual(len(keys), len(set(keys)), "a key is written twice")
        for message in self.messages:
            with self.subTest(message["key"]):
                self.assertRegex(message["key"], CRITICAL_KEY)
                self.assertTrue(message["purpose"].strip())
                self.assertTrue(message["used_in"], "the key has no place of use")
                for place in message["used_in"]:
                    self.assertIn(place["surface"], SURFACES)
                    if place["surface"] == "keycloak":
                        self.assertIn(place["theme"], KEYCLOAK_THEME_TYPES)
                        self.assertTrue(place["message_key"])
                    elif place["surface"] == "backend":
                        self.assertTrue((ROOT / place["app"]).is_dir(), place["app"])
                        self.assertTrue(place["source"].strip())
                    else:
                        self.assertEqual(place["repo"], "atonota-web")
                        self.assertTrue(place["message_key"])

    def test_keycloak_key_exists_in_every_open_language(self):
        for message in self.messages:
            for place in message["used_in"]:
                if place["surface"] != "keycloak":
                    continue
                folder = KEYCLOAK_THEME / place["theme"] / "messages"
                for language in open_languages():
                    with self.subTest(key=message["key"], language=language):
                        path = folder / f"messages_{language}.properties"
                        self.assertTrue(path.is_file(), f"{path} is missing")
                        text = read_properties(path).get(place["message_key"], "")
                        self.assertTrue(text, f"{place['message_key']} is missing in {path.name}")

    def test_backend_message_exists_in_every_open_language(self):
        for message in self.messages:
            for place in message["used_in"]:
                if place["surface"] != "backend":
                    continue
                app_dir = ROOT / place["app"]
                source = place["source"]
                for language in open_languages():
                    with self.subTest(key=message["key"], language=language):
                        if language == "en":
                            # English is the Frappe source text. It must be in the code.
                            found = any(source in path.read_text(encoding="utf-8") for path in tracked_source_files(app_dir))
                            self.assertTrue(found, f"English source text is not in {place['app']}")
                            continue
                        path = app_dir / "translations" / f"{language}.csv"
                        self.assertTrue(path.is_file(), f"{path} is missing")
                        rows = [row for row in read_frappe_csv(path) if row[0] == source]
                        if place.get("context"):
                            rows = [row for row in rows if len(row) > 2 and row[2] == place["context"]]
                        self.assertTrue(rows and rows[0][1].strip(), f"no {language} text for {message['key']}")

    def test_file_does_not_hold_a_language_list(self):
        data = load(CRITICAL)
        self.assertEqual(set(data), {"$comment", "messages"})


class NotificationLocaleTest(unittest.TestCase):
    def test_order(self):
        self.assertEqual(load(LOCALES)["notification_locale_order"], ["recipient", "tenant", "default"])

    def test_recipient_language_wins(self):
        self.assertEqual(resolve_notification_locale("tr", "en-GB"), "tr")

    def test_empty_recipient_falls_back_to_tenant(self):
        self.assertEqual(resolve_notification_locale(None, "tr"), "tr")
        self.assertEqual(resolve_notification_locale("", "tr"), "tr")

    def test_both_empty_gives_en_gb(self):
        self.assertEqual(resolve_notification_locale(None, None), "en-GB")

    def test_closed_language_is_skipped(self):
        self.assertEqual(resolve_notification_locale("de", "tr"), "tr")
        self.assertEqual(resolve_notification_locale("de", "fr"), "en-GB")


class TermsAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.schema = load(TERMS)

    def test_required_fields(self):
        self.assertEqual(
            set(self.schema["required"]),
            {"acceptance_id", "terms_id", "terms_version", "shown_locale", "user", "accepted_at"},
        )
        self.assertFalse(self.schema["additionalProperties"])

    def test_shown_locale_shape(self):
        pattern = self.schema["properties"]["shown_locale"]["pattern"]
        self.assertEqual(pattern, LOCALE.pattern)
        self.assertRegex("tr", pattern)
        self.assertRegex("en-GB", pattern)
        self.assertNotRegex("tr_TR", pattern)

    def test_record_is_append_only(self):
        self.assertTrue(self.schema["x-append-only"])

    def test_examples_follow_the_schema(self):
        for example in self.schema["examples"]:
            with self.subTest(example["acceptance_id"]):
                self.assertEqual(set(example), set(self.schema["required"]))
                self.assertRegex(example["shown_locale"], LOCALE)
                self.assertIn(example["shown_locale"].split("-")[0], open_languages())


class BillingIdentityTest(unittest.TestCase):
    def setUp(self):
        self.schema = load(BILLING)

    def test_tax_id_result_has_three_values(self):
        values = set(self.schema["$defs"]["tax_id_check"]["properties"]["result"]["enum"])
        self.assertEqual(values, TAX_ID_RESULTS)

    def test_address_comes_from_billing_country_not_language(self):
        formats = self.schema["x-address-formats"]
        self.assertIn("TR", formats)
        self.assertIn("default", formats)
        text = json.dumps(self.schema)
        self.assertNotIn("locale", text)
        self.assertNotIn('"language"', text)

    def test_turkey_requires_province(self):
        self.assertIn("province", self.schema["x-address-formats"]["TR"]["required"])
        self.assertNotIn("province", self.schema["x-address-formats"]["default"]["required"])

    def test_single_part_name_is_allowed(self):
        name = self.schema["$defs"]["party"]["properties"]["name"]
        self.assertEqual(name["minLength"], 1)
        self.assertNotIn("last_name", self.schema["$defs"]["party"]["properties"])


class DocumentTest(unittest.TestCase):
    def test_doc_states_the_rules(self):
        text = DOC.read_text(encoding="utf-8")
        for word in ("`recipient`", "`tenant`", "`en-GB`", "`terms_version`", "`shown_locale`"):
            self.assertIn(word, text)
        for value in TAX_ID_RESULTS:
            self.assertIn(f"`{value}`", text)

    def test_contracts_doc_links_the_contract(self):
        self.assertIn("contracts/locale-and-notifications.md", CONTRACTS_DOC.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
