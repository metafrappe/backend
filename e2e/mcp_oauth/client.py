"""Exercise a local MCP resource with the official SDK's OAuth client.

No provisioning, container commands, disk token storage or production destinations.
The HTTP form driver represents only a synthetic fixture user, not a browser test.
"""

import argparse
import asyncio
import base64
from datetime import timedelta
import hashlib
from html.parser import HTMLParser
from importlib.metadata import version
import ipaddress
import json
import logging
import os
import socket
import ssl
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth.utils import extract_resource_metadata_from_www_auth
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


TOOL = "plt_search_doctypes"
ARGUMENTS = {"limit": 1}
MCP_PATH = "/api/method/platform_core.api.ai.mcp"


def validate_local_url(value: str) -> str:
    """Reject non-TLS, ambiguous and non-loopback test destinations."""
    address = urlsplit(value)
    host = address.hostname
    if (
        address.scheme != "https"
        or not host
        or address.username
        or address.password
        or address.query
        or address.fragment
        or address.port == 0
    ):
        raise ValueError("Expected an unambiguous local HTTPS URL")
    allowed = host in {"localhost", "identity.localhost", "tenant1.localhost"}
    if not allowed:
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = False
    if not allowed:
        raise ValueError("Only local test hosts are allowed")
    addresses = socket.getaddrinfo(host, address.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_loopback for item in addresses):
        raise ValueError("Test host must resolve only to loopback")
    return value


def origin(value: str) -> tuple[str, str | None, int]:
    address = urlsplit(value)
    return address.scheme, address.hostname, address.port or (443 if address.scheme == "https" else 80)


def validate_discovery(metadata: dict, resource: str, issuer: str) -> None:
    if (
        metadata.get("resource") != resource
        or metadata.get("authorization_servers") != [issuer]
        or "mcp" not in metadata.get("scopes_supported", [])
        or metadata.get("bearer_methods_supported") != ["header"]
    ):
        raise ValueError("Resource metadata does not match the configured fixture")


