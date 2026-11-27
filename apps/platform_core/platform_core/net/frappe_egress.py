"""G-146: Frappe paths that fetch a user-supplied address go through safe_fetch.

install() runs before every request, every background job and every migrate. It replaces
these Frappe 16 entry points with guarded versions:

- Webhook and Slack Webhook URL send through GUARDED_REQUESTS.
- The File doctype loads a remote image through get_web_image.
- Print and web templates embed a remote image through get_image_thumbnail_uri.
- The automation "Send Webhook" action sends through send_automation_request.

Server scripts keep Frappe's own guarded session (frappe.utils.safe_exec).
Identity clients with server-pinned hosts stay outside (safe_fetch.PINNED_IDENTITY_CLIENTS).
`bench execute`, `bench console` and other command line paths do not run these hooks.
"""

import base64
import io
from urllib.parse import unquote

import frappe
import requests
from frappe import _

from platform_core.net import safe_fetch

DEFAULT_TIMEOUT = 10
WEBHOOK_MAX_BYTES = 1024 * 1024
IMAGE_MAX_BYTES = 20 * 1024 * 1024
THUMBNAIL_TIMEOUT = 5
# Options that change only the transport. The guard always verifies TLS and never streams.
_IGNORED_OPTIONS = frozenset({"allow_redirects", "stream", "verify"})
_PASSED_OPTIONS = frozenset({"params", "data", "json", "headers", "auth"})
# These would hand an unguarded session or transport back to the caller.
_UNGUARDED_NAMES = frozenset({"Session", "session", "api", "adapters"})


def _timeout(value):
	if value is None:
		return DEFAULT_TIMEOUT
	if isinstance(value, tuple):
		# requests takes (connect, read). The guard has one deadline for the whole exchange.
		return sum(part for part in value if part is not None) or DEFAULT_TIMEOUT
	return value


class GuardedRequests:
	"""Stands in for the requests module inside the listed Frappe modules.

	Exception classes and other names come from the real requests module.
	Redirects stay off. Options that would leave the guard are refused.
	"""

	def __getattr__(self, name):
		if name in _UNGUARDED_NAMES:
			raise AttributeError(name)
		return getattr(requests, name)

	def request(self, method, url, **options):
		unknown = set(options) - _PASSED_OPTIONS - _IGNORED_OPTIONS - {"timeout"}
		if unknown:
			raise safe_fetch.FetchError("Option is not allowed")
		passed = {name: options[name] for name in _PASSED_OPTIONS if name in options}
		return safe_fetch.request(
			method,
			url,
			timeout=_timeout(options.get("timeout")),
			max_bytes=WEBHOOK_MAX_BYTES,
			**passed,
		)

	def get(self, url, params=None, **options):
		return self.request("GET", url, params=params, **options)

	def head(self, url, **options):
		return self.request("HEAD", url, **options)

	def post(self, url, data=None, json=None, **options):
		return self.request("POST", url, data=data, json=json, **options)

	def put(self, url, data=None, **options):
		return self.request("PUT", url, data=data, **options)

	def patch(self, url, data=None, **options):
		return self.request("PATCH", url, data=data, **options)

	def delete(self, url, **options):
		return self.request("DELETE", url, **options)


GUARDED_REQUESTS = GuardedRequests()


def get_web_image(file_url: str):
	"""Guarded copy of frappe.core.doctype.file.utils.get_web_image.

	Only an absolute HTTPS address is fetched. Up to safe_fetch.MAX_REDIRECTS
	redirects are followed, and each target is checked again.
	"""
	from frappe.core.doctype.file.utils import get_extension, get_random_filename
	from frappe.utils import strip
	from frappe.utils.image import Image

	try:
		response = safe_fetch.request(
			"GET",
			file_url,
			timeout=DEFAULT_TIMEOUT,
			max_bytes=IMAGE_MAX_BYTES,
			max_redirects=safe_fetch.MAX_REDIRECTS,
		)
	except safe_fetch.FetchError:
		# File.make_thumbnail skips OSError. A refused image must not fail the save.
		raise requests.exceptions.ConnectionError("Address is not allowed") from None
	if response.status_code != 200:
		# File.make_thumbnail skips the image on this error, as it did before.
		raise requests.exceptions.HTTPError(f"{response.status_code} Error", response=response)
	content = response.content
	image = Image.open(io.BytesIO(content))
	try:
		filename, extn = file_url.rsplit("/", 1)[1].rsplit(".", 1)
	except ValueError:
		filename = get_random_filename()
		extn = None
	extn = get_extension(filename, extn, content)
	return image, "/files/" + strip(unquote(filename)), extn


