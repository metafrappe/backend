"""G-97 security review finding 4 (AJA-2551): generic AI write tools refuse Tenant Settings and Tenant Branding."""

from frappe.tests import IntegrationTestCase

from platform_core.ai import policy
from platform_core.ai.errors import ToolDenied
from platform_core.ai.tools import write


class TestTenantSettingsAiWritePolicy(IntegrationTestCase):
	def test_tenant_settings_and_branding_are_closed_to_generic_ai_write_tools(self):
		for doctype in ("Tenant Settings", "Tenant Branding"):
			with self.subTest(doctype=doctype):
				self.assertTrue(policy.is_closed_by_app(doctype))
				with self.assertRaises(ToolDenied) as ctx:
					write.writable_meta(doctype)
				self.assertEqual(ctx.exception.code, "blocked_doctype")
