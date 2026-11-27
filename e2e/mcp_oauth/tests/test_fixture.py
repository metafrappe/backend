"""Isolated MCP OAuth fixture helpers; no Docker or live service is used here."""

import contextlib
import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography import x509

SCRIPT = Path(__file__).resolve().parents[1] / "fixture.py"
SPEC = importlib.util.spec_from_file_location("mcp_oauth_fixture", SCRIPT)
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)

REPO = Path(__file__).resolve().parents[3]


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class StateDirectoryTests(unittest.TestCase):
    def test_rejects_directory_inside_repository(self):
        with self.assertRaises(SystemExit):
            fixture.state_dir({"MCP_FIXTURE_DIR": str(REPO / "e2e/mcp_oauth/state")})

    def test_rejects_relative_directory(self):
        with self.assertRaises(SystemExit):
            fixture.state_dir({"MCP_FIXTURE_DIR": "state"})

    def test_default_directory_is_outside_repository(self):
        path = fixture.state_dir({"HOME": "/home/example"})
        self.assertEqual(path, Path("/home/example/.cache/frappesetup/mcp-oauth-fixture"))


class RealmTests(unittest.TestCase):
    def setUp(self):
        self.source = (REPO / "identity/keycloak/realm/platform-realm.json").read_text()
        self.values = fixture.new_values()
        self.realm = fixture.build_realm(self.source, self.values)

    def test_only_mcp_clients_are_enabled_for_the_resource(self):
        clients = {c["clientId"]: c for c in self.realm["clients"]}
        for client_id in ["mcp-external", "mcp-resource", fixture.RESOURCE]:
            self.assertTrue(clients[client_id]["enabled"], client_id)

    def test_external_delivery_is_disabled(self):
        self.assertEqual(self.realm["identityProviders"], [])
        self.assertEqual(self.realm["eventsListeners"], [])
        self.assertEqual(self.realm["smtpServer"], {})

    def test_keycloak_message_keys_are_kept(self):
        text = json.dumps(self.realm)
        self.assertIn("${profileScopeConsentText}", text)
        self.assertNotIn("${ATONOTA_", text)

    def test_introspection_secret_is_bound_to_the_resource_client(self):
        clients = {c["clientId"]: c for c in self.realm["clients"]}
        self.assertEqual(clients[fixture.RESOURCE]["secret"], self.values["introspection_secret"])

    def test_sample_account_matches_client_rules(self):
        (user,) = self.realm["users"]
        self.assertTrue(user["username"].startswith("mcp-e2e-"))
        self.assertTrue(user["username"].endswith("@example.test"))
        self.assertEqual(user["id"], self.values["subject"])
        self.assertEqual(user["requiredActions"], [])
        self.assertFalse(user["credentials"][0]["temporary"])


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            fixture.prepare(self.dir, REPO, {})
        return out.getvalue()

    def test_secret_files_are_private_and_not_printed(self):
        output = self.prepare()
        data = json.loads((self.dir / "fixture.json").read_text())
        for name in ["fixture.json", "local.key", "compose.json", "platform-realm.json"]:
            self.assertEqual(mode(self.dir / name), 0o600, name)
        self.assertEqual(mode(self.dir), 0o700)
        for key in fixture.SECRET_KEYS:
            self.assertNotIn(data[key], output)

    def test_prepare_never_overwrites_existing_secrets(self):
        self.prepare()
        before = (self.dir / "fixture.json").read_text()
        with self.assertRaises(SystemExit):
            self.prepare()
        self.assertEqual((self.dir / "fixture.json").read_text(), before)

    def test_certificate_names_both_local_hosts(self):
        self.prepare()
        cert = x509.load_pem_x509_certificate((self.dir / "local.crt").read_bytes())
        names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        self.assertEqual(
            set(names.get_values_for_type(x509.DNSName)),
            {"identity.localhost", "tenant1.localhost"},
        )

    def test_compose_publishes_only_loopback_ports_and_keeps_secrets_out_of_commands(self):
        self.prepare()
        data = json.loads((self.dir / "fixture.json").read_text())
        compose = json.loads((self.dir / "compose.json").read_text())
        self.assertEqual(compose["name"], fixture.PROJECT)
        ports = [p for s in compose["services"].values() for p in s.get("ports", [])]
        self.assertEqual(sorted(ports), ["127.0.0.1:7840:7840", "127.0.0.1:7841:7841"])
        commands = json.dumps([s.get("command") for s in compose["services"].values()])
        for key in fixture.SECRET_KEYS:
            self.assertNotIn(data[key], commands)

    def test_network_uses_a_fixed_private_subnet(self):
        # Docker's default address pools are exhausted on this machine.
        self.prepare()
        compose = json.loads((self.dir / "compose.json").read_text())
        (subnet,) = compose["networks"]["default"]["ipam"]["config"]
        self.assertEqual(subnet, {"subnet": fixture.DEFAULT_SUBNET})

    def test_invalid_subnet_is_refused(self):
        with self.assertRaises(SystemExit):
            fixture.prepare(self.dir, REPO, {"MCP_FIXTURE_SUBNET": "10.0.0.0/8; rm"})
        self.assertFalse((self.dir / "fixture.json").exists())

    def test_password_file_prints_only_the_path(self):
        self.prepare()
        data = json.loads((self.dir / "fixture.json").read_text())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            fixture.main(["password-file"], {"MCP_FIXTURE_DIR": str(self.dir)})
        self.assertEqual(out.getvalue().strip(), str(self.dir / "fixture.json"))
        self.assertNotIn(data["password"], out.getvalue())


