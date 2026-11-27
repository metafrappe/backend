"""Local configuration checks for the panel and tenant application."""

import ast
import json
import re
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
CORE = BACKEND / "apps" / "platform_core" / "platform_core"
STACK = BACKEND / "deploy" / "compose" / "stack.yaml"


class TestSessionBootstrapContract(unittest.TestCase):
	def test_http_and_realtime_share_each_sites_frontend(self):
		services = dict(
			re.findall(r"^  ([\w-]+):\n((?:^(?:    .*|\s*)\n)*)", STACK.read_text(), re.MULTILINE)
		)
		for site in ("tenant", "press"):
			with self.subTest(site=site):
				frontend = services[f"{site}-frontend"]
				self.assertIn(f"      BACKEND: {site}-web:8000\n", frontend)
				self.assertIn(f"      SOCKETIO: {site}-socket:9000\n", frontend)
				self.assertIn("      FRAPPE_SITE_NAME_HEADER: $$host\n", frontend)
				for service in (f"{site}-web", f"{site}-socket"):
					self.assertNotRegex(services[service], r"(?m)^    ports:")

	def test_tenant_lifecycle_and_role_fixture(self):
		hooks = ast.parse((CORE / "hooks.py").read_text())
		lifecycle = {
			node.targets[0].id: ast.literal_eval(node.value)
			for node in hooks.body
			if isinstance(node, ast.Assign)
			and isinstance(node.targets[0], ast.Name)
			and node.targets[0].id in {"after_install", "after_migrate"}
		}
		for name in ("after_install", "after_migrate"):
			self.assertIn("platform_core.identity.session_policy.apply", lifecycle[name])

		roles = json.loads((CORE / "fixtures" / "role.json").read_text())
		self.assertTrue(roles)
		for role in roles:
			self.assertEqual(role["doctype"], "Role")
			self.assertLessEqual(
				set(role), {"doctype", "name", "role_name", "desk_access", "disabled", "docstatus"}
			)
			self.assertEqual(role["name"], role["role_name"])
