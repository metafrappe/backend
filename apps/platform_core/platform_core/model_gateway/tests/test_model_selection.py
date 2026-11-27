"""G-83: configured identifiers are checked before a model request is dispatched."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from platform_core.model_gateway import gateway
from platform_core.model_gateway.policy import Denied


class ModelSelectionTests(TestCase):
	def target(
		self, *, allowed='["synthetic-model"]', model_id="synthetic-model", provider="fixture-provider"
	):
		return gateway._checked_target(
			SimpleNamespace(allowed_models=allowed),
			SimpleNamespace(),
			SimpleNamespace(name="fixture-provider"),
			SimpleNamespace(provider=provider, model_id=model_id),
		)

	def test_exact_provider_and_allowed_model_are_required(self):
		self.assertEqual(self.target().model.model_id, "synthetic-model")
		for kwargs in [
			{"model_id": "unknown"},
			{"model_id": "Synthetic-model"},
			{"provider": "other-provider"},
		]:
			with self.subTest(**kwargs), self.assertRaises(Denied) as error:
				self.target(**kwargs)
			self.assertEqual(error.exception.code, "invalid_target")

	def test_empty_allowlist_allows_a_registered_model_of_the_same_provider(self):
		self.assertEqual(self.target(allowed="[]").model.model_id, "synthetic-model")
		with self.assertRaises(Denied):
			self.target(allowed="[]", provider="other-provider")

	def test_missing_model_stops_before_dispatch(self):
		def get_doc(doctype, name):
			if doctype == "PLT AI Model":
				raise frappe.DoesNotExistError
			return SimpleNamespace(account="fixture-account")

		with (
			patch.object(gateway.policy, "require_user"),
			patch.object(gateway, "_require_clean_transaction"),
			patch.object(gateway.frappe, "get_doc", side_effect=get_doc),
			patch.object(gateway, "_dispatch") as dispatch,
		):
			with self.assertRaises(frappe.PermissionError):
				gateway.test_api("fixture-api", "missing-model")
			dispatch.assert_not_called()
