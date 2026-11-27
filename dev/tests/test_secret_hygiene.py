"""Secret hygiene checks (G-112, AJA-2288).

Three parts:
- Every app runs the gitleaks pre-commit hook. The hook catches a fake secret in a staged file.
  The hook is connected through the repository hook that the personal author guard calls first;
  `core.hooksPath` never changes.
- The server environment file uses sops with age. The example file is encrypted and no private
  age key is in the repository.
- The 90 day key rotation guide names every key in the encrypted example.
Design: docs/dagitim/secrets.md.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SECURITY = BACKEND / "dev" / "security"
SOPS_CONFIG = BACKEND / ".sops.yaml"
SECRETS = BACKEND / "deploy" / "secrets"
EXAMPLE = SECRETS / "example.sops.env"
GUIDE = BACKEND / "docs" / "dagitim" / "secrets.md"
INSTALL_HOOK = BACKEND / "dev" / "bin" / "install-secret-hook"

# Upstream gitleaks .pre-commit-hooks.yaml, hook id "gitleaks", tag v8.30.1.
HOOK_REPO = "https://github.com/gitleaks/gitleaks"
HOOK_ENTRY = "gitleaks git --pre-commit --redact --staged --verbose"
AGE_RECIPIENT = re.compile(r"age1[02-9ac-hj-np-z]{58}")
B64 = r"[A-Za-z0-9+/=]+"
ENCRYPTED_VALUE = re.compile(rf"ENC\[AES256_GCM,data:{B64},iv:{B64},tag:{B64},type:str\]")
ROTATED_KEYS = ("IYZICO_API_KEY", "IYZICO_SECRET_KEY", "MODEL_PROVIDER_API_KEY", "SMTP_PASSWORD")


def tool_versions():
    values = {}
    for line in (SECURITY / "tool-versions.env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def repo_blocks(config_text):
    """Split a pre-commit config into its `- repo:` blocks (no YAML library in the gate)."""
    blocks = re.split(r"^\s*- repo:\s*", config_text, flags=re.M)[1:]
    return [block.split("\n", 1) for block in blocks]


class GitleaksHookTests(unittest.TestCase):
    def app_configs(self):
        configs = sorted(BACKEND.glob("apps/*/.pre-commit-config.yaml"))
        self.assertTrue(configs, "no app pre-commit config found")
        return configs

    def test_every_app_config_runs_pinned_gitleaks(self):
        version = tool_versions()["GITLEAKS_VERSION"]
        for config in self.app_configs():
            with self.subTest(config=config.relative_to(BACKEND).as_posix()):
                matches = [body for url, *body in repo_blocks(config.read_text()) if url.strip() == HOOK_REPO]
                self.assertEqual(len(matches), 1, "gitleaks repo must appear exactly once")
                body = matches[0][0] if matches[0] else ""
                self.assertRegex(
                    body,
                    rf"(?m)^\s*rev:\s*v{re.escape(version)}\s*$",
                    "hook version must match dev/security/tool-versions.env",
                )
                self.assertRegex(body, r"(?m)^\s*- id:\s*gitleaks\s*$")

    def docker_or_skip(self):
        if shutil.which("docker") is None:
            self.skipTest("docker CLI not found; the hook run needs the pinned gitleaks image")

    def run_in_gitleaks_image(self, script):
        """Run a shell script in the pinned gitleaks image with the security gate's container flags."""
        command = [
            "bash",
            "-c",
            'source "$1"; "${docker_command[@]}" image inspect "$gitleaks_image" >/dev/null 2>&1 '
            '|| { echo "missing image: $gitleaks_image" >&2; exit 125; }; '
            'exec "${docker_command[@]}" run "${container_flags[@]}" "$gitleaks_image" -es',
            "run",
            str(SECURITY / "container-settings"),
        ]
        return subprocess.run(command, input=script, capture_output=True, text=True, timeout=300)

    def test_hook_entry_catches_fake_secret_and_passes_clean_change(self):
        self.docker_or_skip()
        # The fake key is built from two halves so this file itself does not hold a secret.
        script = f"""
set +e -u
repo=$(mktemp -d /tmp/hook.XXXXXX)
git init --quiet "$repo"
cd "$repo"
printf 'greeting = "hello"\\n' > clean.py
git add clean.py
{HOOK_ENTRY} >/tmp/clean.log 2>&1
echo "clean=$?"
printf 'api_key = "%s%s"\\n' Zt4Wq9LmB2xR k7Pv3Nc8Hs5Dj6Fa > leak.py
git add leak.py
{HOOK_ENTRY} >/tmp/leak.log 2>&1
echo "leak=$?"
grep -c 'generic-api-key' /tmp/leak.log || true
grep -c 'k7Pv3Nc8Hs5Dj6Fa' /tmp/leak.log || true
"""
        result = self.run_in_gitleaks_image(script)
        if result.returncode == 125:
            self.fail(
                f"{result.stderr.strip()}. Pull it once with the pinned digest from "
                "dev/security/tool-versions.env."
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.split()
        self.assertEqual(lines[0], "clean=0", "a clean staged change must pass")
        self.assertEqual(lines[1], "leak=1", "a staged fake secret must stop the commit")
        self.assertNotEqual(lines[2], "0", "the finding must name the generic-api-key rule")
        self.assertEqual(lines[3], "0", "the hook output must redact the secret")


class InstallHookTests(unittest.TestCase):
    def make_repo(self, root):
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)
        # A stand-in for the personal author guard: a hooks path outside the repository.
        guard = root / "guard"
        guard.mkdir()
        config = ["git", "-C", str(root), "config", "--local"]
        subprocess.run([*config, "core.hooksPath", str(guard)], check=True)
        return guard

    def install(self, root):
        return subprocess.run([str(INSTALL_HOOK)], cwd=root, capture_output=True, text=True, timeout=60)

    def test_installs_repository_hook_and_keeps_hooks_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guard = self.make_repo(root)
            result = self.install(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            hook = root / ".git" / "hooks" / "pre-commit"
            self.assertTrue(os.access(hook, os.X_OK), "repository pre-commit hook must be executable")
            text = hook.read_text()
            self.assertIn("pre-commit run gitleaks", text)
            self.assertIn("apps/platform_core/.pre-commit-config.yaml", text)
            hooks_path = subprocess.run(
                ["git", "-C", str(root), "config", "core.hooksPath"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(hooks_path, str(guard), "core.hooksPath must not change")
            self.assertEqual(list(guard.iterdir()), [], "the guard directory must not change")
            self.assertEqual(self.install(root).returncode, 0, "a second run must be harmless")

    def test_refuses_to_replace_a_foreign_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_repo(root)
            hook = root / ".git" / "hooks" / "pre-commit"
            hook.parent.mkdir(parents=True, exist_ok=True)
            hook.write_text("#!/bin/sh\nexit 0\n")
            result = self.install(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(hook.read_text(), "#!/bin/sh\nexit 0\n")


class SopsTests(unittest.TestCase):
    def rules(self):
        text = SOPS_CONFIG.read_text()
        self.assertRegex(text, r"(?m)^creation_rules:\s*$")
        return re.findall(r"(?m)^\s*- path_regex:\s*(\S+)\s*\n\s*age:\s*(\S+)\s*$", text)

    def test_config_encrypts_server_environment_files_with_age(self):
        rules = self.rules()
        self.assertTrue(rules, "creation_rules needs a path_regex and an age recipient")
        for path_regex, recipients in rules:
            with self.subTest(path_regex=path_regex):
                pattern = re.compile(path_regex.strip("'\""))
                self.assertTrue(pattern.search("deploy/secrets/example.sops.env"))
                self.assertTrue(pattern.search("deploy/secrets/prod.sops.env"))
                self.assertFalse(pattern.search("deploy/settings/tenant.production.env.example"))
                for recipient in recipients.strip("'\"").split(","):
                    self.assertRegex(recipient, rf"^{AGE_RECIPIENT.pattern}$")

    def test_example_is_encrypted_for_the_configured_recipient(self):
        lines = [line for line in EXAMPLE.read_text().splitlines() if line and not line.startswith("#")]
        values = dict(line.split("=", 1) for line in lines)
        data = {key: value for key, value in values.items() if not key.startswith("sops_")}
        self.assertEqual(sorted(data), sorted(ROTATED_KEYS))
        for key, value in data.items():
            with self.subTest(key=key):
                self.assertRegex(value, rf"^{ENCRYPTED_VALUE.pattern}$", "value must be encrypted")
        self.assertRegex(values.get("sops_mac", ""), r"^ENC\[AES256_GCM,")
        self.assertIn("sops_version", values)
        configured = {r for _, rs in self.rules() for r in rs.strip("'\"").split(",")}
        self.assertEqual(values.get("sops_age__list_0__map_recipient"), next(iter(configured)))

    def test_every_secrets_file_is_sops_encrypted(self):
        files = sorted(p for p in SECRETS.iterdir() if p.is_file() and p.name != "README.md")
        self.assertEqual(files, sorted(SECRETS.glob("*.sops.env")), "plain files do not belong here")
        for path in files:
            with self.subTest(path=path.name):
                self.assertIn("sops_mac=ENC[", path.read_text())

    def test_no_private_age_key_is_tracked(self):
        tracked = subprocess.run(
            ["git", "-C", str(BACKEND), "grep", "-l", "-I", "AGE-SECRET-KEY-1"],
            capture_output=True,
            text=True,
        )
        # This test file and the guide only name the prefix; any other hit is a real key.
        hits = {line for line in tracked.stdout.splitlines()} - {
            "dev/tests/test_secret_hygiene.py",
            "docs/dagitim/secrets.md",
        }
        self.assertEqual(hits, set(), "a private age key is tracked")

    def test_sops_reports_example_as_encrypted_when_installed(self):
        sops = shutil.which("sops")
        if sops is None:
            self.skipTest("sops not installed; the structure tests above still run")
        result = subprocess.run(
            [sops, "filestatus", "--input-type", "dotenv", str(EXAMPLE)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"encrypted":true', result.stdout.replace(" ", ""))


class RotationGuideTests(unittest.TestCase):
    def test_guide_names_every_key_and_the_90_day_period(self):
        text = GUIDE.read_text()
        self.assertIn("90 gün", text)
        for key in ROTATED_KEYS:
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", text)
        for provider in ("iyzico", "SMTP", "model sağlayıcı"):
            with self.subTest(provider=provider):
                self.assertIn(provider, text)


if __name__ == "__main__":
    unittest.main()
