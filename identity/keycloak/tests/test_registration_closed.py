"""G-79: Keycloak has no direct sign-up and rejects disposable email addresses. Keycloak is not needed.

Self sign-up opens only through the Press trial flow (`press_tr.api.trial.start`). The realm
must therefore close the Keycloak registration page. Press and Keycloak reject the same
disposable domains. The single list is in the press_tr app; this test keeps the realm in step.
"""

import json
import re
import unittest

from helpers import DIRECTORY, read_realm

DOMAIN_FILE = DIRECTORY.parents[1] / "apps/press_tr/press_tr/press_identity/disposable_email_domains.txt"
PROFILE_PROVIDER = "org.keycloak.userprofile.UserProfileProvider"
ERROR_KEY = "atDisposableEmail"


def listed_domains():
    lines = DOMAIN_FILE.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if line and not line.startswith("#")]


def email_attribute(realm):
    providers = realm.get("components", {}).get(PROFILE_PROVIDER, [])
    if len(providers) != 1:
        raise AssertionError(f"expected one user profile provider, found {len(providers)}")
    config = json.loads(providers[0]["config"]["kc.user.profile.config"][0])
    return {item["name"]: item for item in config["attributes"]}, config


class RegistrationClosedTest(unittest.TestCase):
    def test_direct_registration_is_closed(self):
        realm = read_realm()
        self.assertIs(realm["registrationAllowed"], False)

    def test_browser_flow_offers_no_registration_flow_override(self):
        # A client may not bring back the registration page through its own flow binding.
        for client in read_realm().get("clients", []):
            with self.subTest(client=client["clientId"]):
                self.assertNotIn("registration", client.get("authenticationFlowBindingOverrides", {}))


class DisposableEmailTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        realm = read_realm()
        cls.provider = realm["components"][PROFILE_PROVIDER][0]
        cls.attributes, cls.config = email_attribute(realm)
        cls.validator = cls.attributes["email"]["validations"]["pattern"]
        # Keycloak uses Java regex with `matches()`; this pattern uses only syntax Python reads the same way.
        cls.pattern = re.compile(cls.validator["pattern"])

    def accepted(self, address):
        return self.pattern.fullmatch(address) is not None

    def test_profile_keeps_the_default_attributes_and_checks(self):
        self.assertEqual(self.provider["providerId"], "declarative-user-profile")
        self.assertEqual(set(self.attributes), {"username", "email", "firstName", "lastName"})
        email = self.attributes["email"]
        self.assertIn("email", email["validations"])
        self.assertEqual(email["validations"]["length"], {"max": 255})
        self.assertEqual(email["required"], {"roles": ["user"]})
        self.assertNotIn("unmanagedAttributePolicy", self.config)

    def test_pattern_rejects_every_listed_domain_and_its_subdomains(self):
        domains = listed_domains()
        self.assertTrue(domains)
        for domain in domains:
            with self.subTest(domain=domain):
                self.assertFalse(self.accepted(f"person@{domain}"))
                self.assertFalse(self.accepted(f"Person@{domain.upper()}"))
                self.assertFalse(self.accepted(f"person@inbox.{domain}"))

    def test_pattern_names_exactly_the_listed_domains(self):
        names = re.search(r"\(\?:([a-z0-9|\\.-]+)\)\$", self.validator["pattern"]).group(1).split("|")
        self.assertEqual([name.replace("\\.", ".") for name in names], listed_domains())

    def test_pattern_accepts_permanent_and_lookalike_addresses(self):
        for address in (
            "person@example.test",
            "person@gmail.com",
            "person@notmailinator.com",
            "person@mailinator.com.tr",
            "mailinator.com@example.test",
        ):
            with self.subTest(address=address):
                self.assertTrue(self.accepted(address))

    def test_error_message_is_translated_in_the_login_theme(self):
        self.assertEqual(self.validator["error-message"], ERROR_KEY)
        for locale in ("tr", "en"):
            messages = DIRECTORY / "themes" / "atonota" / "login" / "messages" / f"messages_{locale}.properties"
            with self.subTest(locale=locale):
                self.assertRegex(messages.read_text(encoding="utf-8"), rf"(?m)^{ERROR_KEY}=\S")

    def test_pattern_has_no_import_placeholder(self):
        # Keycloak's realm import replaces ${NAME}. The pattern must not contain that form.
        self.assertNotIn("${", self.validator["pattern"])


if __name__ == "__main__":
    unittest.main()
