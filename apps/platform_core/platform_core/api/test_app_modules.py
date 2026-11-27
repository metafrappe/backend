"""Local tests for the installed application manifest."""

from inspect import unwrap
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from platform_core import hooks
from platform_core.api.app_modules import get_manifest

METHOD = "platform_core.api.app_modules.get_manifest"


class TestAppModules(TestCase):
	def test_projects_installed_modules_and_visible_tools(self):
		screen = {"id": "overview", "title": "Overview", "internal": "not public"}
		topic = {"id": "start", "title": "Getting started"}
		visible_tool = SimpleNamespace(app="sample", name="sample_list", visible=lambda: True)
		hidden_tool = SimpleNamespace(app="sample", name="sample_admin", visible=lambda: False)
		uninstalled_tool = SimpleNamespace(app="missing", name="missing_list", visible=lambda: True)
		with (
			patch("platform_core.api.app_modules.require_session"),
			patch(
				"platform_core.shell.app_modules.frappe.get_installed_apps", return_value=["sample", "bare"]
			),
			patch(
				"platform_core.shell.app_modules.frappe.get_hooks",
				side_effect=lambda hook, **kwargs: {
					("app_module_screens", "sample"): [screen],
					("app_module_help_topics", "sample"): [topic],
					("app_module_screens", "missing"): [screen],
				}.get((hook, kwargs["app_name"]), []),
			) as get_hooks,
			patch(
				"platform_core.ai.registry.all_tools",
				return_value=[visible_tool, hidden_tool, uninstalled_tool],
			),
		):
			self.assertEqual(
				unwrap(get_manifest)(),
				{
					"version": 1,
					"apps": [
						{"name": "bare", "screens": [], "help_topics": [], "tools": []},
						{
							"name": "sample",
							"screens": [{"id": "overview", "title": "Overview"}],
							"help_topics": [topic],
							"tools": [{"name": "sample_list"}],
						},
					],
				},
			)

		self.assertNotIn("missing", [call.kwargs["app_name"] for call in get_hooks.call_args_list])

	def test_requires_session_before_discovery(self):
		with (
			patch("platform_core.api.app_modules.require_session", side_effect=PermissionError),
			patch("platform_core.api.app_modules.read_manifest") as read_manifest,
		):
			with self.assertRaises(PermissionError):
				unwrap(get_manifest)()
		read_manifest.assert_not_called()

	def test_get_manifest_guest_denied(self):
		guest = frappe._dict(user="Guest", sid="Guest")
		request = SimpleNamespace(cookies={})
		with (
			patch.object(frappe.local, "session", guest, create=True),
			patch.object(frappe.local, "session_obj", guest, create=True),
			patch.object(frappe.local, "request", request, create=True),
			patch.object(frappe.local, "response_headers", {}, create=True),
			patch.object(frappe.local, "flags", frappe._dict(mute_messages=True), create=True),
			patch.object(frappe, "_", lambda message, **kwargs: message),
			patch("platform_core.api.app_modules.read_manifest") as read_manifest,
			patch("platform_core.api.app_modules.app_tool_references") as tool_references,
		):
			with self.assertRaises(frappe.PermissionError):
				unwrap(get_manifest)()
			self.assertEqual(frappe.local.response_headers["Cache-Control"], "private, no-store")
		read_manifest.assert_not_called()
		tool_references.assert_not_called()

	def test_get_manifest_foreign_data_denied(self):
		sites = {
			"tenant-a.localhost": ["platform_core", "own_app"],
			"tenant-b.localhost": ["platform_core", "foreign_app"],
		}
		hooks_by_app = {
			("app_module_screens", "own_app"): [{"id": "own", "title": "Own", "tenant": "tenant-a"}],
			("app_module_screens", "foreign_app"): [{"id": "foreign", "title": "Foreign"}],
			("app_module_help_topics", "foreign_app"): [{"id": "foreign-help", "title": "Foreign help"}],
		}
		tools = [
			SimpleNamespace(app="own_app", name="own_list", visible=lambda: True),
			SimpleNamespace(app="foreign_app", name="foreign_list", visible=lambda: True),
			SimpleNamespace(app="own_app", name="own_admin", visible=lambda: False),
		]
		with (
			patch.object(frappe.local, "site", "tenant-a.localhost", create=True),
			patch("platform_core.api.app_modules.require_session"),
			patch(
				"platform_core.shell.app_modules.frappe.get_installed_apps",
				side_effect=lambda **kwargs: sites[frappe.local.site],
			),
			patch(
				"platform_core.shell.app_modules.frappe.get_hooks",
				side_effect=lambda hook, **kwargs: hooks_by_app.get((hook, kwargs["app_name"]), []),
			) as get_hooks,
			patch("platform_core.ai.registry.all_tools", return_value=tools),
		):
			manifest = unwrap(get_manifest)()

		self.assertEqual(
			manifest["apps"],
			[
				{
					"name": "own_app",
					"screens": [{"id": "own", "title": "Own"}],
					"help_topics": [],
					"tools": [{"name": "own_list"}],
				},
				{"name": "platform_core", "screens": [], "help_topics": [], "tools": []},
			],
		)
		self.assertNotIn("foreign", repr(manifest))
		self.assertNotIn("tenant", repr(manifest))
		self.assertNotIn("foreign_app", [call.kwargs["app_name"] for call in get_hooks.call_args_list])

	def test_endpoint_registration(self):
		self.assertNotIn(get_manifest, frappe.guest_methods)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[get_manifest], ["GET"])
		self.assertIn(METHOD, hooks.website_user_allowed_methods)
