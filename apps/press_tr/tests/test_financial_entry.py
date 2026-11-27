"""AJA-197: generic financial writes close without breaking internal Press billing."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch


class FinancialEntryTest(TestCase):
	def setUp(self):
		self.framework = Mock()
		self.framework._ = lambda text, **kwargs: text
		self.framework.PermissionError = PermissionError
		self.framework.throw.side_effect = lambda message, exception=PermissionError: (_ for _ in ()).throw(
			exception(message)
		)
		self.framework.session.user = "customer@example.test"
		self.framework.form_dict = {}
		self.framework.request.method = "POST"
		self.framework.get_meta.return_value = SimpleNamespace(istable=False)
		self.framework.db.exists.return_value = False
		self.framework.local = SimpleNamespace()
		self.operators = Mock()
		self.operators.accounts.return_value = {}
		self.operators.service_users.return_value = set()
		source = Path(__file__).parents[1] / "press_tr/press_identity/financial_policy.py"
		spec = importlib.util.spec_from_file_location("financial_policy_under_test", source)
		self.policy = importlib.util.module_from_spec(spec)
		with patch.dict(
			sys.modules,
			{
				"frappe": self.framework,
				"press_tr": SimpleNamespace(),
				"press_tr.press_identity": SimpleNamespace(operators=self.operators),
				"press_tr.press_identity.operators": self.operators,
			},
		):
			spec.loader.exec_module(self.policy)

	def route(self, module, name, arguments=None, payload=None):
		self.framework.local.press_request_target = (
			SimpleNamespace(__module__=module, __name__=name),
			arguments or {},
		)
		self.framework.form_dict = payload or {}

	def test_rest_v1_v2_and_shared_records_are_denied(self):
		for module in ["frappe.api.v1", "frappe.api.v2"]:
			for name in ["create_doc", "update_doc", "delete_doc", "execute_doc_method"]:
				with self.subTest(module=module, name=name):
					self.route(module, name, {"doctype": "Invoice"})
					with self.assertRaises(PermissionError):
						self.policy.guard_request()

	def test_generic_rpc_payload_shapes_are_denied(self):
		cases = [
			("frappe.client", "insert", {"doc": '{"doctype":"Invoice"}'}),
			(
				"frappe.client",
				"insert_many",
				{"docs": '[{"doctype":"Team"},{"doctype":"Balance Transaction"}]'},
			),
			("frappe.client", "set_value", {"doctype": "Invoice", "name": "fixture"}),
			("frappe.desk.form.save", "savedocs", {"doc": '{"doctype":"Invoice"}', "action": "Submit"}),
			("frappe.handler", "run_doc_method", {"docs": '{"doctype":"Invoice"}', "method": "submit"}),
			("frappe.api.v2", "run_doc_method", {"document": {"doctype": "Invoice"}}),
			("frappe.model.workflow", "apply_workflow", {"doc": {"doctype": "Invoice"}}),
			(
				"frappe.desk.doctype.bulk_update.bulk_update",
				"submit_cancel_or_update_docs",
				{"doctype": "Invoice"},
			),
			("frappe.share", "add", {"doctype": "Invoice", "write": 1}),
		]
		for module, name, payload in cases:
			with self.subTest(module=module, name=name):
				self.route(module, name, payload=payload)
				with self.assertRaises(PermissionError):
					self.policy.guard_request()

	def test_import_resolves_protected_reference(self):
		self.route(
			"frappe.core.doctype.data_import.data_import",
			"form_start_import",
			payload={"data_import": "fixture-import"},
		)
		self.framework.db.get_value.return_value = "Invoice"
		with self.assertRaises(PermissionError):
			self.policy.guard_request()

	def test_child_record_cannot_bypass_financial_guard(self):
		self.route("frappe.client", "set_value", payload={"doctype": "Invoice Item", "name": "row"})
		self.framework.get_meta.return_value = SimpleNamespace(istable=True)
		self.framework.db.exists.return_value = True
		with self.assertRaises(PermissionError):
			self.policy.guard_request()

	def test_internal_team_subscription_and_payment_paths_remain_available(self):
		for module in ["press.api.account", "press.api.saas", "press.api.billing"]:
			self.route(module, "create", payload={"doctype": "Invoice"})
			self.policy.guard_request()

	def test_read_only_and_unrelated_documents_keep_framework_permissions(self):
		self.route("frappe.client", "get_list", payload={"doctype": "Invoice"})
		self.policy.guard_request()
		self.route("frappe.client", "save", payload={"doc": {"doctype": "ToDo"}})
		self.policy.guard_request()

	def test_billing_operator_still_requires_registered_human(self):
		self.route("frappe.client", "submit", payload={"doc": {"doctype": "Invoice"}})
		self.framework.session.user = "billing@example.test"
		self.operators.accounts.return_value = {"billing@example.test": {}}
		self.framework.get_roles.return_value = ["Press Ops Billing"]
		self.policy.guard_request()
		self.operators.guard_request.assert_called_once()

	def test_existing_file_cannot_write_linked_financial_field(self):
		self.route(
			"frappe.client",
			"set_value",
			payload={"doctype": "File", "name": "fixture-file", "fieldname": "is_private", "value": 1},
		)
		self.framework.db.get_value.return_value = "Invoice"
		with self.assertRaises(PermissionError):
			self.policy.guard_request()

	def test_file_target_requires_string_names(self):
		# Numeric SQL comparison can select a string File name. Never skip that target.
		for key in ("name", "docname", "dn", "old_name"):
			with self.subTest(key=key):
				self.route("frappe.client", "set_value", payload={"doctype": "File", key: 0})
				with self.assertRaises(PermissionError):
					self.policy.guard_request()
		for key in ("names", "docnames", "items"):
			for batch in (["fixture-file", 0], '["fixture-file", 0]', 0):
				with self.subTest(key=key, batch=batch):
					self.route("frappe.client", "delete", payload={"doctype": "File", key: batch})
					with self.assertRaises(PermissionError):
						self.policy.guard_request()

	def test_new_attachment_to_financial_record_is_protected(self):
		self.route(
			"frappe.handler", "upload_file", payload={"doctype": "Invoice", "docname": "fixture-invoice"}
		)
		with self.assertRaises(PermissionError):
			self.policy.guard_request()
		self.route(
			"frappe.client",
			"insert",
			payload={
				"doc": {
					"doctype": "File",
					"attached_to_doctype": "Invoice",
					"attached_to_name": "fixture-invoice",
				}
			},
		)
		with self.assertRaises(PermissionError):
			self.policy.guard_request()

	def test_customer_can_open_own_invoice_payment_link(self):
		# Press dashboard opens this GET link; Press itself checks invoice ownership.
		link = {"dt": "Invoice", "dn": "fixture-invoice", "method": "stripe_payment_url"}
		self.route("press.api.client", "run_doc_method", link, dict(link))
		self.policy.guard_request()
		self.framework.throw.assert_not_called()

	def test_payment_link_exception_covers_only_that_invoice_method(self):
		base = {"dt": "Invoice", "dn": "fixture-invoice", "method": "stripe_payment_url"}
		cases = [
			("press.api.client", "run_doc_method", {**base, "method": "submit"}),
			("press.api.client", "run_doc_method", {**base, "dt": "Balance Transaction"}),
			("press.api.client", "run_doc_method", {**base, "args": {"doctype": "Invoice"}}),
			("frappe.handler", "run_doc_method", base),
			("frappe.api.v2", "execute_doc_method", {**base, "doctype": "Invoice"}),
		]
		for module, name, arguments in cases:
			with self.subTest(module=module, name=name, arguments=arguments):
				self.route(module, name, arguments, dict(arguments))
				with self.assertRaises(PermissionError):
					self.policy.guard_request()
		# A payload that disagrees with the resolved arguments is not the payment link.
		self.route("press.api.client", "run_doc_method", base, {**base, "method": "cancel"})
		with self.assertRaises(PermissionError):
			self.policy.guard_request()
