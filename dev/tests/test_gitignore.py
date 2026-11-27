"""Root .gitignore keeps secret environment files out of the public repository (AJA-1649)."""

import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GIT = shutil.which("git")


def git(*arguments):
    # GIT_* variables could point the check at another repository.
    clean = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(
        [GIT, "-C", str(ROOT), *arguments],
        env=clean,
        capture_output=True,
        text=True,
        check=False,
    )


def ignored(path):
    # --no-index also reports paths that are already tracked.
    return git("check-ignore", "-q", "--no-index", "--", path).returncode == 0


@unittest.skipUnless(GIT, "git is required")
class GitignoreTest(unittest.TestCase):
    def test_root_gitignore_exists(self):
        self.assertTrue((ROOT / ".gitignore").is_file())

    def test_secret_environment_files_are_ignored(self):
        for path in (
            ".env",
            ".env.production",
            ".env.local",
            "local.env",
            "e2e/.env",
            "e2e/.env.production",
            "deploy/settings/press.production.env",
            "identity/keycloak/secrets.env",
            "e2e/.fs-stack-env.0123456789abcdef.tmp",
        ):
            with self.subTest(path=path):
                self.assertTrue(ignored(path), f"{path} must be ignored by Git")

    def test_templates_and_near_misses_stay_visible(self):
        for path in (
            ".env.example",
            "dev/.env.example",
            "deploy/settings/press.production.env.example",
            # e2e/stack tests use these names as paths Git does not ignore.
            "e2e/stack-candidate.env",
            "e2e/.env.tmp-review.md",
            "e2e/.fs-stack-env.notes.tmp",
            "e2e/docs/.fs-stack-env.0123456789abcdef.tmp",
        ):
            with self.subTest(path=path):
                self.assertFalse(ignored(path), f"{path} must not be ignored by Git")

    def test_no_tracked_file_is_ignored(self):
        result = git("ls-files", "-ci", "--exclude-standard")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "", "tracked files became ignored")


if __name__ == "__main__":
    unittest.main()
