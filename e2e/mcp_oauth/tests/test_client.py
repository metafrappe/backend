"""Local runner boundaries; no live services are used by these tests."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import httpx
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "client.py"
SPEC = importlib.util.spec_from_file_location("mcp_oauth_client", SCRIPT)
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


class LocalDestinationTests(unittest.TestCase):
    def test_accepts_verified_local_tls(self):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 7841))]):
            self.assertEqual(
                client.validate_local_url("https://tenant1.localhost:7841/mcp"),
                "https://tenant1.localhost:7841/mcp",
            )

    def test_rejects_remote_or_ambiguous_destinations_before_authentication(self):
        urls = [
            "https://example.com/mcp",
            "http://127.0.0.1/mcp",
            "https://user@localhost/mcp",
            "https://localhost/mcp#fragment",
            "https://localhost/mcp?access_token=example",
            "https://localhost:0/mcp",
        ]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                client.validate_local_url(url)

    def test_local_hostname_must_resolve_only_to_loopback(self):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("192.0.2.2", 443))]):
            with self.assertRaises(ValueError):
                client.validate_local_url("https://identity.localhost/realms/platform")


class DiscoveryTests(unittest.TestCase):
    def test_resource_and_issuer_must_match_the_operator_configuration(self):
        resource = "https://tenant1.localhost:7841/mcp"
        issuer = "https://identity.localhost:7840/realms/platform"
        good = {
            "resource": resource,
            "authorization_servers": [issuer],
            "scopes_supported": ["mcp"],
            "bearer_methods_supported": ["header"],
        }
        client.validate_discovery(good, resource, issuer)
        for change in [
            {"resource": resource + "/other"},
            {"authorization_servers": ["https://other.example.test"]},
            {"scopes_supported": []},
            {"bearer_methods_supported": ["query"]},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                client.validate_discovery({**good, **change}, resource, issuer)


class FixtureBrowserTests(unittest.IsolatedAsyncioTestCase):
    issuer = "https://identity.localhost:7840/realms/platform"
    callback = "http://127.0.0.1:7842/callback"

    def browser(self, http):
        return client.FixtureBrowser(
            http, self.issuer, self.callback, "mcp-e2e-reader@example.test", "fixture-only"
        )

    async def test_password_then_consent_then_callback(self):
        requests = []

        def respond(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(
                    200,
                    text='<form id="kc-form-login" action="'
                    + self.issuer
                    + '/login-actions/authenticate"></form>',
                )
            if len(requests) == 2:
                self.assertIn(b"username=mcp-e2e-reader", request.content)
                return httpx.Response(
                    200,
                    text='<form action="'
                    + self.issuer
                    + '/login-actions/consent"><input type="hidden" name="code" '
                    'value="consent-code"></form>',
                )
            self.assertIn(b"accept=true", request.content)
            return httpx.Response(302, headers={"Location": self.callback + "?code=auth-code&state=state"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            browser = self.browser(http)
            await browser.redirect(self.issuer + "/protocol/openid-connect/auth")
            self.assertEqual(await browser.callback(), ("auth-code", "state"))
        self.assertEqual(len(requests), 3)

    async def test_never_posts_credentials_to_a_different_origin(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(
                200, text='<form id="kc-form-login" action="https://outside.example.test/steal"></form>'
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            with self.assertRaises(ValueError):
                await self.browser(http).redirect(self.issuer + "/protocol/openid-connect/auth")
        self.assertEqual(len(requests), 1)

    async def test_repeated_login_form_does_not_retry_a_rejected_password(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(
                200,
                text='<form id="kc-form-login" action="'
                + self.issuer
                + '/login-actions/authenticate"></form>',
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            with self.assertRaises(ValueError):
                await self.browser(http).redirect(self.issuer + "/protocol/openid-connect/auth")
        self.assertEqual(len(requests), 2, "One GET and exactly one password POST are allowed")

    async def test_rejects_wrong_callback_and_duplicate_code(self):
        for location in [
            self.callback + "-wrong?code=x&state=y",
            self.callback + "?code=x&code=z&state=y",
            self.callback + "?code=x",
            self.callback + "?error=access_denied&state=y",
        ]:
            with self.subTest(location=location):
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda request: httpx.Response(302, headers={"Location": location})
                    )
                ) as http:
                    with self.assertRaises(ValueError):
                        await self.browser(http).redirect(self.issuer + "/protocol/openid-connect/auth")

    async def test_only_synthetic_test_accounts_are_allowed(self):
        async with httpx.AsyncClient() as http:
            with self.assertRaises(ValueError):
                client.FixtureBrowser(http, self.issuer, self.callback, "person@example.org", "unused")


class DiscoveryBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_cannot_exchange_a_code_at_another_realm(self):
        """Drive the public runner far enough to capture its HTTP request boundary."""
        captured = []
        real_client = httpx.AsyncClient

        def factory(**options):
            captured.append(options["event_hooks"]["request"][0])
            return real_client(transport=httpx.MockTransport(lambda request: httpx.Response(401)))

        args = SimpleNamespace(
            resource="https://tenant1.localhost:7841" + client.MCP_PATH,
            issuer="https://identity.localhost:7840/realms/platform",
            callback="http://127.0.0.1:7842/callback",
            username="mcp-e2e-reader@example.test",
            ca_file="unused",
        )
        with (
            patch.object(client, "validate_local_url", side_effect=lambda value: value),
            patch.object(client.ssl, "create_default_context"),
            patch.object(client.httpx, "AsyncClient", side_effect=factory),
            patch.dict("os.environ", {"MCP_TEST_PASSWORD": "fixture-only"}),
        ):
            with self.assertRaises(ValueError):
                await client.run(args)
            request = httpx.Request(
                "POST",
                "https://identity.localhost:7840/realms/other/protocol/openid-connect/token",
                data={"grant_type": "authorization_code", "code": "example"},
            )
            with self.assertRaises(ValueError):
                await captured[0](request)


if __name__ == "__main__":
    unittest.main()
