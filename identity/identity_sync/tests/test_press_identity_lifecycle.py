"""G-16/G-79/G-81: exercise invitation and recovery across HTTP test doubles.

Expectations come from docs/contracts.md sections 4, 6 and 7. These tests do not
establish real Press permissions or a deployed Keycloak event listener.
"""

from __future__ import annotations

import unittest

from identity_sync.events import Event
from identity_sync.httpjson import HttpError

from . import fakes


class PressIdentityLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = fakes.Stack(two_tenants=True)
        self.addCleanup(self.stack.close)
        self.organization = {"id": fakes.ORG_ID, "name": "tenant1", "alias": "tenant1"}
        self.other_organization = {
            "id": "org-second",
            "name": "tenant2",
            "alias": "tenant2",
        }
        self.email = "invited@example.test"

    def event(self, identifier: str) -> Event:
        return Event(
            id=identifier,
            kind="admin",
            type="USER_UPDATE",
            realm="platform",
            time=1,
            user_id=fakes.SUBJECT,
        )

    def invite_routes(self, *, existing: bool, membership_status: int = 201) -> None:
        keycloak = self.stack.keycloak
        if existing:
            keycloak.add_user(
                fakes.keycloak_user(email=self.email),
                [self.other_organization],
            )
        keycloak.on(
            "GET",
            f"{keycloak.admin}/users",
            lambda _request: (200, list(keycloak.users.values())),
        )

        def create(request):
            keycloak.add_user({"id": fakes.SUBJECT, **request.json()})
            return (
                201,
                None,
                {"Location": f"{keycloak.url}{keycloak.admin}/users/{fakes.SUBJECT}"},
            )

        def join(request):
            if membership_status != 201:
                return membership_status, {"error": "membership refused"}
            self.assertEqual(request.json(), fakes.SUBJECT)
            keycloak.memberships[fakes.SUBJECT].append(self.organization)
            return 201, None

        keycloak.on("POST", f"{keycloak.admin}/users", create)
        keycloak.on(
            "POST", f"{keycloak.admin}/organizations/{fakes.ORG_ID}/members", join
        )
        keycloak.on(
            "PUT",
            f"{keycloak.admin}/users/{fakes.SUBJECT}/execute-actions-email",
            (204, None),
        )

    def invite(self):
        return self.stack.app.keycloak.invite_user(
            self.email, "Invited", "Member", fakes.ORG_ID
        )

    def assert_linked(self, tenants) -> None:
        identity = (self.stack.issuer, fakes.SUBJECT)
        self.assertEqual(self.stack.press.links, {identity: self.email})
        for tenant in tenants:
            self.assertEqual(tenant.links, {identity: self.email})
            self.assertTrue(tenant.user_of(*identity)["enabled"])

    def test_new_invitee_waits_for_verification_then_links_only_the_invited_tenant(
        self,
    ) -> None:
        self.invite_routes(existing=False)
        result = self.invite()
        self.assertEqual(result.subject, fakes.SUBJECT)

        self.stack.app.processor.handle(self.event("before-verification"))
        self.assertEqual(self.stack.press.users, {})
        self.assertEqual(self.stack.tenant.users, {})
        self.assertEqual(self.stack.tenant2.users, {})

        self.stack.keycloak.users[fakes.SUBJECT]["emailVerified"] = True
        outcome = self.stack.app.processor.handle(self.event("after-verification"))

        self.assertEqual(outcome.status, "processed")
        self.assert_linked([self.stack.tenant])
        self.assertEqual(
            self.stack.press.teams_of(self.stack.issuer, fakes.SUBJECT), [fakes.ORG_ID]
        )
        self.assertEqual(self.stack.tenant2.users, {})
        self.assertEqual(self.stack.tenant2.calls("POST", fakes.TENANT_PROVISION), [])
        self.assertEqual(
            len(
                self.stack.keycloak.calls("POST", f"{self.stack.keycloak.admin}/users")
            ),
            1,
        )

    def test_existing_invitee_keeps_identity_and_membership_in_the_other_team(
        self,
    ) -> None:
        self.invite_routes(existing=True)
        original_user = dict(self.stack.keycloak.users[fakes.SUBJECT])

        self.assertEqual(self.invite().subject, fakes.SUBJECT)
        self.assertEqual(
            self.stack.app.processor.handle(self.event("existing-invite")).status,
            "processed",
        )

        self.assert_linked([self.stack.tenant, self.stack.tenant2])
        self.assertEqual(self.stack.keycloak.users[fakes.SUBJECT], original_user)
        self.assertEqual(
            self.stack.keycloak.calls("POST", f"{self.stack.keycloak.admin}/users"), []
        )
        self.assertEqual(
            self.stack.press.teams_of(self.stack.issuer, fakes.SUBJECT),
            sorted([fakes.ORG_ID, "org-second"]),
        )

    def test_refused_membership_sends_no_invitation_and_grants_no_target_access(
        self,
    ) -> None:
        self.invite_routes(existing=False, membership_status=403)

        with self.assertRaises(HttpError) as caught:
            self.invite()

        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(self.stack.keycloak.memberships[fakes.SUBJECT], [])
        email_path = (
            f"{self.stack.keycloak.admin}/users/{fakes.SUBJECT}/execute-actions-email"
        )
        self.assertEqual(self.stack.keycloak.calls("PUT", email_path), [])
        self.stack.app.processor.handle(self.event("refused-invite"))
        self.assertEqual(self.stack.press.users, {})
        self.assertEqual(self.stack.tenant.users, {})
        self.assertEqual(self.stack.tenant2.users, {})

    def test_partial_delivery_replays_latest_source_state_without_duplicate_accounts(
        self,
    ) -> None:
        self.stack.keycloak.add_user(
            fakes.keycloak_user(email=self.email),
            [self.organization, self.other_organization],
        )
        self.stack.tenant2.on("POST", fakes.TENANT_PROVISION, (503, None))
        change = self.event("partial-delivery")

        self.assertEqual(
            self.stack.app.processor.handle(change).status, "dead_lettered"
        )
        self.assertEqual(
            len(self.stack.tenant2.calls("POST", fakes.TENANT_PROVISION)), 3
        )
        self.assertEqual(len(self.stack.sleeps), 2)
        self.assert_linked([self.stack.tenant])
        self.assertIsNone(self.stack.tenant2.user_of(self.stack.issuer, fakes.SUBJECT))
        (letter,) = self.stack.app.store.dead_letters()
        self.assertEqual(letter.event.id, change.id)

        self.stack.keycloak.users[fakes.SUBJECT]["firstName"] = "Current"
        self.stack.tenant2.on("POST", fakes.TENANT_PROVISION, fakes.DONE)
        replayed = self.stack.app.processor.replay_dead_letters()

        self.assertEqual(
            [(identifier, result.status) for identifier, result in replayed],
            [(change.id, "processed")],
        )
        self.assertEqual(self.stack.app.store.dead_letters(), [])
        self.assert_linked([self.stack.tenant, self.stack.tenant2])
        for tenant in (self.stack.tenant, self.stack.tenant2):
            self.assertEqual(
                tenant.user_of(self.stack.issuer, fakes.SUBJECT)["first_name"],
                "Current",
            )
            self.assertEqual(len(tenant.users), 1)
        for team in self.stack.press.teams.values():
            self.assertEqual(team["members"], {self.email})

        targets = (self.stack.press, self.stack.tenant, self.stack.tenant2)
        calls_before = [len(target.requests) for target in targets]
        self.assertEqual(self.stack.app.processor.handle(change).status, "duplicate")
        self.assertEqual([len(target.requests) for target in targets], calls_before)

    def test_disabled_source_closes_both_tenants_after_one_target_recovers(
        self,
    ) -> None:
        for organization in (self.organization, self.other_organization):
            self.stack.press.seed_member(
                self.stack.issuer,
                fakes.SUBJECT,
                self.email,
                organization["id"],
                api_keys=2,
            )
        for tenant in (self.stack.tenant, self.stack.tenant2):
            tenant.seed_user(self.stack.issuer, fakes.SUBJECT, self.email)
        self.stack.keycloak.add_user(
            fakes.keycloak_user(email=self.email, enabled=False), []
        )
        self.stack.tenant2.on("POST", fakes.TENANT_SET_ENABLED, (503, None))

        self.assertEqual(
            self.stack.app.processor.handle(self.event("disable")).status,
            "dead_lettered",
        )
        self.assertFalse(
            self.stack.press.user_of(self.stack.issuer, fakes.SUBJECT)["enabled"]
        )
        self.assertEqual(
            self.stack.press.user_of(self.stack.issuer, fakes.SUBJECT)["api_keys"], []
        )
        self.assertEqual(
            self.stack.press.teams_of(self.stack.issuer, fakes.SUBJECT), []
        )
        self.assertFalse(
            self.stack.tenant.user_of(self.stack.issuer, fakes.SUBJECT)["enabled"]
        )
        self.assertTrue(
            self.stack.tenant2.user_of(self.stack.issuer, fakes.SUBJECT)["enabled"]
        )

        self.stack.tenant2.on("POST", fakes.TENANT_SET_ENABLED, fakes.DONE)
        self.assertEqual(
            self.stack.app.processor.replay_dead_letters()[0][1].status, "processed"
        )
        self.assertFalse(
            self.stack.tenant2.user_of(self.stack.issuer, fakes.SUBJECT)["enabled"]
        )
        self.assertEqual(self.stack.app.store.dead_letters(), [])
