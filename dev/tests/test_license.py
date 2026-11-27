"""The repository root carries the MIT license.

The license text matches the frappesetup LICENSE file. Only the year and owner line may differ.
The README names the license so readers find it.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LICENSE = ROOT / "LICENSE"
README = ROOT / "README.md"
COPYRIGHT = re.compile(r"^Copyright \(c\) \d{4} karacaismail$")

MIT_BODY = """Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


class License(unittest.TestCase):
    def test_root_license_is_mit(self):
        self.assertTrue(LICENSE.is_file(), "LICENSE is missing at the repository root")
        lines = LICENSE.read_text().split("\n")
        self.assertEqual(lines[0], "MIT License")
        self.assertEqual(lines[1], "")
        self.assertRegex(lines[2], COPYRIGHT)
        self.assertEqual(lines[3], "")
        self.assertEqual("\n".join(lines[4:]), MIT_BODY)

    def test_readme_names_the_license(self):
        text = README.read_text()
        self.assertIn("[MIT lisansı](LICENSE)", text)


if __name__ == "__main__":
    unittest.main()
