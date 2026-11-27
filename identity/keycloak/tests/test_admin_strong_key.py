"""G-163 item 1: a platform administrator signs in with a strong key on every login.

Expected behaviour comes from the G-163 requirement (src/data/requirements.json) and its technical design:
- A strong key is a passkey (webauthn-authenticator-passwordless) or a hardware key (webauthn-authenticator).
  TOTP is not a strong key.
- The realm role "platform-admin" marks a platform administrator. Frappe System Manager users get it by sync.
- ACR "admin" is level 2. Its step accepts only a strong key.
- A platform-admin user meets the strong key step on every login, whatever level the client asks for.
  The general second factor step (which offers TOTP) is skipped for this user.
- An administrator without a strong key cannot sign in and cannot add a key alone. The first key is added
  only after a realm administrator opens the registration (role "strong-key-enrollment").
- AJA-356: a user who has only a passkey is asked for it after the password.

Keycloak behaviour the flow relies on, read in the 26.8.2 source:
- ConditionalCredentialAuthenticator: "included" false (the default) matches when none of the listed
  credentials was used in this authentication session (AuthenticatorUtil.getAuthnCredentials).
- DefaultAuthenticationFlow.processSingleFlowExecutionModel: an ALTERNATIVE strong key step for a user
  without that key throws CREDENTIAL_SETUP_REQUIRED, it never adds a registration. Only a REQUIRED
  webauthn-authenticator step adds the "webauthn-register" required action (WebAuthnAuthenticatorFactory
  isUserSetupAllowed true; the passwordless factory returns false).
"""

from __future__ import annotations

import json
import re
import time
import unittest
import urllib.parse

from test_extensions import _cookie_opener, _follow_keycloak_redirect, _form_action, _open
from helpers import (
    admin,
    admin_token,
    get_environment_value,
    live_available,
    read_realm,
    read_users,
    tenant_authorize_url,
)

ADMIN_ROLE = "platform-admin"
ENROLLMENT_ROLE = "strong-key-enrollment"
STRONG_KEY_STEPS = {"webauthn-authenticator", "webauthn-authenticator-passwordless"}
SECOND_FACTOR_FLOWS = ("atonota-browser-2fa", "atonota-magic-link-2fa", "atonota-post-broker-2fa")

ADMIN_TOTP_USER = "yonetici.totp@example.test"
ADMIN_PASSKEY_USER = "yonetici.passkey@example.test"
ADMIN_ENROLLMENT_USER = "yonetici.kayit@example.test"
PASSKEY_USER = "passkey.ornek@example.test"
PLAIN_USER = "ayse.ornek@example.test"

# Sign-in values of the synthetic development users (realm/dev-users/platform-users-0.json).
SAMPLE_LOGIN = {
    ADMIN_TOTP_USER: "Ornek-Parola-Yonetici-Totp-2026",  # gitleaks:allow (synthetic test value, development realm only)
    ADMIN_PASSKEY_USER: "Ornek-Parola-Yonetici-Passkey-2026",  # gitleaks:allow (synthetic test value, development realm only)
    ADMIN_ENROLLMENT_USER: "Ornek-Parola-Yonetici-Kayit-2026",  # gitleaks:allow (synthetic test value, development realm only)
    PASSKEY_USER: "Ornek-Parola-Passkey-2026",  # gitleaks:allow (synthetic test value, development realm only)
    PLAIN_USER: "Ornek-Parola-Ayse-2026",  # gitleaks:allow (synthetic test value, development realm only)
}


def _flows(realm: dict) -> dict:
    return {f["alias"]: f for f in realm["authenticationFlows"]}


def _configs(realm: dict) -> dict:
    return {c["alias"]: c["config"] for c in realm["authenticatorConfig"]}


def _ordered(flow: dict) -> list:
    return sorted(flow["authenticationExecutions"], key=lambda e: e["priority"])


