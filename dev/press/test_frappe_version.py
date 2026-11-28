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

    def test_frappe_build_does_not_mask_build_failures(self):
        # Frappe 16.56 imports every app's hooks after writing assets; Press hooks need a site.
        # Verify no app defines build hooks, run bundle + translations directly, and validate assets.json.
        install_path = PRESS_DEV / "install.sh"
        subprocess.run(["bash", "-n", str(install_path)], check=True, capture_output=True, text=True)
        install = install_path.read_text(encoding="utf-8")
        self.assertNotIn("|| test -f sites/assets/assets.json", install)
        self.assertNotRegex(install, r"bench build --app frappe\s*\|\|")

        hook_guard = re.search(
            r"grep -qE '\^\[\[:space:\]\]\*after_\(app_\)\?build\[\[:space:\]\]\*\(\\\+\?=|:\)'",
            install,
        )
        self.assertIsNotNone(hook_guard, "install.sh must guard against after_build/after_app_build hooks")
        self.assertIn("apps/*/*/hooks.py", install)

        bundle_step = re.search(
            r"\(cd sites && \.\./env/bin/python -c \".*frappe\.bundler import bundle; "
            r"bundle\('production', apps='frappe'\); "
            r"from frappe\.gettext\.translate import compile_translations; "
            r"compile_translations\('frappe'\)\"\)(?!\s*\|\|)",
            install,
        )
        self.assertIsNotNone(
            bundle_step,
            "install.sh must run frappe.bundler.bundle and compile_translations for frappe without masking errors",
        )

        manifest_check = re.search(
            r"env/bin/python -c \".*json\.load\(open\('sites/assets/assets\.json'.*'desk\.bundle\.js', 'desk\.bundle\.css'",
            install,
        )
        self.assertIsNotNone(
            manifest_check,
            "install.sh must validate sites/assets/assets.json as JSON containing desk bundles",
        )
        self.assertLess(hook_guard.start(), bundle_step.start())
        self.assertLess(bundle_step.start(), manifest_check.start())

    def test_documents_name_only_the_pinned_release(self):
        major, minor, patch = FRAPPE_VERSION.split(".")
        minor_release = f"{major}.{minor}"
        old = re.compile(
            rf"(?<![\d.]){re.escape(major)}\.(?!{re.escape(minor)}(?:\.{re.escape(patch)})?(?![\d.]))\d+(?:\.\d+)?"
        )
        for name in VERSIONED_FILES:
            with self.subTest(file=name):
                text = (PRESS_DEV / name).read_text(encoding="utf-8")
                self.assertIn(minor_release, text)
                self.assertEqual(
                    old.findall(text),
                    [],
                    f"{name} names another Frappe {major} release",
                )

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
