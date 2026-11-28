"""G-97 part 1 (AJA-2551): Tenant Branding single DocType controller.

Validates hex color tokens and public same-site raster logo paths server-side so
CSS injection, script URLs, path traversal and private file references are rejected.
"""

import posixpath
import re

import frappe
from frappe import _
from frappe.model.document import Document

HEX_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")
# Brand logos are shared across all tenant users, so only public /files/ paths with strict ASCII characters are accepted.
LOGO_PATH_PATTERN = re.compile(r"/files/[A-Za-z0-9._/-]+")
ALLOWED_LOGO_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})


def validate_hex_color(value: object, label: str, *, required: bool = False) -> None:
	if value is None or value == "":
		if required:
			frappe.throw(
				_("{0} must be a six-digit hex color such as #12ab34.").format(label),
				frappe.ValidationError,
			)
		return
	if not isinstance(value, str) or not HEX_COLOR_PATTERN.fullmatch(value):
		frappe.throw(
			_("{0} must be a six-digit hex color such as #12ab34.").format(label),
			frappe.ValidationError,
		)


def validate_logo_path(value: object) -> None:
	if value is None or value == "":
		return
	if not isinstance(value, str) or not LOGO_PATH_PATTERN.fullmatch(value):
		frappe.throw(_("Logo must be a public uploaded raster image path."), frappe.ValidationError)
	normalized = posixpath.normpath(value)
	if normalized != value or not normalized.startswith("/files/") or ".." in value.split("/"):
		frappe.throw(_("Logo must be a public uploaded raster image path."), frappe.ValidationError)
	_root, ext = posixpath.splitext(normalized.lower())
	if ext not in ALLOWED_LOGO_EXTENSIONS:
		frappe.throw(
			_("Logo must be a PNG, JPEG, WebP or GIF image."),
			frappe.ValidationError,
		)
	# Public brand logos must reference an existing public File record on this site (exception to G-3).
	if not frappe.db.exists("File", {"file_url": normalized, "is_private": 0, "is_folder": 0}):
		frappe.throw(_("Logo file does not exist on this site."), frappe.ValidationError)


class TenantBranding(Document):
	def validate(self):
		validate_hex_color(self.primary_color, _("Primary Color"), required=True)
		validate_hex_color(self.accent_color, _("Accent Color"), required=False)
		validate_logo_path(self.logo)
