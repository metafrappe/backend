"""The PDF renderer runs in its own isolated container (G-146, G-51, AJA-2285).

G-146 asks that the PDF renderer of G-51 runs in a separate container with a read-only file
system and a restricted network. The renderer is a headless Chrome. Frappe reaches it with the
site setting "chromium_websocket_url" instead of starting Chrome inside the tenant container.
The renderer joins only the network "pdf-render". That network has no gateway ("internal: true"),
so the renderer cannot reach the internet, the database, Redis or Keycloak. Only the tenant
services that make PDFs share the network with it.
The service sits behind the profile "pdf-renderer". remote/apply never turns that profile on, so
this change starts nothing on a server.
"""

import re
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]
STACK = DEPLOY / "compose" / "stack.yaml"
APPLY = DEPLOY / "remote" / "apply"
RENDERER = "pdf-renderer"
NETWORK = "pdf-render"
# Services that make PDFs: the web process (print view, download) and the queue worker.
PDF_CLIENTS = {"tenant-web", "tenant-worker"}


def top_level(text: str, section: str) -> str:
    """Returns the body of one top level key such as "services:" or "networks:"."""
    found = re.search(rf"^{section}:\n(.*?)(?=^\S|\Z)", text, re.M | re.S)
    if not found:
        raise AssertionError(f"top level key {section} missing")
    return found.group(1)


def entries(body: str) -> dict[str, str]:
    """Splits a top level body into its two-space entries."""
    names = list(re.finditer(r"^  ([a-z][a-z0-9-]*):(.*)\n", body, re.M))
    blocks = {}
    for index, match in enumerate(names):
        end = names[index + 1].start() if index + 1 < len(names) else len(body)
        blocks[match.group(1)] = match.group(2) + "\n" + body[match.end():end]
    return blocks


def key_lines(block: str, key: str) -> list[str]:
    """Returns a four-space key as one flow value or as its list items."""
    found = re.search(rf"(?m)^    {key}:(.*)\n((?:      .*\n)*)", block)
    if not found:
        return []
    inline = found.group(1).strip()
    if inline:
        return [inline]
    return [line.strip() for line in found.group(2).splitlines() if line.strip()]


def service_networks(block: str, anchors: dict[str, str]) -> set[str]:
    """Network names of a service, following one "<<: *anchor" merge."""
    lines = key_lines(block, "networks")
    if not lines:
        merge = re.search(r"(?m)^    <<: \*(\S+)", block)
        if merge:
            lines = key_lines(("\n" + anchors[merge.group(1)]).replace("\n  ", "\n    "), "networks")
    names = set()
    for line in lines:
        if line.startswith("["):
            names.update(part.strip() for part in line.strip("[]").split(",") if part.strip())
        else:
            names.add(re.sub(r"^- ", "", line).split(":")[0].strip())
    return names


class PdfRendererIsolationTest(unittest.TestCase):
    def setUp(self):
        self.stack = STACK.read_text(encoding="utf-8")
        self.services = entries(top_level(self.stack, "services"))
        self.networks = entries(top_level(self.stack, "networks"))
        self.anchors = dict(re.findall(r"(?ms)^x-[a-z-]+: &(\S+)\n(.*?)(?=^\S|\Z)", self.stack))
        if RENDERER not in self.services:
            self.fail("the PDF renderer must be its own compose service")
        self.renderer = self.services[RENDERER]

    def test_renderer_is_a_separate_container(self):
        # Its own image, not the tenant or Press anchor that carries the bench and its secrets.
        self.assertNotRegex(self.renderer, r"(?m)^    <<:")
        self.assertRegex(self.renderer, r"(?m)^    image: \$\{ATONOTA_IMAGE_PDF_RENDERER")
        self.assertNotRegex(self.renderer, r"(?m)^    env_file:")

    def test_file_system_is_read_only(self):
        self.assertRegex(self.renderer, r"(?m)^    read_only: true$")
        # Chrome writes only to memory. No volume or host path is mounted.
        self.assertNotRegex(self.renderer, r"(?m)^    volumes:")
        tmpfs = key_lines(self.renderer, "tmpfs")
        self.assertTrue(tmpfs, "Chrome needs a tmpfs for /tmp")
        for line in tmpfs:
            self.assertRegex(line, r"noexec", line)

    def test_process_has_no_extra_privileges(self):
        self.assertEqual(key_lines(self.renderer, "cap_drop"), ["[ALL]"])
        self.assertNotRegex(self.renderer, r"(?m)^    (cap_add|privileged|devices):")
        self.assertIn("no-new-privileges:true", " ".join(key_lines(self.renderer, "security_opt")))
        self.assertRegex(self.renderer, r"(?m)^    user: \"?\d+:\d+\"?$")

    def test_network_is_restricted(self):
        self.assertEqual(service_networks(self.renderer, self.anchors), {NETWORK})
        self.assertNotRegex(self.renderer, r"(?m)^    (ports|expose|network_mode|extra_hosts|dns):")
        self.assertIn(NETWORK, self.networks)
        # "internal: true" gives the network no gateway, so no route leaves the host.
        self.assertRegex(self.networks[NETWORK], r"internal: true")

    def test_only_pdf_clients_share_the_renderer_network(self):
        members = {
            name for name, block in self.services.items()
            if NETWORK in service_networks(block, self.anchors)
        }
        self.assertEqual(members, PDF_CLIENTS | {RENDERER})

    def test_service_is_off_until_turned_on(self):
        # remote/apply writes COMPOSE_PROFILES itself and never adds this profile.
        self.assertEqual(key_lines(self.renderer, "profiles"), [f"[{RENDERER}]"])
        self.assertNotIn(RENDERER, APPLY.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
