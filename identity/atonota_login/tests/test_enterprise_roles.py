"""The apply step writes the enterprise-sso-required role from the membership file (G-160, AJA-363).

Expected rules, from the G-160 design (AJA-361):
- the membership layer in Frappe decides who needs the role; Frappe never writes Keycloak,
- `atonota-login apply` gives the role to every Keycloak user named in the file,
- the step takes the role back from a user who is no longer in the file (the membership ended),
- a user is found by the stable Keycloak user id (the token's `sub`), never by the e-mail,
- a second Keycloak account with the same e-mail gets no role and no link,
- the file can carry only the roles that the membership layer owns,
- a user who holds the role cannot finish a social platform sign-in such as Google.

Tenant rules, from the system review (AJA-368, AJA-391):
- the realm is shared by every tenant site; the file names its source organisations by their
  Keycloak organisation id, the same value as the Press team's Keycloak organisation id,
- the step takes the role back only from members of those organisations, read from the
  Keycloak organisation members list; a member of another tenant keeps the role,
- a holder who is also a member of an organisation outside the file keeps the role,
- a file without organisations, or with an empty list, stops the step before any write.
"""

import contextlib
import copy
import importlib.machinery
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atonota_login import keycloak_apply, platforms
from atonota_login.keycloak_apply import ApplyError

BACKEND = Path(__file__).resolve().parents[3]
REALM_FILE = BACKEND / "identity" / "keycloak" / "realm" / "platform-realm.json"
GOOGLE_RECORD = BACKEND / "identity" / "atonota_login" / "platforms" / "google.json"
ROLE = "enterprise-sso-required"
MEMBER = "6f1c2a9e-0d4b-4c8e-9a51-3b2e1f0c7d11"
SAME_EMAIL = "0a9b8c7d-6e5f-4a3b-8c2d-1e0f9a8b7c6d"
FORMER = "c3d2e1f0-a9b8-4c7d-8e6f-5a4b3c2d1e0f"
B_MEMBER = "9e8d7c6b-5a49-4382-a1b0-c9d8e7f6a5b4"
ORG_A = "1a2b3c4d-0000-4000-8000-00000000000a"
ORG_B = "1a2b3c4d-0000-4000-8000-00000000000b"


class FakeUsers:
    """Users, realm roles and role mappings of a fake platform realm. It records every call."""

    def __init__(self, users, holders=(), members=None):
        self.users = {user["id"]: copy.deepcopy(user) for user in users}
        self.roles = {ROLE: {"id": "role-1", "name": ROLE, "composite": False}}
        self.holders = {ROLE: set(holders)}
        # Keycloak organisations by id, each with the ids of its members.
        self.members = {ORG_A: set(self.users)} if members is None else members
        self.calls = []

    def page(self, path, ids):
        query = dict(item.split("=") for item in path.split("?", 1)[1].split("&"))
        start, size = int(query["first"]), int(query["max"])
        return [copy.deepcopy(self.users[i]) for i in sorted(ids)[start : start + size]]

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        parts = path.split("?", 1)[0].strip("/").split("/")
        if parts[0] == "organizations" and method == "GET":
            if parts[1:2] == ["members"] and parts[3:] == ["organizations"]:
                return 200, [{"id": org, "alias": org} for org in sorted(self.members) if parts[2] in self.members[org]]
            if parts[1] not in self.members:
                return 404, None
            if len(parts) == 2:
                return 200, {"id": parts[1], "alias": parts[1]}
            if parts[2:] == ["members"]:
                return 200, self.page(path, self.members[parts[1]])
        if parts[0] == "roles" and method == "GET":
            role = self.roles.get(parts[1])
            if role is None:
                return 404, None
            if len(parts) == 2:
                return 200, copy.deepcopy(role)
            return 200, self.page(path, self.holders[parts[1]])
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


def roles_file(entries, organizations=(ORG_A,)):
    """The roles file of one tenant site: its source organisations and its entries."""
    return {"organizations": list(organizations), "entries": list(entries)}


def apply(keycloak, entries, organizations=(ORG_A,), allowed=None):
    allowed = organizations if allowed is None else allowed
    return keycloak_apply.apply_realm_roles(keycloak, roles_file(entries, organizations), allowed)


