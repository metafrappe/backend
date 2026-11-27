"""G-77/G-152: repair declared client drift without touching account records.

Uses the existing in-memory Admin API fixture. A successful test is not evidence
that a deployed realm or an upgraded Keycloak provider has been checked.
"""

import copy
import unittest

import test_create_tenant_client as tenant_fixture
import test_realm_sync as realm_fixture


class PressRealmDriftTest(unittest.TestCase):
    def setUp(self):
        self.fixture = realm_fixture.RealmSyncTest()
        self.fixture.setUp()

    def test_declared_press_and_tenant_callback_drift_is_removed(self):
        admin = self.fixture.fresh_admin()
        for name in ("press", "site-tenant1"):
            client = admin.client_named(name)
            client["redirectUris"] = ["https://wrong.example.test/*"]
            client["attributes"]["pkce.code.challenge.method"] = "plain"
            client["directAccessGrantsEnabled"] = True

        changes = self.fixture.run_sync(admin)

        self.assertTrue(changes)
        for name in ("press", "site-tenant1"):
            actual = admin.client_named(name)
            desired = self.fixture.file_client(name)
            self.assertEqual(actual["redirectUris"], desired["redirectUris"])
            self.assertTrue(actual["redirectUris"])
            self.assertTrue(all("*" not in uri for uri in actual["redirectUris"]))
            self.assertEqual(actual["attributes"]["pkce.code.challenge.method"], "S256")
            self.assertFalse(actual["directAccessGrantsEnabled"])
        self.assertTrue(
            all("/users" not in path and "/sessions" not in path for _, path in admin.calls)
        )
        admin.calls.clear()
        self.assertEqual(self.fixture.run_sync(admin), [])
        self.assertEqual(admin.writes(), [])

    def test_declared_service_scope_moves_out_of_default_token_audience(self):
        admin = self.fixture.fresh_admin()
        scope = admin.scope_id("aud-press")
        identity_sync = admin.client_named("identity-sync")
        admin.bindings[(identity_sync["id"], "optional")].discard(scope)
        admin.bindings[(identity_sync["id"], "default")].add(scope)
        press_before = copy.deepcopy(admin.client_named("press"))

        self.fixture.run_sync(admin)

        self.assertNotIn("aud-press", admin.bound("identity-sync", "default"))
        self.assertIn("aud-press", admin.bound("identity-sync", "optional"))
        self.assertEqual(admin.client_named("press"), press_before)
        self.assertEqual(self.fixture.run_sync(admin), [])

    def test_tenant_templates_keep_callbacks_and_audiences_separate(self):
        command = tenant_fixture.CreateTenantClientTest()
        for name in ("acme", "second"):
            with self.subTest(tenant=name):
                server = tenant_fixture.FakeKeycloak()
                origin = f"https://{name}.example.test"
                args = [name, origin, "https://identity.example.test"]
                code, _, _, _ = command.run_command(
                    args, reply=f"CREATE site-{name}", server=server
                )

                self.assertEqual(code, 0)
                browser = server.clients[f"site-{name}"]
                self.assertEqual(
                    browser["redirectUris"],
                    [f"{origin}/api/method/platform_core.api.auth.keycloak_callback"],
                )
                self.assertEqual(browser["optionalClientScopes"], [])
                self.assertEqual(
                    server.clients[f"site-{name}-service"]["optionalClientScopes"],
                    ["aud-identity-sync"],
                )
                scope = server.scopes[f"aud-site-{name}"]
                self.assertEqual(
                    scope["protocolMappers"][0]["config"]["included.client.audience"],
                    f"site-{name}",
                )
                self.assertTrue(
                    all("/admin/realms/platform/" in call.full_url for call in server.calls)
                )
