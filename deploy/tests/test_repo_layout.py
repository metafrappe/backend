"""The code sits at the root of the metafrappe/backend repository (AJA-1524, AJA-1587).

The old frappesetup repository kept this code under a backend/ folder. Paths that still start with
backend/ point to a folder that no longer exists. These tests run with the standard library only:

    python3 -I -m unittest discover -s deploy/tests
"""

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JENKINS = ROOT / "deploy" / "jenkins"
JENKINSFILES = ("backend.Jenkinsfile", "promote.Jenkinsfile", "web.Jenkinsfile")
# A path that starts with backend/. Words such as atonota-backend/ or deploy/backend/ do not count.
OLD_PREFIX = re.compile(r"(^|[^a-z_/.-])backend/")
# The acceptance command of AJA-1587, without the paths it excludes itself.
GREP_EXCLUDES = (":!*.md", ":!*.patch", ":!dev/naming", ":!brand-exclusions.txt")
# Lines that keep the old prefix on purpose: (path, text on the line or None for every line, reason).
KEPT = (
    # Gitleaks fingerprints name a commit and the path inside that commit. The commits belong to
    # the old frappesetup history, where the files were under the old folder. Changing the path
    # would break the fingerprint.
    ("dev/security/.gitleaksignore", None, "old commit fingerprints"),
    # This test names the prefix it looks for.
    ("deploy/tests/test_repo_layout.py", None, "the test itself"),
)
# Text that may keep the old prefix on any line. The rule files moved to docs/standards/ (AJA-1526).
KEPT_TEXT = ()


def old_prefix_lines(text):
    return [line for line in text.splitlines() if OLD_PREFIX.search(line)]


class JenkinsfilePathTests(unittest.TestCase):
    def test_jenkinsfiles_use_root_paths(self):
        for name in JENKINSFILES:
            with self.subTest(name=name):
                text = (JENKINS / name).read_text(encoding="utf-8")
                self.assertEqual(old_prefix_lines(text), [])

    def test_jenkinsfiles_call_the_deploy_scripts_from_the_root(self):
        for name in JENKINSFILES:
            with self.subTest(name=name):
                text = (JENKINS / name).read_text(encoding="utf-8")
                self.assertIn("deploy/bin/deploy ", text)
                self.assertIn("python3 -I deploy/release.py ", text)
                self.assertIn("includes: 'deploy/**'", text)

    def test_web_job_fetches_the_frontend_repository(self):
        text = (JENKINS / "web.Jenkinsfile").read_text(encoding="utf-8")
        self.assertIn("git url: 'https://github.com/metafrappe/frontend.git'", text)
        self.assertNotIn("atonota-web.git", text)

    def test_jenkins_setup_notes_name_the_new_repositories(self):
        for name in JENKINSFILES:
            with self.subTest(name=name):
                text = (JENKINS / name).read_text(encoding="utf-8")
                self.assertNotIn("karacaismail/frappesetup", text)
                self.assertNotIn("karacaismail/atonota-web", text)


class ReleaseLabelTests(unittest.TestCase):
    def test_image_source_label_names_the_backend_repository(self):
        text = (ROOT / "deploy" / "bin" / "build-release").read_text(encoding="utf-8")
        self.assertIn("org.opencontainers.image.source=https://github.com/metafrappe/backend", text)
        self.assertNotIn("frappesetup", text)


class SecurityAuditRootTests(unittest.TestCase):
    def test_security_scripts_find_the_root_with_git(self):
        for relative in ("dev/bin/security-audit", "dev/security/history-scan"):
            with self.subTest(script=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn('cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"', text)
                self.assertNotIn("../../..", text)
                self.assertEqual(old_prefix_lines(text), [])


@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "needs a Git checkout")
class RepositoryPathTests(unittest.TestCase):
    def test_no_code_file_uses_the_old_prefix(self):
        command = ["git", "-C", str(ROOT), "grep", "-nE", r"(^|[^a-z_/.-])backend/", "--", *GREP_EXCLUDES]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        left = []
        for line in result.stdout.splitlines():
            path = line.split(":", 1)[0]
            if any(path == kept and (text is None or text in line) for kept, text, _ in KEPT):
                continue
            if any(text in line for text in KEPT_TEXT):
                continue
            left.append(line[:160])
        self.assertEqual(left, [], f"{len(left)} lines still use the backend/ prefix")

    def test_every_kept_line_still_exists(self):
        for path, text, _ in KEPT:
            with self.subTest(path=path, text=text):
                content = (ROOT / path).read_text(encoding="utf-8")
                self.assertTrue(text is None or text in content)


if __name__ == "__main__":
    unittest.main()


class StandardsFolderTests(unittest.TestCase):
    """The rule files sit in docs/standards/ (AJA-1526)."""

    RULE_FILES = (
        "ACIK-ISLER.md",
        "KARARLAR.md",
        "README.md",
        "SURECLER-VE-SONUCLAR.md",
        "frappe-python-disi-standartlari.md",
        "frappe-python-standartlari.md",
        "headless-frontend-standartlari.md",
        "mobile.md",
    )

    def test_decision_record_is_in_docs_standards(self):
        self.assertTrue((ROOT / "docs" / "standards" / "KARARLAR.md").is_file())

    def test_all_rule_files_are_in_docs_standards(self):
        for name in self.RULE_FILES:
            with self.subTest(name=name):
                self.assertTrue((ROOT / "docs" / "standards" / name).is_file())

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_code_files_do_not_name_the_old_folder(self):
        old = "docs/" + "standartlar"
        result = subprocess.run(
            ["git", "grep", "-n", old, "--", "*.py", "*.ts", "*.mjs", "*.json", "*.txt", "*.sh"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.stdout, "")


def standards_text(name):
    return (ROOT / "docs" / "standards" / name).read_text(encoding="utf-8")


class StandardsSyncTests(unittest.TestCase):
    """docs/standards/ matches the frappesetup backend branch before PR #64 (AJA-1672)."""

    def test_decision_record_has_decisions_43_and_44(self):
        text = standards_text("KARARLAR.md")
        self.assertIn("### Karar 43. GILT kuralları onaylandı", text)
        self.assertIn("### Karar 44. Varsayılan dil İngiliz İngilizcesi olacak", text)

    def test_naming_report_is_in_docs_standards(self):
        self.assertTrue((ROOT / "docs" / "standards" / "naming_rules_report.md").is_file())
        self.assertIn("(naming_rules_report.md)", standards_text("README.md"))


class StandardsPr64Tests(unittest.TestCase):
    """frappesetup PR #64: radius and security guides, Decisions 45 and 46 (AJA-1672)."""

    def test_radius_and_security_guides_are_in_docs_standards(self):
        for name in ("radius.md", "frappe-guvenlik-onlemleri.md"):
            with self.subTest(name=name):
                self.assertTrue((ROOT / "docs" / "standards" / name).is_file())
                self.assertIn(f"({name})", standards_text("README.md"))

    def test_decision_record_has_decisions_45_and_46(self):
        text = standards_text("KARARLAR.md")
        self.assertIn("### Karar 45. Köşe yuvarlaklığının tek kuralı radius.md yönergesidir", text)
        self.assertIn("### Karar 46. Güvenlik yönergesi depoda korunur", text)