class EnterpriseRoleApplyTest(unittest.TestCase):
    def setUp(self):
        self.keycloak = FakeUsers([user(MEMBER), user(SAME_EMAIL), user(FORMER, "former@acme.example")])

    def test_member_of_required_organisation_gets_the_role(self):
        report = apply(self.keycloak, [{"subject": MEMBER, "realm_roles": [ROLE]}])
        self.assertEqual(self.keycloak.holders[ROLE], {MEMBER})
        self.assertIn(("POST", f"/users/{MEMBER}/role-mappings/realm", [self.keycloak.roles[ROLE]]), self.keycloak.calls)
        self.assertEqual(report, [{"role": ROLE, "added": 1, "removed": 0, "kept": 0}])

    def test_role_is_taken_back_when_membership_ends(self):
        self.keycloak.holders[ROLE] = {MEMBER, FORMER}
        report = apply(self.keycloak, [{"subject": MEMBER, "realm_roles": [ROLE]}])
        self.assertEqual(self.keycloak.holders[ROLE], {MEMBER})
        self.assertIn(("DELETE", f"/users/{FORMER}/role-mappings/realm", [self.keycloak.roles[ROLE]]), self.keycloak.calls)
        self.assertEqual(report, [{"role": ROLE, "added": 0, "removed": 1, "kept": 1}])

    def test_empty_file_takes_every_role_back(self):
        self.keycloak.holders[ROLE] = {FORMER}
        apply(self.keycloak, [])
        self.assertEqual(self.keycloak.holders[ROLE], set())

    def test_role_holders_are_read_page_by_page(self):
        many = [user(f"u-{number:04d}", f"u{number}@acme.example") for number in range(230)]
        self.keycloak = FakeUsers(many, holders=[item["id"] for item in many])
        self.keycloak.members[ORG_A] = {item["id"] for item in many}
        entries = [{"subject": item["id"], "realm_roles": [ROLE]} for item in many]
        report = apply(self.keycloak, entries)
        self.assertEqual(report, [{"role": ROLE, "added": 0, "removed": 0, "kept": 230}])

    def test_second_account_with_the_same_e_mail_is_not_linked_or_given_the_role(self):
        apply(self.keycloak, [{"subject": MEMBER, "realm_roles": [ROLE]}])
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
            apply(self.keycloak, [{"subject": "missing-user", "realm_roles": [ROLE]}])
        self.assertEqual(raised.exception.rule, "unknown_user")
        self.assertFalse([call for call in self.keycloak.calls if call[0] != "GET"])

    def test_file_cannot_give_another_role(self):
        for roles in (["admin"], [ROLE, "realm-admin"]):
            with self.subTest(roles=roles):
                with self.assertRaises(ApplyError) as raised:
                    apply(self.keycloak, [{"subject": MEMBER, "realm_roles": roles}])
                self.assertEqual(raised.exception.rule, "role_not_managed")
                self.assertFalse(self.keycloak.calls)

    def test_missing_realm_role_stops_the_step(self):
        del self.keycloak.roles[ROLE]
        with self.assertRaises(ApplyError) as raised:
            apply(self.keycloak, [{"subject": MEMBER, "realm_roles": [ROLE]}])
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
        for body in ('{"subject": "x"}', '[{"subject": ""}]', '[{"subject": "x", "realm_roles": "r"}]',
                     '[{"subject": "x", "realm_roles": [], "email": "a@b"}]',
                     f'[{{"subject": "x", "realm_roles": ["{ROLE}"]}}, {{"subject": "x", "realm_roles": []}}]'):
            with self.subTest(entries=body):
                path.write_text(f'{{"organizations": ["{ORG_A}"], "entries": {body}}}', encoding="utf-8")
                with self.assertRaises(ApplyError):
                    keycloak_apply.read_realm_roles(path)
        for organizations in ([""], [1], [ORG_A, ORG_A], ORG_A):
            with self.subTest(organizations=organizations):
                path.write_text(json.dumps(roles_file([], organizations)), encoding="utf-8")
                with self.assertRaises(ApplyError):
                    keycloak_apply.read_realm_roles(path)
        good = roles_file([{"subject": MEMBER, "realm_roles": [ROLE]}])
        path.write_text(json.dumps(good), encoding="utf-8")
        self.assertEqual(keycloak_apply.read_realm_roles(path), good)

    def test_read_realm_roles_refuses_a_file_without_organisations(self):
        # The old list form and an empty list name no source organisation. Nothing may be taken back.
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "roles.json"
        for body in (json.dumps([{"subject": MEMBER, "realm_roles": [ROLE]}]),
                     json.dumps({"entries": []}), json.dumps(roles_file([], []))):
            with self.subTest(body=body):
                path.write_text(body, encoding="utf-8")
                with self.assertRaises(ApplyError) as raised:
                    keycloak_apply.read_realm_roles(path)
                self.assertEqual(raised.exception.rule, "organizations_missing")


