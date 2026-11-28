"""G-97 part 1 (AJA-2551): Tenant Branding single DocType controller.

Validates hex color tokens and same-site raster logo paths server-side so CSS or
script injection values can never be stored.
"""

import posixpath
import re

import frappe
from frappe import _
from frappe.model.document import Document

HEX_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")
ALLOWED_LOGO_PREFIXES = ("/files/", "/private/files/")
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
	if not isinstance(value, str):
		frappe.throw(_("Logo must be a same-site uploaded raster image path."), frappe.ValidationError)
	if value != value.strip() or any(ord(ch) < 32 for ch in value):
		frappe.throw(_("Logo must be a same-site uploaded raster image path."), frappe.ValidationError)
	if "\\" in value or "?" in value or "#" in value:
		frappe.throw(_("Logo must be a same-site uploaded raster image path."), frappe.ValidationError)
	if not value.startswith(ALLOWED_LOGO_PREFIXES):
		frappe.throw(_("Logo must be a same-site uploaded raster image path."), frappe.ValidationError)
	if ".." in value.split("/"):
		frappe.throw(_("Logo must be a same-site uploaded raster image path."), frappe.ValidationError)
	_root, ext = posixpath.splitext(value.lower())
	if ext not in ALLOWED_LOGO_EXTENSIONS:
		frappe.throw(
			_("Logo must be a PNG, JPEG, WebP or GIF image."),
			frappe.ValidationError,
		)


class TenantBranding(Document):
	def validate(self):
		validate_hex_color(self.primary_color, _("Primary Color"), required=True)
		validate_hex_color(self.accent_color, _("Accent Color"), required=False)
		validate_logo_path(self.logo)