class SiteConfigTests(unittest.TestCase):
    def test_site_config_matches_client_documentation(self):
        values = fixture.new_values()
        conf = fixture.site_config(values)
        self.assertEqual(conf["mcp_oauth_resource"], fixture.RESOURCE)
        self.assertEqual(conf["mcp_oauth_client_ids"], ["mcp-external"])
        self.assertEqual(conf["mcp_oauth_introspection_secret"], values["introspection_secret"])
        self.assertEqual(conf["keycloak_realm"], "platform")


class LockTests(unittest.TestCase):
    def test_second_holder_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp-oauth.lock"
            with fixture.test_lock(path, "AJA-1"):
                with self.assertRaises(SystemExit) as refused:
                    with fixture.test_lock(path, "AJA-2"):
                        pass
                self.assertIn("AJA-1", str(refused.exception))
            with fixture.test_lock(path, "AJA-2"):
                pass

    def test_owner_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                fixture.main(["lock", "--", "true"], {"MCP_FIXTURE_LOCK": str(Path(tmp) / "x.lock")})


class SafetyTests(unittest.TestCase):
    def test_never_pulls_or_uses_the_shared_stack_project(self):
        self.assertFalse(fixture.PROJECT.startswith("fs-e2e-"))
        self.assertIn("--pull", fixture.compose_create_args())
        self.assertIn("never", fixture.compose_create_args())

    def test_up_refuses_when_ports_are_taken(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                fixture.prepare(Path(tmp) / "s", REPO, {})
            with (
                patch.object(fixture, "running_containers", return_value=[]),
                patch.object(fixture, "port_owners", return_value=["fs-aja57-oauth-keycloak-1"]),
                patch.object(fixture, "docker") as docker,
            ):
                with self.assertRaises(SystemExit):
                    fixture.up(Path(tmp) / "s", REPO, os.environ)
                docker.assert_not_called()


class UpOrderTests(unittest.TestCase):
    def test_keycloak_data_volume_is_owned_by_keycloak_before_start(self):
        # A fresh named volume is root-owned; Keycloak (uid 1000) then cannot open its H2 file.
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "s"
            with contextlib.redirect_stdout(io.StringIO()):
                fixture.prepare(directory, REPO, {})
                with (
                    patch.object(fixture, "running_containers", return_value=[]),
                    patch.object(fixture, "port_owners", return_value=[]),
                    patch.object(fixture, "compose", side_effect=lambda env, d, *a, **k: calls.append(a)),
                    patch.object(fixture, "docker", return_value=SimpleNamespace(returncode=0)),
                    patch.object(fixture, "copy_in"),
                    patch.object(fixture, "open_tunnel"),
                    patch.object(fixture, "wait_https"),
                ):
                    fixture.up(directory, REPO, {})
        chown = [i for i, a in enumerate(calls) if "chown" in a]
        start = calls.index(("start",))
        self.assertEqual(len(chown), 1)
        self.assertLess(chown[0], start)
        self.assertIn("/opt/keycloak/data/h2", calls[chown[0]])
        self.assertIn("never", calls[chown[0]])


if __name__ == "__main__":
    unittest.main()