class TenantRoleApplyTest(unittest.TestCase):
    """One realm serves every tenant. A tenant's file never takes the role from another tenant."""

    def setUp(self):
        self.keycloak = FakeUsers(
            [user(MEMBER), user(FORMER, "former@acme.example"), user(B_MEMBER, "b@beta.example")],
            members={ORG_A: {MEMBER, FORMER}, ORG_B: {B_MEMBER}},
        )

    def test_tenant_a_file_does_not_touch_the_role_of_a_tenant_b_member(self):
        self.keycloak.holders[ROLE] = {MEMBER, FORMER, B_MEMBER}
        report = apply(self.keycloak, [{"subject": MEMBER, "realm_roles": [ROLE]}], [ORG_A])
        self.assertEqual(self.keycloak.holders[ROLE], {MEMBER, B_MEMBER})
        self.assertFalse([c for c in self.keycloak.calls if c[0] == "DELETE" and B_MEMBER in c[1]])
        self.assertEqual(report, [{"role": ROLE, "added": 0, "removed": 1, "kept": 1}])

    def test_empty_entries_take_the_role_back_only_inside_the_named_organisations(self):
        self.keycloak.holders[ROLE] = {MEMBER, B_MEMBER}
        apply(self.keycloak, [], [ORG_A])
        self.assertEqual(self.keycloak.holders[ROLE], {B_MEMBER})

    def test_member_of_an_organisation_outside_the_file_keeps_the_role(self):
        # MEMBER belongs to both tenants. Tenant B may still require corporate sign-in.
        self.keycloak.members[ORG_B].add(MEMBER)
        self.keycloak.holders[ROLE] = {MEMBER}
        apply(self.keycloak, [], [ORG_A])
        self.assertEqual(self.keycloak.holders[ROLE], {MEMBER})

    def test_holder_of_no_named_organisation_is_not_read_or_written(self):
        self.keycloak.holders[ROLE] = {B_MEMBER}
        apply(self.keycloak, [], [ORG_A])
        self.assertEqual(self.keycloak.holders[ROLE], {B_MEMBER})
        self.assertFalse([c for c in self.keycloak.calls if c[0] != "GET"])
        self.assertFalse([c for c in self.keycloak.calls if B_MEMBER in c[1]])

    def test_member_of_two_named_organisations_only_loses_the_role(self):
        self.keycloak.members[ORG_B].add(MEMBER)
        self.keycloak.holders[ROLE] = {MEMBER}
        apply(self.keycloak, [], [ORG_A, ORG_B])
        self.assertEqual(self.keycloak.holders[ROLE], set())

    def test_file_naming_another_tenant_organisation_is_refused(self):
        # A tenant writes its own organisation records. The operator passes the expected organisation
        # ids from the Press team. A file that names another organisation stops before any write.
        self.keycloak.holders[ROLE] = {B_MEMBER}
        for allowed in ([ORG_A], []):
            with self.subTest(allowed=allowed):
                self.keycloak.calls.clear()
                with self.assertRaises(ApplyError) as raised:
                    apply(self.keycloak, [], [ORG_A, ORG_B], allowed=allowed)
                self.assertEqual(raised.exception.rule,
                                 "organization_not_allowed" if allowed else "organizations_missing")
                self.assertFalse(self.keycloak.calls)
        self.assertEqual(self.keycloak.holders[ROLE], {B_MEMBER})

    def test_role_is_given_only_to_members_of_the_named_organisations(self):
        # A tenant file cannot give the role to a user of another tenant and lock that user out.
        with self.assertRaises(ApplyError) as raised:
            apply(self.keycloak, [{"subject": B_MEMBER, "realm_roles": [ROLE]}], [ORG_A])
        self.assertEqual(raised.exception.rule, "subject_not_member")
        self.assertFalse([c for c in self.keycloak.calls if c[0] != "GET"])
        self.assertNotIn(B_MEMBER, self.keycloak.holders[ROLE])

    def test_broken_keycloak_answers_stop_the_step_before_any_write(self):
        self.keycloak.holders[ROLE] = {FORMER}
        base = self.keycloak
        for broken, answer in (("/members?", (500, None)), ("/members?", (200, {"id": "x"})),
                               ("/members?", (200, [{"name": "no id"}])),
                               ("/organizations/members/", (403, None)),
                               ("/organizations/members/", (200, [None]))):
            with self.subTest(path=broken, answer=answer):
                calls = []

                def call(method, path, payload=None, broken=broken, answer=answer):
                    calls.append((method, path))
                    if method == "GET" and broken in path:
                        return answer
                    return base(method, path, payload)

                with self.assertRaises(ApplyError):
                    keycloak_apply.apply_realm_roles(call, roles_file([]), [ORG_A])
                self.assertFalse([c for c in calls if c[0] != "GET"])
        self.assertEqual(self.keycloak.holders[ROLE], {FORMER})

    def test_organisation_members_are_read_page_by_page(self):
        many = [user(f"u-{number:04d}", f"u{number}@acme.example") for number in range(230)]
        self.keycloak = FakeUsers(many, holders=[item["id"] for item in many], members={ORG_A: {i["id"] for i in many}})
        apply(self.keycloak, [], [ORG_A])
        self.assertEqual(self.keycloak.holders[ROLE], set())

    def test_file_without_organisations_takes_no_role_back(self):
        self.keycloak.holders[ROLE] = {MEMBER, FORMER, B_MEMBER}
        for document in ({"entries": []}, roles_file([], []), [], None):
            with self.subTest(document=document):
                self.keycloak.calls.clear()
                with self.assertRaises(ApplyError) as raised:
                    keycloak_apply.apply_realm_roles(self.keycloak, document, [ORG_A])
                self.assertEqual(raised.exception.rule, "organizations_missing")
                self.assertFalse([c for c in self.keycloak.calls if c[0] != "GET"])
        self.assertEqual(self.keycloak.holders[ROLE], {MEMBER, FORMER, B_MEMBER})

    def test_unknown_organisation_stops_the_step_before_any_write(self):
        self.keycloak.holders[ROLE] = {FORMER}
        with self.assertRaises(ApplyError) as raised:
            apply(self.keycloak, [], [ORG_A, "missing-org"])
        self.assertEqual(raised.exception.rule, "unknown_organization")
        self.assertEqual(self.keycloak.holders[ROLE], {FORMER})
        self.assertFalse([c for c in self.keycloak.calls if c[0] != "GET"])


