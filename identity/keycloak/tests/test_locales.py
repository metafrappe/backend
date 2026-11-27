"""Dil ayarını ve tema çevirilerini sınar. Keycloak gerekmez (AJA-1777).

Karar 44: dil seçilmezse ekran İngilizce açılır. Açık diller en ve tr dilleridir.
Her temada en ve tr dosyaları aynı anahtarları taşır. Böylece bir dilde eksik metin kalmaz.
"""

import re
import unittest

from helpers import DIRECTORY, read_realm

THEME = DIRECTORY / "themes" / "atonota"
THEME_TYPES = ("account", "login", "email")
PLACEHOLDER = re.compile(r"\{\{\w+\}\}|\{\d+\}")


def read_messages(path) -> dict:
    messages = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "!")):
            continue
        key, separator, value = line.partition("=")
        if separator:
            messages[key.strip()] = value
    return messages


class DefaultLocaleTest(unittest.TestCase):
    def test_default_locale_is_english(self):
        realm = read_realm()
        self.assertEqual(realm["defaultLocale"], "en")
        self.assertEqual(set(realm["supportedLocales"]), {"en", "tr"})


class ThemeMessageKeysTest(unittest.TestCase):
    def test_en_and_tr_have_same_keys(self):
        for theme_type in THEME_TYPES:
            with self.subTest(theme_type):
                folder = THEME / theme_type / "messages"
                english = read_messages(folder / "messages_en.properties")
                turkish = read_messages(folder / "messages_tr.properties")
                self.assertEqual(sorted(set(turkish) - set(english)), [], "İngilizce dosyada eksik anahtar")
                self.assertEqual(sorted(set(english) - set(turkish)), [], "Türkçe dosyada eksik anahtar")

    def test_en_and_tr_use_same_placeholders(self):
        for theme_type in THEME_TYPES:
            folder = THEME / theme_type / "messages"
            english = read_messages(folder / "messages_en.properties")
            turkish = read_messages(folder / "messages_tr.properties")
            for key in sorted(set(english) & set(turkish)):
                with self.subTest(theme=theme_type, key=key):
                    self.assertTrue(english[key].strip(), "boş İngilizce metin")
                    self.assertEqual(set(PLACEHOLDER.findall(english[key])), set(PLACEHOLDER.findall(turkish[key])))


if __name__ == "__main__":
    unittest.main()
