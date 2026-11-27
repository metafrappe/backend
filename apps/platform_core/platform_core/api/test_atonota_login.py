"""`atonota_login` action decision endpoints over the real HTTP path (G-161, G-166, AJA-230).

Expected behavior comes from the contract (`contracts/platform_core-identity.openapi.yaml`, tag
`atonota-login`) and the architecture note of AJA-213:
- only a signed-in user may call the endpoints; a guest gets 403 and `PermissionError`,
- the server collects the evidence from Frappe records; body fields such as `evidence` or `user` change nothing,
- `configuration_required` opens one task for the rule owner,
- the paid plan gate follows the plan decision (AJA-18): Starter and Growth need membership and a
  payment card, Enterprise is never self-service, an unknown plan is refused,
- the server has no card source yet (no Team Tier code), so no caller and no role passes the gate,
- a refusal writes no plan record and no billing record,
- a passed gate still writes nothing: the P2 billing flow is not connected (`BillingNotConnected`).
"""

import json
import secrets
from unittest import mock

import frappe
from atonota_login import decision
from frappe.tests import IntegrationTestCase
from frappe.tests.test_api import make_request
from frappe.utils import get_test_client
from frappe.utils.password import update_password

from platform_core.api import test_atonota_verification as notice
from platform_core.identity.atonota import decision_api, verification_api
from platform_core.identity.tests import helpers as h

API = "/api/method/platform_core.api.atonota_login."
# Fresh test password for each run. It has upper case, lower case, digits and a symbol.
PASSWORD = f"Sahte-{secrets.token_hex(8)}-Ak!"
MEMBER = "atonota.member@example.test"
VISITOR = "atonota.visitor@example.test"
MANAGER = "atonota.manager@example.test"
USERS = (MEMBER, VISITOR, MANAGER)
FAR_FUTURE = {"status": "valid", "expiresAt": "2099-01-01T00:00:00+00:00"}
# Plan and billing records of ERPNext. None of them may appear when the gate refuses (G-166).
PLAN_AND_BILLING_DOCTYPES = (
	"Subscription Plan",
	"Subscription",
	"Payment Request",
	"Payment Entry",
	"Sales Invoice",
)


def owner_tasks() -> list:
	return frappe.get_all(
		"ToDo",
		filters={"status": "Open", "description": ("like", f"%{decision_api.TASK_MARK}%")},
		fields=["name", "description", "role", "allocated_to"],
	)


