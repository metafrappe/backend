"""The apply step writes the enterprise-sso-required role from the membership file (G-160, AJA-363).

Expected rules, from the G-160 design (AJA-361):
- the membership layer in Frappe decides who needs the role; Frappe never writes Keycloak,
- `atonota-login apply` gives the role to every Keycloak user named in the file,
- the step takes the role back from a user who is no longer in the file (the membership ended),
- a user is found by the stable Keycloak user id (the token's `sub`), never by the e-mail,
- a second Keycloak account with the same e-mail gets no role and no link,
- the file can carry only the roles that the membership layer owns,
- a user who holds the role cannot finish a social platform sign-in such as Google.
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from atonota_login import keycloak_apply, platforms
from atonota_login.keycloak_apply import ApplyError

BACKEND = Path(__file__).resolve().parents[3]
REALM_FILE = BACKEND / "identity" / "keycloak" / "realm" / "platform-realm.json"
GOOGLE_RECORD = BACKEND / "identity" / "atonota_login" / "platforms" / "google.json"
ROLE = "enterprise-sso-required"
MEMBER = "6f1c2a9e-0d4b-4c8e-9a51-3b2e1f0c7d11"
SAME_EMAIL = "0a9b8c7d-6e5f-4a3b-8c2d-1e0f9a8b7c6d"
FORMER = "c3d2e1f0-a9b8-4c7d-8e6f-5a4b3c2d1e0f"


class FakeUsers:
    """Users, realm roles and role mappings of a fake platform realm. It records every call."""

    def __init__(self, users, holders=()):
        self.users = {user["id"]: copy.deepcopy(user) for user in users}
        self.roles = {ROLE: {"id": "role-1", "name": ROLE, "composite": False}}
        self.holders = {ROLE: set(holders)}
        self.calls = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        parts = path.split("?", 1)[0].strip("/").split("/")
        if parts[0] == "roles" and method == "GET":
            role = self.roles.get(parts[1])
            if role is None:
                return 404, None
            if len(parts) == 2:
                return 200, copy.deepcopy(role)
            query = dict(item.split("=") for item in path.split("?", 1)[1].split("&"))
            members = sorted(self.holders[parts[1]])
            start, size = int(query["first"]), int(query["max"])
            return 200, [copy.deepcopy(self.users[i]) for i in members[start : start + size]]
        if parts[0] == "users" and len(parts) == 2 and method == "GET":
            user = self.users.get(parts[1])
            return (200, copy.deepcopy(user)) if user else (404, None)
        if parts[0] == "users" and parts[2:] == ["role-mappings", "realm"]:
            if parts[1] not in self.users:
                return 404, None
            names = {role["name"] for role in payload}
            for name in names:
                if method == "POST":
                    self.holders[name].add(parts[1])
                elif method == "DELETE":
                    self.holders[name].discard(parts[1])
            return 204, None
        return 500, None


def user(user_id, email="ayse@acme.example"):
    return {"id": user_id, "username": user_id, "email": email, "enabled": True}


class EnterpriseRoleApplyTest(unittest.TestCase):
    def setUp(self):
        self.keycloak = FakeUsers([user(MEMBER), user(SAME_EMAIL), user(FORMER, "former@acme.example")])

    def test_member_of_required_organisation_gets_the_role(self):
        report = keycloak_apply.apply_realm_roles(self.keycloak, [{"subject": MEMBER, "realm_roles": [ROLE]}])
        self.assertEqual(self.keycloak.holders[ROLE], {MEMBER})
        self.assertIn(("POST", f"/users/{MEMBER}/role-mappings/realm", [self.keycloak.roles[ROLE]]), self.keycloak.calls)
        self.assertEqual(report, [{"role": ROLE, "added": 1, "removed": 0, "kept": 0}])

    def test_role_is_taken_back_when_membership_ends(self):
        self.keycloak.holders[ROLE] = {MEMBER, FORMER}
        report = keycloak_apply.apply_realm_roles(self.keycloak, [{"subject": MEMBER, "realm_roles": [ROLE]}])
        self.assertEqual(self.keycloak.holders[ROLE], {MEMBER})
        self.assertIn(("DELETE", f"/users/{FORMER}/role-mappings/realm", [self.keycloak.roles[ROLE]]), self.keycloak.calls)
        self.assertEqual(report, [{"role": ROLE, "added": 0, "removed": 1, "kept": 1}])

    def test_empty_file_takes_every_role_back(self):
        self.keycloak.holders[ROLE] = {FORMER}
        keycloak_apply.apply_realm_roles(self.keycloak, [])
        self.assertEqual(self.keycloak.holders[ROLE], set())

    def test_role_holders_are_read_page_by_page(self):
        many = [user(f"u-{number:04d}", f"u{number}@acme.example") for number in range(230)]
        self.keycloak = FakeUsers(many, holders=[item["id"] for item in many])
        entries = [{"subject": item["id"], "realm_roles": [ROLE]} for item in many]
        report = keycloak_apply.apply_realm_roles(self.keycloak, entries)
        self.assertEqual(report, [{"role": ROLE, "added": 0, "removed": 0, "kept": 230}])

    def test_second_account_with_the_same_e_mail_is_not_linked_or_given_the_role(self):
        keycloak_apply.apply_realm_roles(self.keycloak, [{"subject": MEMBER, "realm_roles": [ROLE]}])
        self.assertNotIn(SAME_EMAIL, self.keycloak.holders[ROLE])
        for method, path, _ in self.keycloak.calls:
            # No lookup by e-mail and no write that links two accounts.
            self.assertNotIn("email", path)
            self.assertNotIn("search", path)
            self.assertNotIn("federated-identity", path)
            self.assertFalse(method == "PUT", path)
            self.assertNotIn(SAME_EMAIL, path)

    def test_unknown_user_stops_the_step_before_any_write(self):
        with self.assertRaises(ApplyError) as raised:
            keycloak_apply.apply_realm_roles(self.keycloak, [{"subject": "missing-user", "realm_roles": [ROLE]}])
        self.assertEqual(raised.exception.rule, "unknown_user")
        self.assertFalse([call for call in self.keycloak.calls if call[0] != "GET"])

    def test_file_cannot_give_another_role(self):
        for roles in (["admin"], [ROLE, "realm-admin"]):
            with self.subTest(roles=roles):
                with self.assertRaises(ApplyError) as raised:
                    keycloak_apply.apply_realm_roles(self.keycloak, [{"subject": MEMBER, "realm_roles": roles}])
                self.assertEqual(raised.exception.rule, "role_not_managed")
                self.assertFalse(self.keycloak.calls)

    def test_missing_realm_role_stops_the_step(self):
        del self.keycloak.roles[ROLE]
        with self.assertRaises(ApplyError) as raised:
            keycloak_apply.apply_realm_roles(self.keycloak, [{"subject": MEMBER, "realm_roles": [ROLE]}])
        self.assertEqual(raised.exception.rule, "role_missing")

    def test_read_realm_roles_refuses_a_malformed_file(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "roles.json"
        for body in ('{"subject": "x"}', '[{"subject": ""}]', '[{"subject": "x", "realm_roles": "r"}]',
                     '[{"subject": "x", "realm_roles": [], "email": "a@b"}]',
                     f'[{{"subject": "x", "realm_roles": ["{ROLE}"]}}, {{"subject": "x", "realm_roles": []}}]'):
            with self.subTest(body=body):
                path.write_text(body, encoding="utf-8")
                with self.assertRaises(ApplyError):
                    keycloak_apply.read_realm_roles(path)
        path.write_text(json.dumps([{"subject": MEMBER, "realm_roles": [ROLE]}]), encoding="utf-8")
        self.assertEqual(keycloak_apply.read_realm_roles(path), [{"subject": MEMBER, "realm_roles": [ROLE]}])


class RoleHolderSignInTest(unittest.TestCase):
    """A user who holds the role the apply step writes cannot finish a Google sign-in."""

    def setUp(self):
        self.realm = json.loads(REALM_FILE.read_text(encoding="utf-8"))

    def test_apply_writes_the_role_that_the_sign_in_flow_refuses(self):
        self.assertEqual(platforms.ENTERPRISE_SSO_ROLE, ROLE)
        self.assertEqual(keycloak_apply.MANAGED_REALM_ROLES, frozenset({platforms.ENTERPRISE_SSO_ROLE}))
        configs = {c["alias"]: c["config"] for c in self.realm["authenticatorConfig"]}
        flows = {f["alias"]: f for f in self.realm["authenticationFlows"]}
        steps = []
        for execution in flows[platforms.POST_BROKER_FLOW]["authenticationExecutions"]:
            if execution.get("authenticatorFlow"):
                steps.append([e for e in flows[execution["flowAlias"]]["authenticationExecutions"]])
        refusing = [
            branch for branch in steps
            if any(configs.get(e.get("authenticatorConfig"), {}).get("condUserRole") == platforms.ENTERPRISE_SSO_ROLE
                   for e in branch)
        ]
        self.assertEqual(len(refusing), 1)
        self.assertIn("deny-access-authenticator", [e.get("authenticator") for e in refusing[0]])

    def test_google_sign_in_runs_the_refusing_flow(self):
        google = platforms.load_platforms(GOOGLE_RECORD.parent)
        record = next(p for p in google if p.alias == "google")
        state = platforms.desired_state(record, {})
        self.assertEqual(state["postBrokerLoginFlowAlias"], platforms.POST_BROKER_FLOW)
        realm_google = next(p for p in self.realm["identityProviders"] if p["alias"] == "google")
        self.assertEqual(realm_google["postBrokerLoginFlowAlias"], platforms.POST_BROKER_FLOW)


if __name__ == "__main__":
    unittest.main()
