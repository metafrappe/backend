"""Build the application manifest from the current site's installed apps."""

import frappe


def _public_entries(app: str, hook: str) -> list[dict[str, str]]:
	entries = []
	for declaration in frappe.get_hooks(hook, app_name=app):
		if not isinstance(declaration, dict):
			continue
		entry_id = declaration.get("id")
		title = declaration.get("title")
		if isinstance(entry_id, str) and entry_id and isinstance(title, str) and title:
			entries.append({"id": entry_id, "title": title})
	return entries


def read_manifest(tools_by_app: dict[str, list[dict[str, str]]]) -> dict:
	"""Return static screen and help metadata plus role-filtered AI tool references."""
	installed = set(frappe.get_installed_apps(_ensure_on_bench=True))

	return {
		"version": 1,
		"apps": [
			{
				"name": app,
				"screens": _public_entries(app, "app_module_screens"),
				"help_topics": _public_entries(app, "app_module_help_topics"),
				"tools": tools_by_app.get(app, []),
			}
			for app in sorted(installed)
		],
	}