class LoginForm(HTMLParser):
    """Read only Keycloak's login and consent forms; ignore unrelated page fields."""

    def __init__(self, html: str):
        super().__init__()
        self.kind = None
        self.action = None
        self.fields = {}
        self.inside = False
        self.feed(html)

    def handle_starttag(self, tag: str, attributes: list) -> None:
        attrs = dict(attributes)
        if tag == "form":
            consent = urlsplit(attrs.get("action") or "").path.endswith("/login-actions/consent")
            self.inside = attrs.get("id") == "kc-form-login" or consent
            if self.inside:
                self.kind = "kc-oauth" if consent else "kc-form-login"
                self.action = attrs.get("action")
        if self.inside and tag == "input" and attrs.get("type") == "hidden" and attrs.get("name"):
            self.fields[attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.inside = False


class FixtureBrowser:
    """Submit synthetic credentials only to the selected Keycloak realm."""

    def __init__(self, http, issuer: str, callback: str, username: str, password: str):
        address = urlsplit(callback)
        if (
            address.scheme != "http"
            or address.hostname != "127.0.0.1"
            or not address.port
            or address.username
            or address.password
            or address.query
            or address.fragment
            or address.path != "/callback"
        ):
            raise ValueError("Expected the registered loopback callback")
        if not username.startswith("mcp-e2e-") or not username.endswith("@example.test") or not password:
            raise ValueError("Only synthetic fixture credentials are allowed")
        self.http = http
        self.issuer = issuer
        self.redirect_uri = callback
        self.username = username
        self.password = password
        self.result = None

    def check_realm_url(self, url: str) -> None:
        address = urlsplit(url)
        prefix = urlsplit(self.issuer).path.rstrip("/") + "/"
        if (
            origin(url) != origin(self.issuer)
            or not address.path.startswith(prefix)
            or address.username
            or address.password
            or address.fragment
        ):
            raise ValueError("Login left the configured realm")

    async def redirect(self, url: str) -> None:
        self.result = None
        password_sent = False
        self.check_realm_url(url)
        response = await self.http.get(url)
        for _ in range(10):
            if response.status_code in (302, 303):
                target = urljoin(str(response.url), response.headers.get("location", ""))
                address = urlsplit(target)
                callback = urlsplit(self.redirect_uri)
                if (address.scheme, address.netloc, address.path) == (
                    callback.scheme,
                    callback.netloc,
                    callback.path,
                ):
                    query = parse_qs(address.query, keep_blank_values=True)
                    if (
                        address.fragment
                        or set(query) - {"code", "state", "session_state", "iss"}
                        or any(len(query.get(key, [])) != 1 or not query[key][0] for key in ("code", "state"))
                        or ("iss" in query and query["iss"] != [self.issuer])
                    ):
                        raise ValueError("Invalid authorization callback")
                    self.result = (query["code"][0], query["state"][0])
                    return
                self.check_realm_url(target)
                response = await self.http.get(target)
                continue
            if response.status_code != 200:
                raise ValueError("Keycloak login was refused")
            form = LoginForm(response.text)
            if not form.action:
                raise ValueError("Expected the fixture login or consent form")
            action = urljoin(str(response.url), form.action)
            self.check_realm_url(action)
            if not urlsplit(action).path.startswith(urlsplit(self.issuer).path + "/login-actions/"):
                raise ValueError("Unexpected login form action")
            data = form.fields
            if form.kind == "kc-form-login":
                if password_sent:
                    raise ValueError("The fixture password was rejected; no retry was sent")
                data.update(username=self.username, password=self.password)
                password_sent = True
            elif form.kind == "kc-oauth":
                data["accept"] = "true"
            response = await self.http.post(action, data=data)
        raise ValueError("Fixture login exceeded its step limit")

    async def callback(self) -> tuple[str, str]:
        if self.result is None:
            raise ValueError("No authorization callback was received")
        return self.result


class MemoryStorage:
    """Pre-register the public client; never save tokens to disk."""

    def __init__(self, metadata: OAuthClientMetadata):
        self.client_info = OAuthClientInformationFull(client_id="mcp-external", **metadata.model_dump())
        self.tokens = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        raise ValueError("Dynamic client registration is outside this test")


async def run(args) -> dict:
    if version("mcp") != "1.29.0":
        raise ValueError("Install the pinned MCP SDK version")
    resource = validate_local_url(args.resource)
    issuer = validate_local_url(args.issuer)
    if urlsplit(resource).path != MCP_PATH or not urlsplit(issuer).path.startswith("/realms/"):
        raise ValueError("Expected the platform MCP resource and a Keycloak realm")
    context = ssl.create_default_context(cafile=args.ca_file)
    observed = {
        "pkce_s256": False,
        "pkce_exchange": False,
        "scope_mcp_only": False,
        "authorization_resource": False,
        "token_resource": False,
    }
    challenge_value = None
    authorization_requests = 0

    async def restrict_request(request: httpx.Request) -> None:
        nonlocal challenge_value, authorization_requests
        # The SDK follows discovery itself. Guard every resulting request, including redirects.
        target = str(request.url)
        address = urlsplit(target)
        validate_local_url(address._replace(query="").geturl())
        if origin(target) not in {origin(resource), origin(issuer)}:
            raise ValueError("Discovery left the configured local origins")
        if request.headers.get("authorization") and target != resource:
            raise ValueError("Bearer token left its resource")
        token_endpoint = issuer.rstrip("/") + "/protocol/openid-connect/token"
        if request.method == "POST" and origin(target) == origin(issuer):
            login_prefix = urlsplit(issuer).path.rstrip("/") + "/login-actions/"
            if target != token_endpoint and not address.path.startswith(login_prefix):
                raise ValueError("Credentials left the configured Keycloak realm")
        if address.path.endswith("/protocol/openid-connect/auth"):
            query = parse_qs(address.query)
            authorization_requests += 1
            challenge_value = query.get("code_challenge", [None])[0]
            observed["pkce_s256"] = query.get("code_challenge_method") == ["S256"]
            observed["scope_mcp_only"] = query.get("scope") == ["mcp"]
            observed["authorization_resource"] = query.get("resource") == [resource]
        if target == token_endpoint and request.method == "POST":
            form = parse_qs(request.content.decode())
            verifier = form.get("code_verifier", [""])[0]
            calculated = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            )
            observed["pkce_exchange"] = bool(verifier) and calculated == challenge_value
            observed["token_resource"] = form.get("resource") == [resource] and form.get("grant_type") == [
                "authorization_code"
            ]

    options = {
        "verify": context,
        "trust_env": False,
        "timeout": 20,
        "follow_redirects": False,
        "event_hooks": {"request": [restrict_request]},
    }
    # Never share the Keycloak cookie jar with the MCP client.
    async with httpx.AsyncClient(**options) as browser_http, httpx.AsyncClient(**options) as http:
        browser = FixtureBrowser(
            browser_http, issuer, args.callback, args.username, os.environ.get("MCP_TEST_PASSWORD", "")
        )
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": TOOL, "arguments": ARGUMENTS},
        }
        headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
        challenge = await http.post(resource, json=body, headers=headers)
        metadata_url = extract_resource_metadata_from_www_auth(challenge)
        if challenge.status_code != 401 or not metadata_url:
            raise ValueError("OAuth discovery is not enabled on the local resource")
        validate_local_url(metadata_url)
        if origin(metadata_url) != origin(resource):
            raise ValueError("Resource metadata left the MCP origin")
        response = await http.get(metadata_url)
        response.raise_for_status()
        validate_discovery(response.json(), resource, issuer)
        metadata = OAuthClientMetadata(
            redirect_uris=[args.callback],
            scope="mcp",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
        )
        storage = MemoryStorage(metadata)
        provider = OAuthClientProvider(
            resource, metadata, storage, redirect_handler=browser.redirect, callback_handler=browser.callback
        )
        http.auth = provider
        async with streamable_http_client(resource, http_client=http, terminate_on_close=False) as streams:
            async with ClientSession(
                streams[0], streams[1], read_timeout_seconds=timedelta(seconds=20)
            ) as session:
                initialized = await session.initialize()
                if initialized.protocolVersion != "2025-11-25":
                    raise ValueError("The server negotiated an unexpected MCP version")
                result = await session.call_tool(TOOL, ARGUMENTS)
                if result.isError or not result.content:
                    raise ValueError("The authenticated tool call did not succeed")
        if not storage.tokens or not all(observed.values()) or authorization_requests != 1:
            raise ValueError("The SDK OAuth flow did not satisfy the expected contract")
        # Explicit auth=None prevents the SDK from replacing the invalid token with a fresh login.
        prefix, signature = storage.tokens.access_token.rsplit(".", 1)
        altered = prefix + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
        denied = await http.post(
            resource, json=body, auth=None, headers={**headers, "Authorization": "Bearer " + altered}
        )
        if denied.status_code != 401:
            raise ValueError("An invalid token was not rejected with HTTP 401")
        return {
            "environment": "local",
            "client": "mcp",
            "client_version": version("mcp"),
            "protocol": initialized.protocolVersion,
            "oauth": "pass",
            **observed,
            "authorization_requests": authorization_requests,
            "requested_scope": "mcp",
            "tool": TOOL,
            "tool_call": "pass",
            "invalid_token_case": "tampered_signature",
            "invalid_token_status": denied.status_code,
        }


async def bounded_run(args) -> dict:
    async with asyncio.timeout(120):
        return await run(args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("resource", "issuer", "callback", "username", "ca-file"):
        parser.add_argument("--" + option, required=True)
    args = parser.parse_args()
    # Third-party exception logs can contain callback codes or token responses.
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(bounded_run(args))
    except Exception as error:
        print(json.dumps({"environment": "local", "result": "fail", "error_type": type(error).__name__}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