class TestAtonotaLoginEndpoints(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		h.clear_links(*USERS)
		cls.addClassCleanup(h.clear_links, *USERS)
		h.ensure_user(MEMBER, user_type="System User")
		h.ensure_user(VISITOR, user_type="Website User")
		h.ensure_user(MANAGER, user_type="System User", roles=["System Manager"])
		for user in USERS:
			frappe.db.set_value("User", user, "enabled", 1)
			update_password(user, PASSWORD)
		h.make_link("atonota-member", MEMBER)
		h.make_link("atonota-visitor", VISITOR)
		h.make_link("atonota-manager", MANAGER)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.db.set_value("User", MEMBER, "user_type", "System User")
		frappe.db.delete("ToDo", {"description": ("like", f"%{decision_api.TASK_MARK}%")})
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("ToDo", {"description": ("like", f"%{decision_api.TASK_MARK}%")})
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		super().tearDown()

	# --- request helpers ---

	def send(self, client, path: str, body: dict | None = None):
		headers = {"Accept": "application/json", "Content-Type": "application/json"}
		headers.update(h.csrf_headers(client))
		kwargs = {"path": path, "method": "POST", "headers": headers, "data": json.dumps(body or {})}
		# Committed on purpose: the request uses another connection.
		frappe.db.commit()  # nosemgrep: frappe-request-commit
		try:
			return make_request(client.open, args=(), kwargs=kwargs, site=frappe.local.site)
		finally:
			frappe.db.rollback()

	def login(self, user: str):
		client = get_test_client(use_cookies=True)
		response = self.send(client, "/api/method/login", {"usr": user, "pwd": PASSWORD})
		self.assertEqual(response.status_code, 200, response.data[:300])
		return client

	def evaluate(self, client, body: dict):
		return self.send(client, API + "evaluate", body)

	def decision(self, user: str, body: dict) -> dict:
		response = self.evaluate(self.login(user), body)
		self.assertEqual(response.status_code, 200, response.data[:400])
		return response.json["message"]

	def counts(self) -> dict:
		return {doctype: frappe.db.count(doctype) for doctype in PLAN_AND_BILLING_DOCTYPES}

	# --- evaluate ---

	def test_evaluate_guest_denied(self):
		response = self.evaluate(get_test_client(use_cookies=True), {"action": "open-paid-plan"})
		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.json.get("exc_type"), "PermissionError")
		self.assertEqual(owner_tasks(), [])

	def test_evaluate_foreign_data_denied(self):
		# The visitor cannot ask on behalf of the member. The answer is about the caller only.
		result = self.decision(VISITOR, {"action": "place-order", "user": MEMBER})
		self.assertEqual(result["status"], "denied")
		self.assertEqual(result["reasons"], ["membership"])

	def test_member_evidence_is_read_from_frappe_records(self):
		self.assertEqual(self.decision(MEMBER, {"action": "place-order"})["status"], "ready")
		frappe.db.set_value("User", MEMBER, "user_type", "Website User")
		result = self.decision(MEMBER, {"action": "place-order"})
		self.assertEqual(result["status"], "denied")
		self.assertEqual(result["reasons"], ["membership"])

	def test_client_evidence_does_not_change_the_result(self):
		forged = {"identity": FAR_FUTURE, "membership": FAR_FUTURE, "pricing-decision": FAR_FUTURE}
		visitor = self.decision(VISITOR, {"action": "place-order", "evidence": forged})
		self.assertEqual(visitor["status"], "denied")
		self.assertEqual(visitor["reasons"], ["membership"])
		forged["payment-card"] = FAR_FUTURE
		member = self.decision(MEMBER, {"action": "open-paid-plan", "evidence": forged})
		self.assertEqual(member["status"], "denied")
		self.assertEqual(member["reasons"], ["pricing", "payment-card"])

	def test_result_follows_the_contract_shape(self):
		result = self.decision(MEMBER, {"action": "place-order"})
		self.assertEqual(set(result), {"status", "action", "policy_version", "reasons", "owner_tasks"})
		self.assertEqual(result["action"], "place-order")
		self.assertRegex(result["policy_version"], r"^[0-9a-f]{64}$")
		self.assertEqual(result["reasons"], [])
		self.assertEqual(result["owner_tasks"], [])

	def test_unknown_action_is_denied(self):
		result = self.decision(MEMBER, {"action": "no-such-action"})
		self.assertEqual(result["status"], "denied")
		self.assertEqual(result["reasons"], ["unknown-action"])

	def test_bad_action_field_is_invalid_input(self):
		client = self.login(MEMBER)
		for body in ({}, {"action": ""}, {"action": 7}, {"action": "x" * 141}):
			with self.subTest(body=body):
				response = self.evaluate(client, body)
				self.assertEqual(response.status_code, 400, response.data[:300])
				self.assertEqual(response.json.get("exc_type"), "InvalidInput")

	def test_configuration_required_opens_one_task_for_the_rule_owner(self):
		first = self.decision(MEMBER, {"action": "guest-action"})
		self.assertEqual(first["status"], "configuration_required")
		self.assertEqual(
			first["owner_tasks"],
			[{"rule": "guest-actions", "owner": "product-owner", "action": "guest-action"}],
		)
		self.decision(MEMBER, {"action": "guest-action"})
		tasks = owner_tasks()
		self.assertEqual(len(tasks), 1, tasks)
		self.assertIn("guest-actions", tasks[0].description)
		self.assertIn("product-owner", tasks[0].description)
		self.assertEqual(tasks[0].role, "System Manager")

	# --- paid plan gate (G-166, AJA-18) ---

	def open_plan(self, user: str, body: dict | None = None):
		return self.send(self.login(user), API + "open_paid_plan", body)

	def assert_refused(self, response, state: str):
		self.assertEqual(response.status_code, 403, response.data[:300])
		self.assertEqual(response.json.get("exc_type"), "ActionRefused")
		message = response.json.get("exception", "") + response.json.get("_server_messages", "")
		self.assertIn(state, message)

	def test_open_paid_plan_guest_denied(self):
		before = self.counts()
		response = self.send(get_test_client(use_cookies=True), API + "open_paid_plan", {"plan": "starter"})
		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.json.get("exc_type"), "PermissionError")
		self.assertEqual(self.counts(), before)

	def test_open_paid_plan_foreign_data_denied(self):
		# Body fields cannot name another user or bring evidence.
		before = self.counts()
		body = {
			"plan": "starter",
			"user": MANAGER,
			"evidence": {"membership": FAR_FUTURE, "payment-card": FAR_FUTURE},
		}
		self.assert_refused(self.open_plan(VISITOR, body), "denied")
		self.assertEqual(self.counts(), before)

	def test_open_paid_plan_needs_a_plan_field(self):
		for body in ({}, {"plan": ""}, {"plan": 7}, {"plan": "x" * 141}):
			with self.subTest(body=body):
				response = self.open_plan(MEMBER, body)
				self.assertEqual(response.status_code, 400, response.data[:300])
				self.assertEqual(response.json.get("exc_type"), "InvalidInput")

	def test_gate_1_card_holder_passes_the_gate_but_billing_is_not_connected(self):
		# The card source does not exist yet. Here the test gives the server a card proof.
		before = self.counts()
		real = decision_api.collect_evidence

		def with_card(user, now):
			evidence = real(user, now)
			evidence["payment-card"] = decision_api._proof(now)
			return evidence

		for plan in ("starter", "growth"):
			with self.subTest(plan=plan), mock.patch.object(decision_api, "collect_evidence", with_card):
				response = self.open_plan(MEMBER, {"plan": plan})
				self.assertEqual(response.status_code, 409, response.data[:300])
				self.assertEqual(response.json.get("exc_type"), "BillingNotConnected")
		self.assertEqual(self.counts(), before)
		self.assertEqual(owner_tasks(), [])

	def test_gate_2_member_without_card_is_refused_and_nothing_is_written(self):
		before = self.counts()
		for plan in ("starter", "growth"):
			with self.subTest(plan=plan):
				self.assert_refused(self.open_plan(MEMBER, {"plan": plan}), "denied")
		self.assertEqual(self.counts(), before)
		self.assertEqual(owner_tasks(), [])

	def test_gate_3_enterprise_is_refused_even_with_a_card(self):
		before = self.counts()
		real = decision_api.collect_evidence

		def with_card(user, now):
			evidence = real(user, now)
			evidence["payment-card"] = decision_api._proof(now)
			return evidence

		with mock.patch.object(decision_api, "collect_evidence", with_card):
			self.assert_refused(self.open_plan(MEMBER, {"plan": "enterprise"}), "not-self-service")
			self.assert_refused(self.open_plan(MEMBER, {"plan": "trial"}), "unknown-plan")
		self.assertEqual(self.counts(), before)

	def test_gate_4_empty_pricing_rule_gives_configuration_required(self):
		data = json.loads(decision.POLICY_FILE.read_text(encoding="utf-8"))
		next(r for r in data["rules"] if r["id"] == "paid-plan-pricing")["value"] = None
		with mock.patch.object(decision_api, "_load_policy", return_value=decision.Policy(data)):
			self.assert_refused(self.open_plan(MEMBER, {"plan": "starter"}), "configuration_required")
		tasks = owner_tasks()
		self.assertEqual(len(tasks), 1, tasks)
		self.assertIn("paid-plan-pricing", tasks[0].description)

	def test_gate_6_refusal_writes_no_plan_or_billing_record(self):
		before = self.counts()
		for user in (MEMBER, MANAGER):
			self.assert_refused(self.open_plan(user, {"plan": "growth"}), "denied")
		self.assertEqual(self.counts(), before)

	def test_gate_7_system_manager_cannot_pass_the_gate(self):
		self.assert_refused(self.open_plan(MANAGER, {"plan": "starter"}), "denied")
		# Administrator, in process: the gate does not look at roles.
		frappe.set_user("Administrator")
		with self.assertRaises(decision_api.ActionRefused):
			decision_api.open_paid_plan("starter")


