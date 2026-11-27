"""G-79: the trial start, the team invitation and the disposable email rule.

Expected behaviour comes from AJA-2287 and the G-79 requirement:
- self sign-up opens only through `press_tr.api.trial.start`, Keycloak registration is closed;
- a disposable email address is rejected in Press and in Keycloak;
- `press_tr.api.team.invite` asks identity-sync for an invitation preview. Only the approval
  layer executes an invitation (contracts/identity_sync.openapi.yaml, `/v1/invitations`).

The tests need Frappe but no site and no Press source. Press modules are stand-ins.
"""

import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import frappe
import requests
from werkzeug.exceptions import BadGateway, ServiceUnavailable

try:
	import press
except ImportError:
	# A fast run without the Press bench. press_tr imports the Team class when it loads.
	for name in ("press", "press.api", "press.press", "press.press.doctype", "press.press.doctype.team"):
		sys.modules.setdefault(name, ModuleType(name))
	team_module = sys.modules.setdefault(
		"press.press.doctype.team.team", ModuleType("press.press.doctype.team.team")
	)
	team_module.Team = getattr(team_module, "Team", type("Team", (), {}))

APP = Path(__file__).resolve().parents[1] / "press_tr"
REPOSITORY = Path(__file__).resolve().parents[3]
DOMAIN_FILE = APP / "press_identity/disposable_email_domains.txt"
CONTRACT = REPOSITORY / "contracts/press_tr.openapi.yaml"
TRIAL_ROUTE = "/api/method/press_tr.api.trial.start"
INVITE_ROUTE = "/api/method/press_tr.api.team.invite"
INVITE_FIELDS = {"email", "first_name", "last_name"}


def translate(message, *args, **kwargs):
	return message


def raise_exception(message, exception=frappe.ValidationError, *args, **kwargs):
	raise exception(message)


def _facade(form, *, user="owner@example.test", csrf="token-1"):
	facade = Mock()
	facade.form_dict = dict(form)
	facade.session = SimpleNamespace(user=user, data={"csrf_token": "token-1"}, sid="sid-1")
	facade.get_request_header.side_effect = lambda name, default=None: (
		csrf if name == "X-Frappe-CSRF-Token" else default
	)
	facade.local.team.return_value = SimpleNamespace(name="team-a", custom_ptr_keycloak_org_id="org-1")
	facade.throw.side_effect = raise_exception
	facade.ValidationError = frappe.ValidationError
	facade.PermissionError = frappe.PermissionError
	facade.DoesNotExistError = frappe.DoesNotExistError
	facade.conf = SimpleNamespace(
		identity_sync_url="https://identity-sync.example.test", press_service_client_secret="client-secret"
	)
	return facade


def _press_modules(*, owner=True, admin=False, request=None):
	"""Stand-ins for the pinned Press functions that the endpoints call."""
	utils = ModuleType("press.utils")
	utils.is_team_owner = Mock(return_value=owner)
	utils.is_admin_user = Mock(return_value=admin)
	product_trial = ModuleType("press.api.product_trial")
	product_trial._get_or_create_site_request = Mock(
		return_value=request
		or SimpleNamespace(name="ptr-1", site=None, status="Pending", product_trial="erp")
	)
	modules = {
		"press.utils": utils,
		"press.api.product_trial": product_trial,
	}
	return modules, utils, product_trial


