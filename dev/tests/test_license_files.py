"""Every platform part carries its own license file (G-118).

The owner chose MIT for code and CC BY 4.0 for content on 24 November 2026, the same as K-32.
Code that came from another project keeps its own license: Press extensions stay AGPL, HRMS
extensions stay GPL and Keycloak forks stay Apache 2.0. A part that mixes licenses lists them in
a NOTICE file. An empty template line such as "Copyright (c) [year] [fullname]" is no license
notice, so the test rejects it.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MIT = "MIT"
AGPL = "AGPL-3.0"
GPL = "GPL-3.0"
APACHE = "Apache-2.0"

# path -> (license file name, license, needs LICENSE-CONTENT, needs NOTICE)
# press_tr and hrms_tr keep their license until the orchestrator decides (G-118 handoff).
PARTS = {
    "apps/platform_core": ("license.txt", MIT, True, False),
    "apps/press_tr": ("license.txt", AGPL, False, False),
    "apps/hrms_tr": ("license.txt", GPL, False, False),
    "dev/mobile_test_app": ("license.txt", MIT, False, False),
    "identity/atonota_login": ("LICENSE", MIT, False, False),
    "identity/identity_sync": ("LICENSE", MIT, True, False),
    "identity/keycloak": ("LICENSE", MIT, True, True),
    "identity/keycloak/event-listener": ("LICENSE", APACHE, False, True),
    "identity/keycloak/magic-link-fork": ("LICENSE", APACHE, False, True),
    "libs/oidc_verify": ("LICENSE", MIT, False, False),
}

# Parts whose license is frozen pending a decision; they are not checked for LICENSE-CONTENT.
FROZEN = {"apps/press_tr", "apps/hrms_tr"}

PACKAGE_MARKERS = ("pyproject.toml", "pom.xml", "package.json")
SKIP_DIRS = {"node_modules", ".git", "fixtures", "dist", "target", ".venv"}

LICENSE_MARKERS = {
    MIT: "Permission is hereby granted, free of charge",
    AGPL: "GNU AFFERO GENERAL PUBLIC LICENSE",
    GPL: "GNU GENERAL PUBLIC LICENSE",
    APACHE: "Apache License\n                           Version 2.0",
}

# The GPL and Apache texts end with a "how to apply" appendix. Its brackets are part of the
# official text, so the placeholder search stops there.
APPENDIX = re.compile(r"APPENDIX: How to apply|How to Apply These Terms to Your New Programs")
PLACEHOLDER = re.compile(
    r"\[(?:year|yyyy|fullname|full name|name of copyright owner|owner)\]"
    r"|<(?:year|name of author|copyright holders?)>",
    re.I,
)
MIT_COPYRIGHT = re.compile(r"^Copyright \(c\) \d{4}(?:-\d{4})? \S.*$", re.M)
DOC_SUFFIXES = (".md",)
NOT_DOCS = {"README.md", "THIRD-PARTY-NOTICES.md"}


def _package_dirs():
    found = set()
    for marker in PACKAGE_MARKERS:
        for path in ROOT.rglob(marker):
            rel = path.parent.relative_to(ROOT)
            if SKIP_DIRS.intersection(rel.parts) or any(p.startswith(".") for p in rel.parts):
                continue
            found.add(rel.as_posix())
    return found


def _license_text(part):
    return (ROOT / part / PARTS[part][0]).read_text(encoding="utf-8")


def _has_documents(part):
    for path in (ROOT / part).rglob("*"):
        if SKIP_DIRS.intersection(path.relative_to(ROOT).parts):
            continue
        if path.suffix in DOC_SUFFIXES and path.name not in NOT_DOCS:
            return True
    return False


class LicenseFiles(unittest.TestCase):
    def test_every_package_folder_is_listed(self):
        missing = sorted(_package_dirs() - set(PARTS))
        self.assertEqual(missing, [], "add new parts to PARTS with their license")

    def test_every_part_has_its_license_file(self):
        for part, (name, _, _, _) in PARTS.items():
            with self.subTest(part=part):
                self.assertTrue((ROOT / part / name).is_file(), f"{part}/{name}")

    def test_license_file_matches_the_expected_license(self):
        for part, (_, spdx, _, _) in PARTS.items():
            with self.subTest(part=part):
                self.assertIn(LICENSE_MARKERS[spdx], _license_text(part))
                if spdx == GPL:
                    self.assertNotIn(LICENSE_MARKERS[AGPL], _license_text(part))

    def test_license_files_have_no_template_placeholders(self):
        files = [ROOT / part / spec[0] for part, spec in PARTS.items()]
        files += [ROOT / part / "NOTICE" for part, spec in PARTS.items() if spec[3]]
        for path in files:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                text = path.read_text(encoding="utf-8")
                text = APPENDIX.split(text, maxsplit=1)[0]
                self.assertEqual(PLACEHOLDER.findall(text), [])

    def test_mit_files_name_a_copyright_holder(self):
        for part, (_, spdx, _, _) in PARTS.items():
            if spdx != MIT:
                continue
            with self.subTest(part=part):
                self.assertRegex(_license_text(part), MIT_COPYRIGHT)

    def test_parts_with_documents_carry_the_content_license(self):
        for part, (_, _, needs_content, _) in PARTS.items():
            if part in FROZEN:
                continue
            with self.subTest(part=part):
                self.assertEqual(_has_documents(part), needs_content, "PARTS content flag")
                path = ROOT / part / "LICENSE-CONTENT"
                self.assertEqual(path.is_file(), needs_content)
                if needs_content:
                    text = path.read_text(encoding="utf-8")
                    self.assertIn("Attribution 4.0 International", text)
                    self.assertIn("creativecommons.org/licenses/by/4.0", text)

    def test_mixed_parts_have_a_notice(self):
        for part, (_, _, _, needs_notice) in PARTS.items():
            if needs_notice:
                with self.subTest(part=part):
                    self.assertTrue((ROOT / part / "NOTICE").is_file())

    def test_keycloak_notice_names_every_foreign_source(self):
        notice = (ROOT / "identity/keycloak/NOTICE").read_text(encoding="utf-8")
        for needle in (
            "event-listener/",
            "magic-link-fork/",
            "Apache License, Version 2.0",
            "keycloak.v2",
            "SIL Open Font License",
            "SecLists",
            "Copyright (c) 2018 Daniel Miessler",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, notice)

    def test_magic_link_fork_keeps_the_upstream_copyright(self):
        text = _license_text("identity/keycloak/magic-link-fork")
        self.assertIn("Copyright 2025 Cloudflight GmbH", text)


if __name__ == "__main__":
    unittest.main()
