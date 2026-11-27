"""The Keycloak email theme follows the notification language rule (AJA-1783, parent AJA-1733).

Rule: contracts/locale-and-notifications.md, section 3. The email uses the recipient's language.
Keycloak reads the user's `locale` attribute. When the attribute is empty, Keycloak uses the realm's
default locale. The default locale test is in test_locales.py (AJA-1777, Decision 44).

This file checks what the theme controls:
- the theme offers exactly the open languages, en and tr;
- every text in every email comes from the message files, so no text is fixed to one language;
- every message key that an email uses exists in both languages;
- the HTML email says its own language, and no template fixes a date format to one language.

Keycloak is not needed. Standard library only.
"""

import re
import unittest

from helpers import DIRECTORY

EMAIL = DIRECTORY / "themes" / "atonota" / "email"
OPEN_LANGUAGES = {"en", "tr"}
# Keycloak builds the subject key from the template name. These four templates are in the theme.
SUBJECT_KEYS = {
    "email-verification.ftl": "emailVerificationSubject",
    "password-reset.ftl": "passwordResetSubject",
    "executeActions.ftl": "executeActionsSubject",
    "magiclink-email.ftl": "magiclink-emailSubject",
}
MESSAGE_CALL = re.compile(r"""msg\(\s*"([^"$]+)\"""")
DYNAMIC_PREFIX = re.compile(r"""msg\(\s*"([^"$]+)\$\{""")
COMMENT = re.compile(r"<#--.*?-->", re.DOTALL)
EXPRESSION = re.compile(r"\$\{[^}]*\}")
DIRECTIVE = re.compile(r"</?[#@][^>]*>", re.DOTALL)
HTML_TAG = re.compile(r"<[^>]*>", re.DOTALL)
ENTITY = re.compile(r"&[a-z]+;")


def read_messages(path) -> dict:
    messages = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "!")):
            continue
        key, separator, value = line.partition("=")
        if separator:
            messages[key.strip()] = value.strip()
    return messages


def templates():
    return sorted((EMAIL / "html").glob("*.ftl")) + sorted((EMAIL / "text").glob("*.ftl"))


def theme_languages() -> set:
    for line in (EMAIL / "theme.properties").read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "locales":
            return {part.strip() for part in value.split(",") if part.strip()}
    return set()


class EmailThemeLanguageTest(unittest.TestCase):
    def test_theme_offers_exactly_the_open_languages(self):
        self.assertEqual(theme_languages(), OPEN_LANGUAGES)
        for language in OPEN_LANGUAGES:
            with self.subTest(language=language):
                self.assertTrue((EMAIL / "messages" / f"messages_{language}.properties").is_file())

    def test_no_email_text_is_fixed_to_one_language(self):
        for template in templates():
            with self.subTest(template=template.name, folder=template.parent.name):
                text = template.read_text(encoding="utf-8")
                text = COMMENT.sub(" ", text)
                text = DIRECTIVE.sub(" ", text)
                text = EXPRESSION.sub(" ", text)
                text = HTML_TAG.sub(" ", text)
                text = ENTITY.sub(" ", text)
                self.assertEqual(re.findall(r"[^\W\d_]{2,}", text), [], "text outside msg()")

    def test_every_used_key_exists_in_every_language(self):
        catalogs = {
            language: read_messages(EMAIL / "messages" / f"messages_{language}.properties")
            for language in OPEN_LANGUAGES
        }
        used = set(SUBJECT_KEYS.values())
        prefixes = set()
        for template in templates():
            text = COMMENT.sub(" ", template.read_text(encoding="utf-8"))
            used.update(MESSAGE_CALL.findall(text))
            prefixes.update(DYNAMIC_PREFIX.findall(text))
        self.assertIn("atResetIntro", used)
        for language, catalog in catalogs.items():
            for key in sorted(used):
                with self.subTest(language=language, key=key):
                    self.assertTrue(catalog.get(key), f"{key} is missing in messages_{language}")
            for prefix in sorted(prefixes):
                with self.subTest(language=language, prefix=prefix):
                    keys = {key for key in catalog if key.startswith(prefix)}
                    self.assertTrue(keys, f"no {prefix}* key in messages_{language}")
                    other = {key for key in catalogs["en"] if key.startswith(prefix)}
                    self.assertEqual(keys, other)

    def test_every_theme_template_has_a_subject_key(self):
        for template in (EMAIL / "html").glob("*.ftl"):
            if template.name == "template.ftl":
                continue
            with self.subTest(template=template.name):
                self.assertIn(template.name, SUBJECT_KEYS)
                self.assertTrue((EMAIL / "text" / template.name).is_file())

    def test_html_email_says_its_language(self):
        layout = (EMAIL / "html" / "template.ftl").read_text(encoding="utf-8")
        self.assertIn('lang="${locale.language}"', layout)

    def test_no_template_fixes_a_date_format(self):
        for template in templates():
            with self.subTest(template=template.name, folder=template.parent.name):
                text = template.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"\?(string|date|datetime|time)\s*\(")
                self.assertNotRegex(text, r"<#setting\s+locale")


if __name__ == "__main__":
    unittest.main()