class RoleCommandTest(unittest.TestCase):
    """The command needs the expected organisations from the operator with a roles file (AJA-391)."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "bin" / "atonota-login"
        loader = importlib.machinery.SourceFileLoader("atonota_login_command_roles", str(path))
        spec = importlib.util.spec_from_loader("atonota_login_command_roles", loader)
        cls.command = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.command)

    def run_command(self, keycloak, *arguments):
        local = {"KC_PUBLIC_URL": "http://identity.localhost:5280", "KC_BOOTSTRAP_ADMIN_USERNAME": "admin",
                 "KC_BOOTSTRAP_ADMIN_PASSWORD": "not-used"}
        loopback = [(2, 1, 6, "", ("127.0.0.1", 0))]
        output, errors = io.StringIO(), io.StringIO()
        caller = mock.Mock(return_value=keycloak)
        with mock.patch.dict("os.environ", local), mock.patch("socket.getaddrinfo", return_value=loopback), \
                mock.patch.object(keycloak_apply, "admin_caller", caller), \
                mock.patch.object(keycloak_apply, "apply_registry", return_value=[]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = self.command.main(["apply", "--from-env", *arguments])
        return code, output.getvalue(), errors.getvalue(), caller

    def roles_path(self, value):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "roles.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def setUp(self):
        self.keycloak = FakeUsers([user(MEMBER), user(B_MEMBER, "b@beta.example")],
                                  holders=[B_MEMBER], members={ORG_A: {MEMBER}, ORG_B: {B_MEMBER}})

    def test_roles_file_without_expected_organisation_stops_before_keycloak(self):
        code, _, errors, caller = self.run_command(self.keycloak, "--realm-roles", self.roles_path(roles_file([])))
        self.assertEqual(code, 2)
        self.assertIn("--organization", errors)
        caller.assert_not_called()

    def test_expected_organisation_without_roles_file_is_refused(self):
        code, _, _, caller = self.run_command(self.keycloak, "--organization", ORG_A)
        self.assertEqual(code, 2)
        caller.assert_not_called()

    def test_file_of_another_organisation_is_refused(self):
        path = self.roles_path(roles_file([], [ORG_B]))
        code, _, errors, _ = self.run_command(self.keycloak, "--realm-roles", path, "--organization", ORG_A)
        self.assertNotEqual(code, 0)
        self.assertIn("organization_not_allowed", errors)
        self.assertEqual(self.keycloak.holders[ROLE], {B_MEMBER})

    def test_tenant_file_gives_the_role_inside_the_tenant(self):
        path = self.roles_path(roles_file([{"subject": MEMBER, "realm_roles": [ROLE]}], [ORG_A]))
        code, output, _, _ = self.run_command(self.keycloak, "--realm-roles", path, "--organization", ORG_A)
        self.assertEqual(code, 0)
        self.assertIn(f"role {ROLE}: 1 added, 0 removed, 0 kept", output)
        self.assertEqual(self.keycloak.holders[ROLE], {MEMBER, B_MEMBER})


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