class TestAtonotaVerificationNoticeAccess(IntegrationTestCase):
	"""The two access tests of `verification_notice` (G-164). The other inbox tests are in
	`test_atonota_verification.py`. The endpoint is open to guests: the signature is the only key."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		notice.clear_records()
		h.reset_rate_limits()
		settings = h.SiteSettings({notice.CONFIG_FIELD: notice.SECRET})
		settings.__enter__()
		self.addCleanup(settings.__exit__, None, None, None)
		self.addCleanup(notice.clear_records)

	def post(self, body: bytes, header: str | None):
		headers = {"Accept": "application/json", "Content-Type": "application/json"}
		if header is not None:
			headers[verification_api.SIGNATURE_HEADER] = header
		kwargs = {"path": notice.ENDPOINT, "method": "POST", "headers": headers, "data": body}
		# Committed on purpose: the request uses another connection.
		frappe.db.commit()  # nosemgrep: frappe-request-commit
		try:
			return make_request(get_test_client().open, args=(), kwargs=kwargs, site=frappe.local.site)
		finally:
			frappe.db.rollback()

	def stored(self) -> list:
		return frappe.get_all(
			notice.NOTICE, filters={"case_id": ("like", f"{notice.CASE_PREFIX}%")}, fields=["*"]
		)

	def test_verification_notice_guest_denied(self):
		# A guest without the provider signature stores nothing and starts no job.
		with mock.patch("frappe.enqueue") as enqueue:
			response = self.post(notice.notice_body("e-guest"), None)
		self.assertEqual(response.status_code, 401, response.data[:300])
		self.assertEqual(response.json.get("exc_type"), "NoticeSignatureRejected")
		self.assertEqual(self.stored(), [])
		enqueue.assert_not_called()

	def test_verification_notice_foreign_data_denied(self):
		# A signed body cannot set the state, the record name or a user. Only four fields are kept.
		body = notice.notice_body(
			"e-foreign", state="applied", name="foreign-name", user="Administrator", owner="Administrator"
		)
		with mock.patch("frappe.enqueue"):
			response = self.post(body, notice.signature(body))
		self.assertEqual(response.status_code, 200, response.data[:300])
		rows = self.stored()
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].state, "pending")
		self.assertNotEqual(rows[0].name, "foreign-name")
		self.assertNotEqual(rows[0].owner, "Administrator")
		self.assertFalse(frappe.db.exists(notice.NOTICE, "foreign-name"))