def get_image_thumbnail_uri(url: str, max_dim: int = 400, quality: int = 80) -> str:
	"""Guarded copy of frappe.utils.data.get_image_thumbnail_uri.

	A remote address goes through safe_fetch without redirects. A refused
	address becomes an empty source, so the PDF renderer does not load it either.
	Other errors return the address unchanged, as Frappe does.
	A site-relative path keeps Frappe's own local file reader.
	"""
	if not isinstance(url, str) or not url.startswith(("http://", "https://")):
		return _FRAPPE_THUMBNAIL(url, max_dim, quality)
	cache = getattr(frappe.local, "_print_thumbnail_cache", None)
	if cache is None:
		cache = frappe.local._print_thumbnail_cache = {}
	key = (url, max_dim, quality)
	if key in cache:
		return cache[key]
	try:
		content = safe_fetch.fetch(url, timeout=THUMBNAIL_TIMEOUT, max_bytes=IMAGE_MAX_BYTES)
	except safe_fetch.FetchError:
		cache[key] = ""
		return ""
	try:
		from PIL import Image

		image = Image.open(io.BytesIO(content))
		image.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
		image_format = "PNG" if image.mode in ("RGBA", "LA", "P") else "JPEG"
		if image_format == "JPEG" and image.mode != "RGB":
			image = image.convert("RGB")
		buffer = io.BytesIO()
		options = {"format": image_format, "optimize": True}
		if image_format == "JPEG":
			options["quality"] = quality
		image.save(buffer, **options)
	except Exception:
		return url
	encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
	data_uri = f"data:image/{image_format.lower()};base64,{encoded}"
	cache[key] = data_uri
	return data_uri


def send_automation_request(method, url, headers, payload, timeout):
	"""Guarded copy of the automation engine's _send_guarded_request.

	Redirects are followed up to safe_fetch.MAX_REDIRECTS. Each target is checked again.
	"""
	from frappe.automation_engine.actions.core import AutomationParamError

	body = frappe.as_json(payload) if payload else None
	headers = {"Content-Type": "application/json", **(headers or {})} if body else dict(headers or {})
	try:
		return safe_fetch.request(
			method,
			url,
			data=body,
			headers=headers,
			timeout=timeout,
			max_bytes=WEBHOOK_MAX_BYTES,
			max_redirects=safe_fetch.MAX_REDIRECTS,
		)
	except safe_fetch.FetchError:
		raise AutomationParamError(_("This address is not allowed."), fieldname="url") from None


def _frappe_thumbnail():
	from frappe.utils import data

	original = data.get_image_thumbnail_uri
	return getattr(original, "__wrapped_frappe__", original)


_FRAPPE_THUMBNAIL = _frappe_thumbnail()
get_image_thumbnail_uri.__wrapped_frappe__ = _FRAPPE_THUMBNAIL


def install(*_args, **_kwargs):
	"""Replace the Frappe entry points. Safe to call many times (before_request, before_job)."""
	from frappe.automation_engine.actions import core as automation_actions
	from frappe.core.doctype.file import file as file_doctype
	from frappe.core.doctype.file import utils as file_utils
	from frappe.integrations.doctype.slack_webhook_url import slack_webhook_url
	from frappe.integrations.doctype.webhook import webhook
	from frappe.utils import data

	replacements = (
		(webhook, "requests", GUARDED_REQUESTS),
		(slack_webhook_url, "requests", GUARDED_REQUESTS),
		(file_utils, "get_web_image", get_web_image),
		(file_doctype, "get_web_image", get_web_image),
		(data, "get_image_thumbnail_uri", get_image_thumbnail_uri),
		(frappe.utils, "get_image_thumbnail_uri", get_image_thumbnail_uri),
		(automation_actions, "_send_guarded_request", send_automation_request),
	)
	# A Frappe upgrade may rename an entry point. Then the path would stay open, so stop here.
	for module, name, _replacement in replacements:
		if not hasattr(module, name):
			raise RuntimeError(f"G-146 guard cannot find {module.__name__}.{name}")
	for module, name, replacement in replacements:
		setattr(module, name, replacement)
