"""Tests for the comment language gate (Decision 44).

The gate fails when a file holds more Turkish code comments than the baseline allows.
The baseline lists today's comments per file and may only go down.
"""

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "check_comments.py"
REPO = SCRIPT.parents[2]


def load_gate():
    spec = importlib.util.spec_from_file_location("check_comments", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = load_gate()

TURKISH_COMMENT = "# Kullanıcı kaydını oku\n"
ENGLISH_COMMENT = "# Read the user record\n"


class GateRepo:
    """A throwaway Git repository with the gate's baseline path."""

    def __init__(self, test: unittest.TestCase):
        workspace = tempfile.TemporaryDirectory()
        test.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "gate-test")
        self.git("config", "user.email", "gate-test@example.invalid")
        self.git("config", "core.hooksPath", "/dev/null")

    def git(self, *args: str) -> str:
        done = subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True)
        return done.stdout

    def write(self, path: str, text: str) -> None:
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")
        self.git("add", "--", path)

    def baseline(self, files: dict) -> None:
        self.write(gate.BASELINE_PATH, json.dumps({"files": files}))

    def read_baseline(self) -> dict:
        return json.loads((self.root / gate.BASELINE_PATH).read_text(encoding="utf-8"))["files"]

    def commit(self) -> None:
        self.git("commit", "-q", "-m", "snapshot")

    def run(self, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gate.main(list(argv), root=self.root)
        return code, out.getvalue() + err.getvalue()


class NewTurkishCommentTests(unittest.TestCase):
    def setUp(self):
        self.repo = GateRepo(self)
        self.repo.baseline({})

    def test_new_turkish_python_comment_fails(self):
        self.repo.write("apps/core/reader.py", TURKISH_COMMENT + "x = 1\n")
        code, output = self.repo.run("--check")
        self.assertEqual(code, 1, output)
        self.assertIn("apps/core/reader.py", output)
        self.assertIn("apps/core/reader.py:1", output)

    def test_new_turkish_docstring_fails(self):
        self.repo.write("apps/core/reader.py", 'def read():\n    """Kaydı döndürür."""\n')
        self.assertEqual(self.repo.run("--check")[0], 1)

    def test_new_turkish_typescript_comment_fails(self):
        self.repo.write("e2e/login.ts", "// Giriş sayfasını aç\nconst a = 1;\n")
        self.assertEqual(self.repo.run("--check")[0], 1)

    def test_new_turkish_yaml_and_shell_comments_fail(self):
        self.repo.write("deploy/stack.yaml", "name: x # değer\n")
        self.assertEqual(self.repo.run("--check")[0], 1)
        self.repo.write("deploy/stack.yaml", "name: x\n")
        self.repo.write("dev/bin/start", "#!/bin/sh\n# Sunucuyu başlat\necho ok\n")
        self.assertEqual(self.repo.run("--check")[0], 1)

    def test_new_turkish_java_comment_fails(self):
        self.repo.write("identity/spi/Main.java", "/* Oturum açılır */\nclass Main {}\n")
        self.assertEqual(self.repo.run("--check")[0], 1)

    def test_english_comment_passes(self):
        self.repo.write("apps/core/reader.py", ENGLISH_COMMENT + "x = 1\n")
        self.assertEqual(self.repo.run("--check")[0], 0)


class FalseAlarmTests(unittest.TestCase):
    def setUp(self):
        self.repo = GateRepo(self)
        self.repo.baseline({})

    def test_turkish_strings_are_not_comments(self):
        self.repo.write("apps/core/text.py", 'LABEL = "Kullanıcı # değil"\n')
        self.repo.write("e2e/text.ts", "const a = 'Giriş // yap';\nconst b = `Çıkış /* yap */`;\n")
        self.repo.write("deploy/values.yaml", 'title: "Başlık # değil"\n')
        code, output = self.repo.run("--check")
        self.assertEqual(code, 0, output)

    def test_regex_with_hash_is_not_a_comment(self):
        self.repo.write("e2e/pattern.ts", "const re = /#ş+/;\n")
        self.assertEqual(self.repo.run("--check")[0], 0)

    def test_lang_ok_note_allows_a_name(self):
        self.repo.write("apps/core/city.py", "# Default city is İstanbul. lang-ok: place name\n")
        self.assertEqual(self.repo.run("--check")[0], 0)

    def test_translation_catalogue_and_docs_are_skipped(self):
        self.repo.write("apps/core/translations/tr.csv", "Kaydet,Kaydet\n")
        self.repo.write("docs/guide.md", "# Başlık\n")
        self.repo.write("apps/core/data.json", '{"a": "# Değer"}\n')
        self.assertEqual(self.repo.run("--check")[0], 0)


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.repo = GateRepo(self)

    def test_baselined_comment_passes(self):
        self.repo.write("apps/core/reader.py", TURKISH_COMMENT)
        self.repo.baseline({"apps/core/reader.py": 1})
        code, output = self.repo.run("--check")
        self.assertEqual(code, 0, output)

    def test_second_comment_in_baselined_file_fails(self):
        self.repo.write("apps/core/reader.py", TURKISH_COMMENT + "# Kaydı sil\n")
        self.repo.baseline({"apps/core/reader.py": 1})
        code, output = self.repo.run("--check")
        self.assertEqual(code, 1, output)
        self.assertIn("baseline 1", output)

    def test_translated_comment_passes_and_hints_to_lower_baseline(self):
        self.repo.write("apps/core/reader.py", ENGLISH_COMMENT)
        self.repo.baseline({"apps/core/reader.py": 1})
        code, output = self.repo.run("--check")
        self.assertEqual(code, 0, output)
        self.assertIn("--update-baseline", output)

    def test_baseline_may_not_grow_against_base_ref(self):
        self.repo.write("apps/core/reader.py", TURKISH_COMMENT)
        self.repo.baseline({"apps/core/reader.py": 1})
        self.repo.commit()
        self.repo.write("apps/core/reader.py", TURKISH_COMMENT + "# Kaydı sil\n")
        self.repo.baseline({"apps/core/reader.py": 2})
        code, output = self.repo.run("--check", "--base-ref", "main")
        self.assertEqual(code, 1, output)
        self.assertIn("baseline grew", output)

    def test_new_file_in_baseline_against_base_ref_fails(self):
        self.repo.baseline({})
        self.repo.commit()
        self.repo.write("apps/core/new.py", TURKISH_COMMENT)
        self.repo.baseline({"apps/core/new.py": 1})
        code, output = self.repo.run("--check", "--base-ref", "main")
        self.assertEqual(code, 1, output)
        self.assertIn("baseline grew", output)

    def test_lower_baseline_against_base_ref_passes(self):
        self.repo.write("apps/core/reader.py", TURKISH_COMMENT)
        self.repo.baseline({"apps/core/reader.py": 1})
        self.repo.commit()
        self.repo.write("apps/core/reader.py", ENGLISH_COMMENT)
        self.repo.baseline({})
        code, output = self.repo.run("--check", "--base-ref", "main")
        self.assertEqual(code, 0, output)

    def test_update_baseline_lowers_counts(self):
        self.repo.write("apps/core/reader.py", ENGLISH_COMMENT)
        self.repo.write("apps/core/other.py", TURKISH_COMMENT)
        self.repo.baseline({"apps/core/reader.py": 1, "apps/core/other.py": 1})
        code, output = self.repo.run("--update-baseline")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.repo.read_baseline(), {"apps/core/other.py": 1})

    def test_update_baseline_refuses_to_grow(self):
        self.repo.write("apps/core/reader.py", TURKISH_COMMENT + "# Kaydı sil\n")
        self.repo.baseline({"apps/core/reader.py": 1})
        code, output = self.repo.run("--update-baseline")
        self.assertEqual(code, 1, output)
        self.assertEqual(self.repo.read_baseline(), {"apps/core/reader.py": 1})

    def test_init_baseline_only_when_missing(self):
        self.repo.write("apps/core/reader.py", TURKISH_COMMENT)
        code, output = self.repo.run("--init-baseline")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.repo.read_baseline(), {"apps/core/reader.py": 1})
        self.assertEqual(self.repo.run("--init-baseline")[0], 1)


class RepositoryTests(unittest.TestCase):
    def test_repository_passes_its_own_baseline(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gate.main(["--check"], root=REPO)
        self.assertEqual(code, 0, out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