class DisposableEmailTest(unittest.TestCase):
	def setUp(self):
		from press_tr.press_identity import disposable_email

		self.rule = disposable_email

	def test_domain_file_is_sorted_lowercase_and_unique(self):
		lines = [
			line for line in DOMAIN_FILE.read_text(encoding="utf-8").splitlines() if not line.startswith("#")
		]
		self.assertTrue(lines)
		self.assertEqual(lines, sorted(set(lines)))
		for domain in lines:
			with self.subTest(domain=domain):
				self.assertEqual(domain, domain.strip().lower())
				self.assertRegex(domain, r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
		self.assertEqual(self.rule.DOMAINS, frozenset(lines))

	def test_listed_domain_and_its_subdomain_are_disposable(self):
		for address in (
			"person@mailinator.com",
			"Person@MAILINATOR.COM",
			"  person@yopmail.com ",
			"person@inbox.mailinator.com",
			"person@mailinator.com.",
		):
			with self.subTest(address=address):
				self.assertTrue(self.rule.is_disposable(address))

	def test_permanent_and_lookalike_domains_are_not_disposable(self):
		for address in (
			"person@example.test",
			"person@gmail.com",
			"person@notmailinator.com",
			"person@mailinator.com.tr",
			"mailinator.com@example.test",
		):
			with self.subTest(address=address):
				self.assertFalse(self.rule.is_disposable(address))

	def test_reject_raises_a_translated_validation_error(self):
		facade = _facade({})
		with patch.object(self.rule, "frappe", facade), patch.object(self.rule, "_", side_effect=translate):
			with self.assertRaises(frappe.ValidationError):
				self.rule.reject_disposable("person@mailinator.com")
			self.rule.reject_disposable("person@example.test")


class TrialStartTest(unittest.TestCase):
	def setUp(self):
		from press_tr.api import trial
		from press_tr.press_identity import customer

		self.trial = trial
		self.customer = customer

	def call(self, form, *, owner=True, admin=False, user="owner@example.test", csrf="token-1", product=None):
		facade = _facade(form, user=user, csrf=csrf)
		facade.db.get_value.return_value = product if product is not None else 1
		modules, _utils, product_trial = _press_modules(owner=owner, admin=admin)
		with (
			patch.dict(sys.modules, modules),
			patch.object(self.trial, "frappe", facade),
			patch.object(self.customer, "frappe", facade),
			patch.object(self.trial, "_", side_effect=translate),
			patch.object(self.customer, "_", side_effect=translate),
			patch.object(self.customer, "human_identity", return_value=SimpleNamespace(name="link-1")),
			patch("press_tr.press_identity.disposable_email.frappe", facade),
			patch("press_tr.press_identity.disposable_email._", side_effect=translate),
		):
			result = self.trial.start(**{k: v for k, v in form.items() if k == "product"})
		return result, facade, product_trial

	def test_owner_gets_the_trial_request_of_the_own_team(self):
		result, facade, product_trial = self.call({"cmd": "press_tr.api.trial.start", "product": "erp"})
		product_trial._get_or_create_site_request.assert_called_once_with("erp", "team-a", None)
		self.assertEqual(result, {"name": "ptr-1", "site": None, "status": "Pending", "product_trial": "erp"})
		facade.db.get_value.assert_called_once_with("Product Trial", "erp", "published")

	def test_admin_member_can_start_a_trial(self):
		result, _, _module = self.call({"product": "erp"}, owner=False, admin=True)
		self.assertEqual(result["name"], "ptr-1")

	def test_member_without_admin_access_is_denied(self):
		with self.assertRaises(frappe.PermissionError):
			self.call({"product": "erp"}, owner=False, admin=False)

	def test_disposable_session_email_is_rejected_before_any_write(self):
		with self.assertRaises(frappe.ValidationError):
			self.call({"product": "erp"}, user="person@mailinator.com")

	def test_unpublished_or_unknown_product_is_rejected(self):
		for value in (0, None):
			with self.subTest(published=value), self.assertRaises(frappe.DoesNotExistError):
				facade = _facade({"product": "erp"})
				facade.db.get_value.return_value = value
				modules, _utils, product_trial = _press_modules()
				with (
					patch.dict(sys.modules, modules),
					patch.object(self.trial, "frappe", facade),
					patch.object(self.customer, "frappe", facade),
					patch.object(self.trial, "_", side_effect=translate),
					patch.object(self.customer, "human_identity", return_value=SimpleNamespace(name="l")),
					patch("press_tr.press_identity.disposable_email.frappe", facade),
				):
					try:
						self.trial.start(product="erp")
					finally:
						product_trial._get_or_create_site_request.assert_not_called()

	def test_missing_csrf_token_is_denied(self):
		with self.assertRaises(frappe.PermissionError):
			self.call({"product": "erp"}, csrf="")

	def test_extra_field_is_denied(self):
		with self.assertRaises(frappe.PermissionError):
			self.call({"product": "erp", "team": "team-b"})

	def test_product_must_be_short_text(self):
		for product in ("", 5, "x" * 141):
			with self.subTest(product=product), self.assertRaises(frappe.PermissionError):
				self.call({"product": product})


class TeamInviteTest(unittest.TestCase):
	def setUp(self):
		from press_tr.api import team
		from press_tr.press_identity import customer, invitations

		self.team = team
		self.customer = customer
		self.invitations = invitations

	def response(self, status=200, body=None):
		response = Mock(status_code=status)
		response.json.return_value = (
			body
			if body is not None
			else {
				"subject": None,
				"previews": [{"operation": "keycloak.create_user"}],
				"preview_digest": "d" * 64,
			}
		)
		return response

	def call(self, form, *, owner=True, admin=False, response=None, org_id="org-1", post=None):
		facade = _facade(form)
		facade.local.team.return_value = SimpleNamespace(name="team-a", custom_ptr_keycloak_org_id=org_id)
		modules, _utils, _trial = _press_modules(owner=owner, admin=admin)
		post = post or Mock(return_value=response or self.response())
		with (
			patch.dict(sys.modules, modules),
			patch.object(self.team, "frappe", facade),
			patch.object(self.customer, "frappe", facade),
			patch.object(self.invitations, "frappe", facade),
			patch.object(self.team, "_", side_effect=translate),
			patch.object(self.customer, "_", side_effect=translate),
			patch.object(self.invitations, "_", side_effect=translate),
			patch.object(self.customer, "human_identity", return_value=SimpleNamespace(name="link-1")),
			patch.object(self.invitations, "service_token", return_value="service-token"),
			patch.object(self.invitations.requests, "post", post),
			patch("press_tr.press_identity.disposable_email.frappe", facade),
			patch("press_tr.press_identity.disposable_email._", side_effect=translate),
		):
			result = self.team.invite(**{k: v for k, v in form.items() if k in INVITE_FIELDS})
		return result, post

	def test_admin_gets_an_invitation_preview_for_the_own_organization(self):
		result, post = self.call(
			{"email": " New.Member@Example.test ", "first_name": "New", "last_name": "Member"},
			owner=False,
			admin=True,
		)
		post.assert_called_once()
		self.assertEqual(post.call_args.args, ("https://identity-sync.example.test/v1/invitations",))
		self.assertEqual(
			post.call_args.kwargs["json"],
			{
				"email": "new.member@example.test",
				"first_name": "New",
				"last_name": "Member",
				"organization_id": "org-1",
				"dry_run": True,
			},
		)
		self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer service-token"})
		self.assertFalse(post.call_args.kwargs["allow_redirects"])
		self.assertEqual(
			result,
			{
				"subject": None,
				"previews": [{"operation": "keycloak.create_user"}],
				"preview_digest": "d" * 64,
			},
		)

	def test_invitation_never_asks_for_execution(self):
		_result, post = self.call({"email": "member@example.test"})
		self.assertIs(post.call_args.kwargs["json"]["dry_run"], True)
		self.assertNotIn("approval_id", post.call_args.kwargs["json"])

	def test_disposable_invitee_is_rejected_without_calling_identity_sync(self):
		post = Mock()
		with self.assertRaises(frappe.ValidationError):
			self.call({"email": "member@sharklasers.com"}, post=post)
		post.assert_not_called()

	def test_member_without_admin_access_is_denied(self):
		post = Mock()
		with self.assertRaises(frappe.PermissionError):
			self.call({"email": "member@example.test"}, owner=False, admin=False, post=post)
		post.assert_not_called()

	def test_invalid_email_is_rejected(self):
		for email in ("", "no-at-sign", "a@b@c", "a" * 65 + "@example.test", 7):
			with self.subTest(email=email), self.assertRaises(frappe.ValidationError):
				self.call({"email": email}, post=Mock())

	def test_extra_field_is_denied(self):
		with self.assertRaises(frappe.PermissionError):
			self.call({"email": "member@example.test", "organization_id": "org-2"}, post=Mock())

	def test_team_without_keycloak_organization_is_unavailable(self):
		with self.assertRaises(ServiceUnavailable):
			self.call({"email": "member@example.test"}, org_id=None, post=Mock())

	def test_identity_sync_error_becomes_bad_gateway(self):
		for post in (
			Mock(return_value=self.response(403, {"error": "forbidden"})),
			Mock(return_value=self.response(200, {"previews": "x"})),
			Mock(side_effect=requests.ConnectionError()),
		):
			with self.subTest(post=post), self.assertRaises(BadGateway):
				self.call({"email": "member@example.test"}, post=post)


class ContractAndRouteTest(unittest.TestCase):
	def test_customer_routes_are_documented_for_press_allowlist(self):
		from press_tr.press_identity import request_policy

		self.assertIn("press_tr.api.trial.start", request_policy.CUSTOMER_METHODS)
		self.assertIn("press_tr.api.team.invite", request_policy.CUSTOMER_METHODS)
		self.assertNotIn("press_tr.api.trial.start", request_policy.GUEST_METHODS)
		self.assertNotIn("press_tr.api.team.invite", request_policy.GUEST_METHODS)

	def test_contract_lists_both_endpoints(self):
		text = CONTRACT.read_text(encoding="utf-8")
		for route, operation in ((TRIAL_ROUTE, "startTrial"), (INVITE_ROUTE, "inviteTeamMember")):
			with self.subTest(route=route):
				self.assertIn(f"  {route}:\n    post:\n      operationId: {operation}\n", text)


if __name__ == "__main__":
	unittest.main()
