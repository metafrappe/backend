"""Format checks for the idempotency contract in contracts/idempotency.md (AJA-1749).

Standard library only. Run: python3 -I -m unittest discover -s contracts/tests -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "idempotency.md"

TYPES = {
    "okuma",
    "yeni kayıt",
    "hedef durum",
    "artış",
    "sürümlü düzenleme",
    "toplu işlem",
    "uzun iş",
}
# These types add or count something durable. A retry must not add it twice.
KEY_TYPES = {"yeni kayıt", "artış", "toplu işlem", "uzun iş"}

SECTIONS = (
    "Anahtarın adı ve biçimi",
    "Anahtarın kapsamı",
    "Saklama süresi",
    "Aynı anahtar ve aynı içerik",
    "Aynı anahtar ve başka içerik",
    "İlk istek sürerken gelen istek",
    "Sürüm koşulu",
    "Sağlayıcı bildirimi: iyzico",
    "Banka havalesi",
    "Uç listesi",
)

TERMS = (
    "`Idempotency-Key`",
    "`IdempotencyKeyReusedError`",
    "`IdempotencyInProgressError`",
    "`VersionConflictError`",
    "`conversationId`",
    "`token`",
    "`iyziReferenceCode`",
    "G-125",
    "SA-6",
    "SA-8",
    "SA-11",
)

GOALS = ("Plan satın alma", "Kredi yükleme", "Kullanıcı daveti", "Destek kaydı")
COLUMNS = ("Kullanıcı işi", "Uç", "Tür", "Ödeme", "İş anahtarı", "Sürüm koşulu", "Durum")


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def endpoint_rows(text: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("|") and tuple(cells(line)) == COLUMNS:
            rows = []
            for row in lines[i + 2 :]:
                if not row.startswith("|"):
                    break
                rows.append(dict(zip(COLUMNS, cells(row))))
            return rows
    return []


class IdempotencyContract(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(DOC.is_file(), f"{DOC} is missing")
        self.text = DOC.read_text(encoding="utf-8")
        self.rows = endpoint_rows(self.text)

    def test_sections_exist(self) -> None:
        headings = re.findall(r"^##+ (?:\d+\. )?(.+?)\s*$", self.text, re.MULTILINE)
        for section in SECTIONS:
            self.assertIn(section, headings)

    def test_terms_exist(self) -> None:
        for term in TERMS:
            self.assertIn(term, self.text)

    def test_endpoint_table_exists(self) -> None:
        self.assertGreaterEqual(len(self.rows), 10, "endpoint table is missing or too short")

    def test_user_goals_are_listed(self) -> None:
        goals = {row["Kullanıcı işi"] for row in self.rows}
        for goal in GOALS:
            self.assertTrue(any(g.startswith(goal) for g in goals), goal)

    def test_each_row_has_one_of_seven_types(self) -> None:
        for row in self.rows:
            self.assertIn(row["Tür"], TYPES, row["Uç"])

    def test_cells_use_fixed_words(self) -> None:
        for row in self.rows:
            self.assertIn(row["Ödeme"], {"evet", "hayır"}, row["Uç"])
            self.assertIn(row["İş anahtarı"], {"gerekir", "gerekmez"}, row["Uç"])
            self.assertIn(row["Sürüm koşulu"], {"gerekir", "gerekmez"}, row["Uç"])
            self.assertIn(row["Durum"], {"var", "planlanan"}, row["Uç"])
            self.assertRegex(row["Uç"], r"^`[^`]+`$")

    def test_new_record_and_payment_require_key(self) -> None:
        for row in self.rows:
            if row["Tür"] in KEY_TYPES or row["Ödeme"] == "evet":
                self.assertEqual(row["İş anahtarı"], "gerekir", row["Uç"])

    def test_reads_need_no_key(self) -> None:
        for row in self.rows:
            if row["Tür"] == "okuma":
                self.assertEqual(row["İş anahtarı"], "gerekmez", row["Uç"])
                self.assertEqual(row["Ödeme"], "hayır", row["Uç"])

    def test_edits_require_version(self) -> None:
        for row in self.rows:
            if row["Tür"] == "sürümlü düzenleme":
                self.assertEqual(row["Sürüm koşulu"], "gerekir", row["Uç"])

    def test_endpoints_are_unique(self) -> None:
        names = [row["Uç"] for row in self.rows]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