def _tree(flows: dict, alias: str) -> list:
    steps = []
    for execution in _ordered(flows[alias]):
        steps.append(execution)
        if execution.get("authenticatorFlow"):
            steps.extend(_tree(flows, execution["flowAlias"]))
    return steps


def _conditions(flows: dict, alias: str, provider: str) -> list:
    return [e for e in flows[alias]["authenticationExecutions"] if e.get("authenticator") == provider]


def _credential_list(config: dict) -> set:
    return set(config["credentials"].split("##"))


class AdminStrongKeyFileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.realm = read_realm()
        cls.flows = _flows(cls.realm)
        cls.configs = _configs(cls.realm)
        cls.clients = {c["clientId"]: c for c in cls.realm["clients"]}

    # Shared helpers --------------------------------------------------------------------------------

    def _role_condition(self, alias: str, role: str, negate: bool) -> bool:
        for condition in _conditions(self.flows, alias, "conditional-user-role"):
            config = self.configs[condition["authenticatorConfig"]]
            if config["condUserRole"] == role and config.get("negate", "false") == str(negate).lower():
                return condition["requirement"] == "REQUIRED"
        return False

    def _subflows(self, alias: str) -> list:
        return [e for e in _ordered(self.flows[alias]) if e.get("authenticatorFlow")]

    def _admin_flow(self, parent: str) -> str:
        """The CONDITIONAL subflow of `parent` that runs for platform-admin users."""
        found = [e["flowAlias"] for e in self._subflows(parent)
                 if e["requirement"] == "CONDITIONAL" and self._role_condition(e["flowAlias"], ADMIN_ROLE, False)]
        self.assertEqual(len(found), 1, f"{parent}: one platform-admin subflow expected, found {found}")
        return found[0]

    def _assert_strong_key_only(self, alias: str):
        """`alias` asks the user's strong key and nothing else; TOTP is never offered."""
        executions = [e for e in _ordered(self.flows[alias]) if not e.get("authenticatorFlow")]
        steps = {e["authenticator"]: e for e in executions if not e["authenticator"].startswith("conditional-")}
        self.assertEqual(set(steps), STRONG_KEY_STEPS, alias)
        for step in steps.values():
            # ALTERNATIVE: a missing key fails the step and never opens a registration.
            self.assertEqual(step["requirement"], "ALTERNATIVE", alias)
            self.assertFalse(step.get("userSetupAllowed"), alias)
        conditions = {e["authenticator"]: e for e in executions if e["authenticator"].startswith("conditional-")}
        self.assertEqual(set(conditions), {"conditional-user-configured"}, alias)
        self.assertEqual(conditions["conditional-user-configured"]["requirement"], "REQUIRED", alias)

    def _assert_key_or_deny(self, alias: str) -> str:
        """`alias` has a key step for users with a key and an explicit refusal for users without one.

        Returns the alias of the key step.
        """
        subflows = self._subflows(alias)
        self.assertTrue(all(e["requirement"] == "CONDITIONAL" for e in subflows), alias)
        key = [e["flowAlias"] for e in subflows if _conditions(self.flows, e["flowAlias"], "conditional-user-configured")]
        self.assertEqual(len(key), 1, alias)
        self._assert_strong_key_only(key[0])
        deny = [e["flowAlias"] for e in subflows
                if "deny-access-authenticator" in {s.get("authenticator") for s in self.flows[e["flowAlias"]]["authenticationExecutions"]}]
        self.assertEqual(len(deny), 1, f"{alias}: an explicit refusal is expected")
        not_run = [self.configs[c["authenticatorConfig"]]
                   for c in _conditions(self.flows, deny[0], "conditional-sub-flow-executed")]
        self.assertIn({"flow_to_check": key[0], "check_result": "not-executed"}, not_run, deny[0])
        return key[0]

    # Role and level --------------------------------------------------------------------------------

    def test_platform_admin_and_enrollment_roles_exist(self):
        roles = {r["name"]: r for r in self.realm["roles"]["realm"]}
        for name in (ADMIN_ROLE, ENROLLMENT_ROLE):
            with self.subTest(role=name):
                self.assertIn(name, roles)
                self.assertFalse(roles[name]["composite"])
                self.assertTrue(roles[name].get("description"))
        default = next(r for r in self.realm["roles"]["realm"] if r["name"] == "default-roles-platform")
        self.assertNotIn(ADMIN_ROLE, default["composites"]["realm"])
        self.assertNotIn(ENROLLMENT_ROLE, default["composites"]["realm"])

    def test_tenant_client_maps_admin_to_level_two(self):
        attributes = self.clients["site-tenant1"]["attributes"]
        self.assertEqual(json.loads(attributes["acr.loa.map"]), {"employee": 1, "admin": 2})
        self.assertEqual(attributes["default.acr.values"], "employee")
        self.assertEqual(attributes["minimum.acr.value"], "employee")

    def test_new_tenant_clients_get_the_same_level_map(self):
        import importlib.util

        from helpers import DIRECTORY

        spec = importlib.util.spec_from_file_location("create_tenant_client", DIRECTORY / "bin" / "create-tenant-client.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        client = module.tenant_client("ornek", "https://ornek.example.test")
        self.assertEqual(json.loads(client["attributes"]["acr.loa.map"]), {"employee": 1, "admin": 2})
        self.assertEqual(client["attributes"]["minimum.acr.value"], "employee")

    def test_level_two_accepts_only_a_strong_key(self):
        login = [e for e in self._subflows("atonota-browser-giris") if e["requirement"] == "CONDITIONAL"]
        level_two = []
        for execution in login:
            for condition in _conditions(self.flows, execution["flowAlias"], "conditional-level-of-authentication"):
                config = self.configs[condition["authenticatorConfig"]]
                if config["loa-condition-level"] == "2":
                    level_two.append((execution["flowAlias"], config))
        self.assertEqual(len(level_two), 1, "one level 2 subflow expected in atonota-browser-giris")
        alias, config = level_two[0]
        # max age 0: a request for ACR admin always meets the key again.
        self.assertEqual(config["loa-max-age"], "0")
        self._assert_key_or_deny(alias)
        self.assertNotIn("auth-otp-form", {e.get("authenticator") for e in _tree(self.flows, alias)})

    def test_level_one_subflow_stays_first(self):
        first = _ordered(self.flows["atonota-browser-giris"])[0]
        self.assertEqual(first["flowAlias"], "atonota-browser-level")
        # The level 2 and the administrator steps come after the user is known.
        aliases = [e["flowAlias"] for e in self._subflows("atonota-browser-giris")]
        self.assertEqual(aliases[0], "atonota-browser-level")
        self.assertEqual(len(aliases), 3, aliases)

    # Administrator on every login ------------------------------------------------------------------

    def test_browser_admin_subflow_forces_a_strong_key_on_every_login(self):
        alias = self._admin_flow("atonota-browser-giris")
        # No level condition: the step runs whatever level the client asked for.
        self.assertFalse(_conditions(self.flows, alias, "conditional-level-of-authentication"))
        credential = _conditions(self.flows, alias, "conditional-credential")
        self.assertEqual(len(credential), 1, alias)
        config = self.configs[credential[0]["authenticatorConfig"]]
        # Skipped only when a strong key was already used in this login (the level 2 step or a passkey sign-in).
        self.assertEqual(_credential_list(config), {"webauthn", "webauthn-passwordless"})
        self.assertEqual(config.get("included", "false"), "false")
        self._assert_key_or_deny_or_enrollment(alias)

    def _assert_key_or_deny_or_enrollment(self, alias: str):
        subflows = self._subflows(alias)
        key = [e["flowAlias"] for e in subflows if _conditions(self.flows, e["flowAlias"], "conditional-user-configured")]
        self.assertEqual(len(key), 1, alias)
        self._assert_strong_key_only(key[0])
        enrollment = [e["flowAlias"] for e in subflows if self._role_condition(e["flowAlias"], ENROLLMENT_ROLE, False)]
        self.assertEqual(len(enrollment), 1, f"{alias}: one enrollment subflow expected")
        deny = [e["flowAlias"] for e in subflows
                if "deny-access-authenticator" in {s.get("authenticator") for s in self.flows[e["flowAlias"]]["authenticationExecutions"]}]
        self.assertEqual(len(deny), 1, f"{alias}: an explicit refusal is expected")
        not_run = [self.configs[c["authenticatorConfig"]]
                   for c in _conditions(self.flows, deny[0], "conditional-sub-flow-executed")]
        self.assertIn({"flow_to_check": key[0], "check_result": "not-executed"}, not_run)
        self.assertIn({"flow_to_check": enrollment[0], "check_result": "not-executed"}, not_run)
        self.assertTrue(all(e["requirement"] == "CONDITIONAL" for e in subflows), alias)

    def test_enrollment_needs_the_role_the_password_and_no_existing_key(self):
        admin_flow = self._admin_flow("atonota-browser-giris")
        key = next(e["flowAlias"] for e in self._subflows(admin_flow)
                   if _conditions(self.flows, e["flowAlias"], "conditional-user-configured"))
        alias = next(e["flowAlias"] for e in self._subflows(admin_flow)
                     if self._role_condition(e["flowAlias"], ENROLLMENT_ROLE, False))
        not_run = [self.configs[c["authenticatorConfig"]] for c in _conditions(self.flows, alias, "conditional-sub-flow-executed")]
        # An administrator who already has a key is asked for it; the open registration does not replace it.
        self.assertIn({"flow_to_check": key, "check_result": "not-executed"}, not_run)
        used = [self.configs[c["authenticatorConfig"]] for c in _conditions(self.flows, alias, "conditional-credential")]
        # The email link alone never adds a strong key (G-163): the password must have been used.
        self.assertIn({"credentials": "password", "included": "true"}, used)
        steps = [e for e in _ordered(self.flows[alias]) if not e.get("authenticatorFlow")
                 and not e["authenticator"].startswith("conditional-")]
        self.assertEqual([(e["authenticator"], e["requirement"]) for e in steps], [("webauthn-authenticator", "REQUIRED")])

    def test_only_the_enrollment_step_can_open_a_key_registration(self):
        admin_flow = self._admin_flow("atonota-browser-giris")
        enrollment = next(e["flowAlias"] for e in self._subflows(admin_flow)
                          if self._role_condition(e["flowAlias"], ENROLLMENT_ROLE, False))
        for flow in self.realm["authenticationFlows"]:
            for execution in flow["authenticationExecutions"]:
                if execution.get("authenticator") in STRONG_KEY_STEPS and execution["requirement"] == "REQUIRED":
                    with self.subTest(flow=flow["alias"]):
                        self.assertEqual(flow["alias"], enrollment)

    def test_admin_key_steps_never_offer_totp(self):
        admin_flow = self._admin_flow("atonota-browser-giris")
        for alias in (admin_flow, self._admin_flow("atonota-post-broker")):
            for execution in self._subflows(alias):
                if _conditions(self.flows, execution["flowAlias"], "conditional-user-configured") and \
                        not self._role_condition(execution["flowAlias"], ENROLLMENT_ROLE, False):
                    with self.subTest(flow=execution["flowAlias"]):
                        names = {e.get("authenticator") for e in _tree(self.flows, execution["flowAlias"])}
                        self.assertNotIn("auth-otp-form", names)

    def test_second_factor_subflows_skip_platform_admins(self):
        for alias in SECOND_FACTOR_FLOWS:
            with self.subTest(flow=alias):
                self.assertTrue(self._role_condition(alias, ADMIN_ROLE, True), f"{alias}: negated platform-admin condition")

    def test_post_broker_forces_a_strong_key_for_admins(self):
        executions = _ordered(self.flows["atonota-post-broker"])
        alias = self._admin_flow("atonota-post-broker")
        position = [e.get("flowAlias") for e in executions].index(alias)
        allow = [e.get("authenticator") for e in executions].index("allow-access-authenticator")
        self.assertLess(position, allow)
        credential = _conditions(self.flows, alias, "conditional-credential")
        self.assertEqual(len(credential), 1, alias)
        self.assertEqual(_credential_list(self.configs[credential[0]["authenticatorConfig"]]), {"webauthn", "webauthn-passwordless"})
        # Social sign-in has no registration path: the key step or the refusal.
        self._assert_key_or_deny(alias)

    # AJA-356 ---------------------------------------------------------------------------------------

    def test_passkey_only_user_is_asked_after_the_password(self):
        for alias in SECOND_FACTOR_FLOWS:
            with self.subTest(flow=alias):
                executions = {e.get("authenticator"): e for e in self.flows[alias]["authenticationExecutions"]}
                self.assertIn("webauthn-authenticator-passwordless", executions)
                self.assertEqual(executions["webauthn-authenticator-passwordless"]["requirement"], "ALTERNATIVE")
                # conditional-user-configured counts the passkey step, so a passkey-only user is asked.
                self.assertEqual(executions["conditional-user-configured"]["requirement"], "REQUIRED")

    # Structure -------------------------------------------------------------------------------------

    def test_every_flow_reference_and_config_exists(self):
        aliases = set(self.flows)
        referenced = []
        for flow in self.realm["authenticationFlows"]:
            for execution in flow["authenticationExecutions"]:
                if execution.get("authenticatorFlow"):
                    self.assertIn(execution["flowAlias"], aliases, flow["alias"])
                    referenced.append(execution["flowAlias"])
                if execution.get("authenticatorConfig"):
                    self.assertIn(execution["authenticatorConfig"], self.configs, flow["alias"])
        # A subflow used twice would share execution state between two places.
        self.assertEqual(len(referenced), len(set(referenced)))
        for config in self.configs.values():
            if "flow_to_check" in config:
                self.assertIn(config["flow_to_check"], aliases)

    def test_development_users_for_the_live_tests(self):
        users = {u["username"]: u for u in read_users()["users"]}
        for name in (ADMIN_TOTP_USER, ADMIN_PASSKEY_USER, ADMIN_ENROLLMENT_USER):
            with self.subTest(user=name):
                self.assertIn(ADMIN_ROLE, users[name]["realmRoles"])
        self.assertIn(ENROLLMENT_ROLE, users[ADMIN_ENROLLMENT_USER]["realmRoles"])
        self.assertNotIn(ENROLLMENT_ROLE, users[ADMIN_TOTP_USER]["realmRoles"])
        types = {name: {c["type"] for c in users[name]["credentials"]} for name in users}
        self.assertEqual(types[ADMIN_TOTP_USER], {"password", "otp"})
        self.assertEqual(types[ADMIN_PASSKEY_USER], {"password", "otp", "webauthn-passwordless"})
        self.assertEqual(types[ADMIN_ENROLLMENT_USER], {"password"})
        self.assertEqual(types[PASSKEY_USER], {"password", "webauthn-passwordless"})
        self.assertNotIn(ADMIN_ROLE, users[PASSKEY_USER]["realmRoles"])


# Live tests ----------------------------------------------------------------------------------------

WEBAUTHN_LOGIN = 'name="authenticatorData"'
WEBAUTHN_REGISTER = 'name="attestationObject"'


@unittest.skipUnless(live_available(), "KC_PUBLIC_URL missing, live Keycloak test skipped")
class AdminStrongKeyLiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kc = get_environment_value("KC_PUBLIC_URL")

    def setUp(self):
        self.admin_token = admin_token()
        for email in (ADMIN_TOTP_USER, ADMIN_PASSKEY_USER, ADMIN_ENROLLMENT_USER, PASSKEY_USER, PLAIN_USER):
            admin(f"/attack-detection/brute-force/users/{self._user(email)['id']}", self.admin_token, method="DELETE")

    def _user(self, email: str) -> dict:
        found = admin(f"/users?email={urllib.parse.quote(email)}&exact=true", self.admin_token).json()
        self.assertEqual(len(found), 1, f"development user {email} missing")
        return found[0]

    def _post(self, action: str, form: dict):
        return _open(self._opener, action, urllib.parse.urlencode(form).encode())

    def _password_step(self, email: str, authorize_url: str | None = None):
        time.sleep(1.2)  # quickLoginCheckMilliSeconds: two attempts within a second lock the user.
        opener = self._opener = _cookie_opener()
        status, _, html = _open(opener, authorize_url or tenant_authorize_url())
        self.assertEqual(status, 200)
        form = urllib.parse.urlencode({"username": email, "password": SAMPLE_LOGIN[email], "credentialId": ""}).encode()
        status, headers, html = _open(opener, _form_action(html), form)
        if status in (302, 303) and headers.get("Location", "").startswith(self.kc):
            # A Keycloak page that follows (a required action) is reached by a redirect inside Keycloak.
            status, headers, html = _follow_keycloak_redirect(opener, headers["Location"], self.kc)
        return status, headers, html

    def _assert_no_code(self, status: int, headers: dict):
        self.assertFalse("code=" in headers.get("Location", ""), f"HTTP {status}: no authorization code expected")

    def _assert_refused(self, html: str):
        """The login ended on Keycloak's error page: no form for a further step remains."""
        self.assertIn('data-page-id="login-error"', html)
        self.assertIsNone(re.search(r'action="[^"]*login-actions/authenticate', html), "no further login step expected")

    def test_server_has_the_roles_and_the_level_map(self):
        for role in (ADMIN_ROLE, ENROLLMENT_ROLE):
            self.assertEqual(admin(f"/roles/{role}", self.admin_token).status, 200, role)
        client = admin("/clients?clientId=site-tenant1", self.admin_token).json()[0]
        self.assertEqual(json.loads(client["attributes"]["acr.loa.map"]), {"employee": 1, "admin": 2})
        roles = {r["name"] for r in admin(f"/users/{self._user(ADMIN_TOTP_USER)['id']}/role-mappings/realm", self.admin_token).json()}
        self.assertIn(ADMIN_ROLE, roles)

    def test_admin_with_password_and_totp_is_refused(self):
        status, headers, html = self._password_step(ADMIN_TOTP_USER)
        self._assert_no_code(status, headers)
        self.assertNotIn('name="otp"', html, "TOTP is not a strong key and must not be offered to an administrator")
        self.assertNotIn(WEBAUTHN_REGISTER, html, "an administrator must not register a key alone")
        self.assertNotIn('name="password"', html, "the password was right; the refusal comes from the key step")
        self.assertNotIn(WEBAUTHN_LOGIN, html)
        self._assert_refused(html)

    def test_admin_without_key_is_refused_even_with_a_registration_action(self):
        """A realm administrator setting the required action alone does not open the login."""
        user = self._user(ADMIN_TOTP_USER)
        detail = admin(f"/users/{user['id']}", self.admin_token).json()
        original = list(detail.get("requiredActions", []))
        detail["requiredActions"] = ["webauthn-register-passwordless"]
        self.assertEqual(admin(f"/users/{user['id']}", self.admin_token, "PUT", detail).status, 204)
        self.addCleanup(self._restore_actions, user["id"], original)
        status, headers, html = self._password_step(ADMIN_TOTP_USER)
        self._assert_no_code(status, headers)
        self.assertNotIn(WEBAUTHN_REGISTER, html)
        self.assertNotIn('name="otp"', html, "TOTP is not a strong key")
        self.assertNotIn("login-actions/required-action", headers.get("Location", "") + html)
        self._assert_refused(html)

    def _restore_actions(self, user_id: str, original: list):
        token = admin_token()
        detail = admin(f"/users/{user_id}", token).json()
        detail["requiredActions"] = original
        admin(f"/users/{user_id}", token, "PUT", detail)

    def test_admin_with_a_passkey_gets_the_key_step_not_totp(self):
        status, headers, html = self._password_step(ADMIN_PASSKEY_USER)
        self._assert_no_code(status, headers)
        self.assertEqual(status, 200)
        self.assertNotIn('name="password"', html)
        self.assertIn(WEBAUTHN_LOGIN, html, "the strong key step must follow the password")
        self.assertNotIn('name="otp"', html, "the administrator also has TOTP, which must not be offered")

    def test_admin_with_a_level_one_request_still_gets_the_key_step(self):
        url = tenant_authorize_url() + "&acr_values=employee"
        status, headers, html = self._password_step(ADMIN_PASSKEY_USER, url)
        self._assert_no_code(status, headers)
        self.assertIn(WEBAUTHN_LOGIN, html)
        self.assertNotIn('name="otp"', html)

    def test_level_two_request_refuses_a_user_without_a_strong_key(self):
        url = tenant_authorize_url() + "&acr_values=admin"
        status, headers, html = self._password_step(PLAIN_USER, url)
        self._assert_no_code(status, headers)
        self.assertNotIn('name="password"', html)
        self.assertNotIn(WEBAUTHN_REGISTER, html)
        self._assert_refused(html)

    def test_passkey_only_user_gets_a_second_step_after_the_password(self):
        status, headers, html = self._password_step(PASSKEY_USER)
        self._assert_no_code(status, headers)
        self.assertEqual(status, 200)
        self.assertNotIn('name="password"', html)
        self.assertIn(WEBAUTHN_LOGIN, html, "the passkey must be asked after the password (AJA-356)")

    def test_open_enrollment_shows_the_registration_after_the_password(self):
        status, headers, html = self._password_step(ADMIN_ENROLLMENT_USER)
        self._assert_no_code(status, headers)
        self.assertIn(WEBAUTHN_REGISTER, html, "the realm administrator opened the registration for this user")
        # The registration page has no way to skip the key.
        self.assertIsNone(re.search(r'name="cancel-aia"', html))
        action = re.search(r'<form[^>]*id="register"[^>]*action="([^"]+)"', html).group(1).replace("&amp;", "&")
        for attempt in ({"cancel-aia": "true"}, {"error": "NotAllowedError"}, {}):
            with self.subTest(attempt=attempt):
                status, headers, _ = self._post(action, attempt)
                self._assert_no_code(status, headers)

    def test_magic_link_never_opens_the_enrollment(self):
        """The email link alone must not add a strong key (G-163), even when the registration is open."""
        from test_magic_link import Mailpit, _magic_link_execution_id

        mailpit = Mailpit(f"http://127.0.0.1:{get_environment_value('MAILPIT_UI_PORT')}")
        mailpit.clear()
        execution_id = _magic_link_execution_id(self.admin_token)
        opener = _cookie_opener()
        _, _, html = _open(opener, tenant_authorize_url())
        _, _, html = _open(opener, _form_action(html), urllib.parse.urlencode({"tryAnotherWay": "on"}).encode())
        _, _, html = _open(opener, _form_action(html), urllib.parse.urlencode({"authenticationExecution": execution_id}).encode())
        _open(opener, _form_action(html), urllib.parse.urlencode({"username": ADMIN_ENROLLMENT_USER}).encode())
        link = mailpit.latest_link(ADMIN_ENROLLMENT_USER)
        status, headers, html = _follow_keycloak_redirect(opener, link, self.kc)
        self._assert_no_code(status, headers)
        self.assertNotIn(WEBAUTHN_REGISTER, html)
        self._assert_refused(html)


if __name__ == "__main__":
    unittest.main()
