"""GILT guideline (AJA-1739): the customer text is stored once and unchanged.

The source is the AJA-1728 description between its two marker lines.
The marker lines themselves and the surrounding blank lines are not part
of the text. The file may start with one source note; the note sits
outside the two HTML comment markers and is not hashed.
"""

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "standards" / "gilt-ant-design-x-yonergesi.md"

START = "<!-- yönerge metni başlar -->\n"
END = "\n<!-- yönerge metni biter -->\n"

# SHA-256 of the UTF-8 guideline text from AJA-1728, without the marker
# lines and without leading or trailing blank lines (38533 bytes).
EXPECTED_SHA256 = "ad2e1470676a8844d78affc7d997c1771b4c0dd41c92aa301cd461b0b3a6e2e5"


class GiltGuideline(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(GUIDE.is_file(), f"missing {GUIDE.relative_to(ROOT)}")

    def test_text_matches_source(self):
        self.assertTrue(GUIDE.is_file(), f"missing {GUIDE.relative_to(ROOT)}")
        raw = GUIDE.read_bytes()
        self.assertNotIn(b"\r", raw)
        content = raw.decode("utf-8")
        self.assertEqual(content.count(START), 1)
        self.assertEqual(content.count(END), 1)
        self.assertTrue(content.endswith(END), "nothing may follow the end marker")
        note, rest = content.split(START)
        text = rest[: -len(END)]
        self.assertNotIn("<!--", note)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual(digest, EXPECTED_SHA256)


if __name__ == "__main__":
    unittest.main()
