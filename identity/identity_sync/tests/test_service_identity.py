"""G-82: a service token carries one target, and the service keeps no long-lived key.

Rules: docs/sozlesmeler.md section 2 (one `aud` per token) and the G-82 requirement
("no service stores a long-lived API key on behalf of a user").
"""

from __future__ import annotations

import unittest
from unittest import mock

from identity_sync import tokens
from identity_sync.httpjson import Response
from identity_sync.tokens import TokenProvider


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _provider(clock: _Clock | None = None) -> TokenProvider:
    return TokenProvider(
        "https://keycloak.example.test/realms/platform/protocol/openid-connect/token",
        "identity-sync",
        "synthetic-secret",
        timeout=1.0,
        clock=clock or _Clock(),
    )


def _answer(token: str, expires_in: int = 300) -> Response:
    return Response(status=200, body={"access_token": token, "expires_in": expires_in}, headers={})


class SingleTargetTest(unittest.TestCase):
    def test_a_request_for_two_targets_is_refused_before_keycloak(self) -> None:
        with mock.patch.object(tokens, "request_json") as send:
            for scope in ("aud-site-tenant1 aud-press", "aud-press  aud-identity-sync", "aud-press aud-press"):
                with self.subTest(scope=scope), self.assertRaises(ValueError):
                    _provider().get(scope)
        send.assert_not_called()

    def test_each_token_request_names_at_most_one_target(self) -> None:
        with mock.patch.object(tokens, "request_json", return_value=_answer("t1")) as send:
            provider = _provider()
            provider.get("aud-site-tenant1")
            provider.get("admin-api kc-admin-api")
        scopes = [call.kwargs["form"]["scope"] for call in send.call_args_list]
        self.assertEqual(scopes, ["aud-site-tenant1", "admin-api kc-admin-api"])
        for scope in scopes:
            targets = [part for part in scope.split() if part.startswith("aud-")]
            self.assertLessEqual(len(targets), 1, scope)

    def test_tokens_of_different_targets_are_kept_apart(self) -> None:
        answers = [_answer("tenant-token"), _answer("press-token")]
        with mock.patch.object(tokens, "request_json", side_effect=answers):
            provider = _provider()
            self.assertEqual(provider.get("aud-site-tenant1"), "tenant-token")
            self.assertEqual(provider.get("aud-press"), "press-token")
            self.assertEqual(provider.get("aud-site-tenant1"), "tenant-token")


class NoLongLivedKeyTest(unittest.TestCase):
    def test_a_token_is_dropped_when_it_expires(self) -> None:
        clock = _Clock()
        answers = [_answer("first", expires_in=300), _answer("second", expires_in=300)]
        with mock.patch.object(tokens, "request_json", side_effect=answers) as send:
            provider = _provider(clock)
            self.assertEqual(provider.get("aud-press"), "first")
            clock.now += 300
            self.assertEqual(provider.get("aud-press"), "second")
        self.assertEqual(send.call_count, 2)

    def test_a_very_long_lifetime_is_not_kept(self) -> None:
        clock = _Clock()
        answers = [_answer("first", expires_in=10 * 365 * 86400), _answer("second")]
        with mock.patch.object(tokens, "request_json", side_effect=answers):
            provider = _provider(clock)
            provider.get("aud-press")
            clock.now += tokens.MAX_CACHE_SECONDS
            self.assertEqual(provider.get("aud-press"), "second")

    def test_a_token_without_lifetime_is_not_reused(self) -> None:
        answers = [
            Response(status=200, body={"access_token": "first"}, headers={}),
            Response(status=200, body={"access_token": "second"}, headers={}),
        ]
        with mock.patch.object(tokens, "request_json", side_effect=answers):
            provider = _provider()
            self.assertEqual(provider.get("aud-press"), "first")
            self.assertEqual(provider.get("aud-press"), "second")

    def test_only_client_credentials_are_used(self) -> None:
        with mock.patch.object(tokens, "request_json", return_value=_answer("t1")) as send:
            _provider().get("aud-press")
        form = send.call_args.kwargs["form"]
        self.assertEqual(form["grant_type"], "client_credentials")
        self.assertNotIn("refresh_token", form)
        self.assertNotIn("offline_access", form.get("scope", ""))


if __name__ == "__main__":
    unittest.main()
