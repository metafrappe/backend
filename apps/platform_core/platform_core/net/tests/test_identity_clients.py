"""O-58: identity clients with server-pinned hosts stay outside safe_fetch.

safe_fetch lists them by name and file. Their redirects stay off.
"""

import ast
import importlib.abc
import importlib.machinery
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from platform_core.net import safe_fetch

APPS = Path(__file__).resolve().parents[4]
HTTP_CALLS = frozenset({"get", "post", "put", "patch", "delete", "head", "request"})


def defined_functions(path):
	tree = ast.parse(path.read_text())
	return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}, tree


class _StubFrappe(importlib.abc.MetaPathFinder, importlib.abc.Loader):
	"""Serves a MagicMock for every frappe module, so sign_in imports without a site."""

	def find_spec(self, name, path, target=None):
		if name == "frappe" or name.startswith("frappe."):
			return importlib.machinery.ModuleSpec(name, self, is_package=True)
		return None

	def create_module(self, spec):
		module = MagicMock()
		module.__path__ = []
		module.__spec__ = spec
		return module

	def exec_module(self, module):
		pass


class IdentityClientTests(unittest.TestCase):
	def test_every_listed_identity_client_exists_in_its_file(self):
		self.assertTrue(safe_fetch.PINNED_IDENTITY_CLIENTS)
		for name, relative in safe_fetch.PINNED_IDENTITY_CLIENTS:
			with self.subTest(client=name):
				path = APPS / relative
				self.assertTrue(path.is_file(), relative)
				module, function = name.rsplit(".", 1)
				self.assertEqual(module.replace(".", "/") + ".py", relative.split("/", 1)[1])
				self.assertIn(function, defined_functions(path)[0])

	def test_listed_identity_clients_never_follow_redirects(self):
		for name, relative in safe_fetch.PINNED_IDENTITY_CLIENTS:
			tree = defined_functions(APPS / relative)[1]
			for node in ast.walk(tree):
				if (
					isinstance(node, ast.Call)
					and isinstance(node.func, ast.Attribute)
					and isinstance(node.func.value, ast.Name)
					and node.func.value.id == "requests"
					and node.func.attr in HTTP_CALLS
				):
					with self.subTest(client=name, line=node.lineno):
						flags = {k.arg: k.value for k in node.keywords}
						self.assertIn("allow_redirects", flags)
						self.assertIs(ast.literal_eval(flags["allow_redirects"]), False)

	def test_sign_in_code_exchange_does_not_follow_a_redirect(self):
		with patch.dict(sys.modules), patch.object(sys, "meta_path", [_StubFrappe(), *sys.meta_path]):
			from platform_core.identity import sign_in

			settings = MagicMock(internal_url="https://identity.fixture.test", realm="platform")
			with patch("requests.post") as post:
				post.return_value.status_code = 307
				with self.assertRaises(sign_in.ExchangeFailedError):
					sign_in.exchange_code(settings, "code", "verifier", "https://site.test/callback")
		self.assertIs(post.call_args.kwargs.get("allow_redirects"), False)
