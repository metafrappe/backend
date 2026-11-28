"""G-82: every service identity gets one target per token (realm file check, no Keycloak needed).

A service client must not receive an audience without asking for it. So no audience mapper sits
on the client itself or in one of its default scopes. Each target scope it may ask for adds exactly
one audience. The live check of granted tokens is test_token_access_matrix.
"""

from __future__ import annotations

import unittest

from helpers import read_realm

AUDIENCE_MAPPERS = {"oidc-audience-mapper", "oidc-hardcoded-claim-mapper"}


def _audience_mappers(mappers: list) -> list:
    found = []
    for mapper in mappers or []:
        kind = mapper.get("protocolMapper")
        config = mapper.get("config", {})
        if kind == "oidc-audience-mapper" or (kind in AUDIENCE_MAPPERS and config.get("claim.name") == "aud"):
            found.append(mapper)
    return found


class ServiceSingleTargetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        realm = read_realm()
        cls.scopes = {scope["name"]: scope for scope in realm["clientScopes"]}
        cls.services = {c["clientId"]: c for c in realm["clients"] if c.get("serviceAccountsEnabled")}

    def test_the_realm_has_the_three_service_identities(self):
        self.assertEqual(set(self.services), {"site-tenant1-service", "identity-sync", "press-service"})

    def test_no_service_gets_an_audience_without_asking(self):
        for client_id, client in self.services.items():
            with self.subTest(client=client_id):
                self.assertEqual(_audience_mappers(client.get("protocolMappers")), [])
                for name in client.get("defaultClientScopes", []):
                    self.assertFalse(name.startswith("aud-"), name)
                    self.assertEqual(_audience_mappers(self.scopes[name].get("protocolMappers")), [], name)

    def test_each_target_scope_adds_exactly_one_audience(self):
        for client_id, client in self.services.items():
            for name in client.get("optionalClientScopes", []):
                if not name.startswith("aud-"):
                    continue
                with self.subTest(client=client_id, scope=name):
                    mappers = _audience_mappers(self.scopes[name].get("protocolMappers"))
                    self.assertEqual(len(mappers), 1)
                    config = mappers[0]["config"]
                    audience = config.get("included.client.audience") or config.get("included.custom.audience")
                    self.assertTrue(audience)
                    self.assertNotIn(" ", audience)
                    self.assertEqual(config.get("id.token.claim"), "false")


if __name__ == "__main__":
    unittest.main()
