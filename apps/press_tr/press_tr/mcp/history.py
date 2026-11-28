"""The `PTR MCP Call` history: one row for every call to the press_tr MCP server."""

import functools
import inspect
import json

import frappe

DOCTYPE = "PTR MCP Call"
MAX_TEXT = 2000


def _text(value) -> str:
	return json.dumps(value, default=str, sort_keys=True)[:MAX_TEXT]


def _write(tool: str, status: str, arguments: dict, error: str = "", commit: bool = False) -> None:
	frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"tool": tool,
			"status": status,
			"user": frappe.session.user,
			"request_ip": getattr(frappe.local, "request_ip", None) or "",
			"arguments": _text(arguments),
			"error": error[:MAX_TEXT],
		}
	).insert(ignore_permissions=True)
	if commit:
		# The error response rolls the request back. The history row must stay.
		frappe.db.commit()


def record_refusal(reason: str) -> None:
	_write("handler", "Refused", {}, reason, commit=True)


def recorded(fn):
	"""Write each call of a tool to the history.

	A result with `preview: True` is written as Preview. A raised error is written as Failed and
	committed before the error leaves.
	"""

	signature = inspect.signature(fn)

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		try:
			arguments = dict(signature.bind(*args, **kwargs).arguments)
		except TypeError:
			arguments = {"args": list(args), **kwargs}
		try:
			result = fn(*args, **kwargs)
		except Exception as error:
			_write(fn.__name__, "Failed", arguments, f"{type(error).__name__}: {error}", commit=True)
			raise
		status = "Preview" if isinstance(result, dict) and result.get("preview") else "Done"
		_write(fn.__name__, status, arguments)
		return result

	return wrapper
