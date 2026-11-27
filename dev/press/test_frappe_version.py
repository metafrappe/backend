"""Keep the disposable Press bench on the Frappe release used by the Press image."""

import os
import re
import subprocess
import unittest
from pathlib import Path

PRESS_DEV = Path(__file__).resolve().parent
FRAPPE_VERSION = "16.56.0"
# `git ls-remote https://github.com/frappe/frappe.git refs/tags/v16.56.0`
FRAPPE_COMMIT = "49789a1711d4dde2be9c6888efe35651465f4b64"
VERSIONED_FILES = (
    "install.sh",
    "README.md",
    "create_site.py",
    "uv-overrides.txt",
    "rpc-rate-limit-compatibility.md",
)


class FrappeVersionTest(unittest.TestCase):
    def test_install_pins_the_release_tag_and_commit(self):
        install = (PRESS_DEV / "install.sh").read_text(encoding="utf-8")
        self.assertRegex(install, rf"--frappe-branch v{re.escape(FRAPPE_VERSION)}\s")
        self.assertIn(
            f'test "$(git -C apps/frappe rev-parse HEAD)" = {FRAPPE_COMMIT}',
            install.splitlines(),
        )

    def test_frappe_build_survives_site_less_press_hooks(self):
        # Frappe 16.56 imports every app's hooks after it writes the assets.
        # Press hooks need a site, so the installer must check the asset manifest instead.
        install = (PRESS_DEV / "install.sh").read_text(encoding="utf-8").splitlines()
        self.assertIn("bench build --app frappe || test -f sites/assets/assets.json", install)

    def test_documents_name_only_the_pinned_release(self):
        old = re.compile(r"(?<![\d.])16\.(?!56(?:\.0)?(?![\d.]))\d+(?:\.\d+)?")
        for name in VERSIONED_FILES:
            with self.subTest(file=name):
                text = (PRESS_DEV / name).read_text(encoding="utf-8")
                self.assertIn("16.56", text)
                self.assertEqual(old.findall(text), [], f"{name} names another Frappe 16 release")

    @unittest.skipUnless(
        os.environ.get("PRESS_TEST_COMPOSE_PROJECT"), "Set PRESS_TEST_COMPOSE_PROJECT for the live bench"
    )
    def test_running_bench_uses_the_pinned_release(self):
        context = {"factory": "colima-factory", "default": "colima"}[os.environ.get("FS_COLIMA_PROFILE", "factory")]
        project = os.environ["PRESS_TEST_COMPOSE_PROJECT"]
        container = subprocess.run(
            [
                "docker", "--context", context, "ps", "-q",
                "--filter", f"label=com.docker.compose.project={project}",
                "--filter", "label=com.docker.compose.service=web",
                "--filter", "label=com.docker.compose.oneoff=False",
            ],
            check=True, capture_output=True, text=True,
        ).stdout.split()
        self.assertEqual(len(container), 1, "Expected exactly one running Press web service")
        version = subprocess.run(
            [
                "docker", "--context", context, "exec", container[0],
                "/home/frappe/benches/frappe-bench/env/bin/python", "-c",
                "import frappe; print(frappe.__version__)",
            ],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(version, FRAPPE_VERSION)


if __name__ == "__main__":
    unittest.main()
