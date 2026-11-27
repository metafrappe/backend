"""G-145: clean user HTML in rich text fields before it is saved (AJA-2282).

Frappe cleans field values in `Document._sanitize_content`. Its `sanitize_html` skips a value
that parses as JSON, so `["<img src=x onerror=alert(1)>"]` was saved as written. A rich text
field renders that value as HTML in the browser.

This hook cleans every rich text field with `always_sanitize=True`, the same call that
`Comment.validate` and `Note.validate` already make. Email bodies are such a field: the
Communication content is a Text Editor field.

The hook keeps Frappe's own exceptions. A field marked "Ignore XSS Filter" stays as written,
for example the Web Page HTML that an administrator writes. A submitted or cancelled document
keeps the fields that cannot change after submit. Plain text fields are not touched: they may
hold JSON on purpose, and cleaning would change characters such as "<" in it.

A value without "<" or ">" is skipped. The cleaner would otherwise turn "&" into "&amp;".
Server code that sets `flags.ignore_validate` or writes with `db_set` skips this hook, like
every other validate hook.
"""

import frappe
from frappe.utils.html_utils import sanitize_html

RICH_TEXT_FIELDTYPES = ("Text Editor", "HTML Editor")


def sanitize_rich_text(doc, method=None):
	"""doc_events["*"]["validate"]: clean rich text fields of the document and its rows."""
	# Like Frappe's own cleaning: app install writes trusted fixture data.
	if frappe.flags.in_install:
		return
	_sanitize_document(doc, doc)
	for row in doc.get_all_children():
		_sanitize_document(row, doc)


def _sanitize_document(doc, parent):
	for df in doc.meta.get("fields", {"fieldtype": ("in", RICH_TEXT_FIELDTYPES)}):
		if df.get("ignore_xss_filter"):
			continue
		if parent.docstatus.is_cancelled() or (
			parent.docstatus.is_submitted() and not df.get("allow_on_submit")
		):
			continue
		value = doc.get(df.fieldname)
		if not isinstance(value, str) or ("<" not in value and ">" not in value):
			continue
		doc.set(
			df.fieldname,
			sanitize_html(value, linkify=df.fieldtype == "Text Editor", always_sanitize=True),
		)
