"""Fetch data from addresses that a user or tenant can configure (G-146).

The DNS answer is checked once and the socket connects to that checked IP.
urllib3 keeps the DNS name for TLS verification and SNI. Redirects are off by
default. When a caller enables them, each new target is checked again.

Identity services with server-pinned hosts keep their own clients (O-58).
They are listed in PINNED_IDENTITY_CLIENTS. Their redirects stay off.
"""

import math
import re
import socket
import sys
from ipaddress import IPv6Address, ip_address, ip_network
from time import monotonic
from urllib.parse import urljoin, urlsplit

import requests
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError

MAX_REDIRECTS = 3
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_UNSAFE_URL_CHARACTERS = re.compile(r"[\x00-\x20\x7f\\]")

# A pinned local target, such as a model server on a private host, may use these.
_LOCAL_NETWORKS = tuple(
	ip_network(network)
	for network in ("10.0.0.0/8", "127.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7")
)
_GLOBAL_IPV6 = ip_network("2000::/3")
_ZERO_NETWORK = ip_network("0.0.0.0/8")

# O-58 exceptions: the server owner pins these hosts in site configuration.
# A tenant or user cannot change them. Each client turns redirects off.
# Paths are relative to apps. A test checks every entry.
PINNED_IDENTITY_CLIENTS = (
	("platform_core.identity.sign_in.exchange_code", "platform_core/platform_core/identity/sign_in.py"),
	(
		"platform_core.identity.service_client.identity_sync_bearer",
		"platform_core/platform_core/identity/service_client.py",
	),
	(
		"platform_core.identity.mcp_introspection.fetch_introspection",
		"platform_core/platform_core/identity/mcp_introspection.py",
	),
	(
		"platform_core.mobile.identity_sync_client.send_session_revocations",
		"platform_core/platform_core/mobile/identity_sync_client.py",
	),
	("press_tr.api.auth.exchange_code", "press_tr/press_tr/api/auth.py"),
	(
		"press_tr.press_identity.deletion.send_deletion_request",
		"press_tr/press_tr/press_identity/deletion.py",
	),
)


class FetchError(Exception):
	"""A fixed refusal. It never carries the address, the response or the body."""


def is_local_address(ip):
	return any(ip in network for network in _LOCAL_NETWORKS)


def is_public_address(address):
	try:
		ip = ip_address(address)
	except ValueError:
		return False
	if isinstance(ip, IPv6Address) and (
		ip not in _GLOBAL_IPV6 or ip.scope_id or ip.sixtofour is not None or ip.teredo is not None
	):
		return False
	return ip.is_global and not (ip.is_multicast or ip.is_link_local or ip.is_unspecified)


def resolve_addresses(host, port, *, addresses=(), secure=True):
	"""Resolve once. Refuse the whole answer if any address is not allowed.

	Without pins only public addresses pass, and only over TLS.
	With pins only the pinned private addresses pass.
	"""
	try:
		resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
		pins = {ip_address(address) for address in addresses}
	except (OSError, UnicodeError, ValueError):
		raise FetchError("Address is not allowed") from None

	def allowed(family, address):
		try:
			ip = ip_address(address[0])
		except ValueError:
			return False
		if family == socket.AF_INET6 and (not isinstance(ip, IPv6Address) or ip.scope_id or address[3]):
			return False
		if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip in _ZERO_NETWORK:
			return False
		if not pins:
			return secure and is_public_address(ip)
		return ip in pins and is_local_address(ip)

	if not resolved or any(
		family not in (socket.AF_INET, socket.AF_INET6) or not allowed(family, address)
		for family, _kind, _proto, _canonical, address in resolved
	):
		raise FetchError("Address is not allowed")
	return resolved


class SafeConnection:
	"""urllib3 connection mixin that connects only to checked addresses."""

	def _approved_addresses(self):
		return resolve_addresses(self._dns_host, self.port, secure=isinstance(self, HTTPSConnection))

	def _connect_deadline(self):
		if isinstance(self.timeout, (float, int)):
			return monotonic() + self.timeout
		return None

	def _new_conn(self):
		# Keep the DNS name on the connection for TLS verification and SNI.
		# Connect the socket to the approved sockaddr without resolving it again.
		deadline = self._connect_deadline()
		for family, kind, proto, _canonical, address in self._approved_addresses():
			remaining = deadline - monotonic() if deadline is not None else None
			if remaining is not None and remaining <= 0:
				raise ConnectTimeoutError(self, "Connection timed out")
			try:
				sock = socket.socket(family, kind, proto)
			except OSError:
				continue
			try:
				sock.settimeout(remaining)
				for option in self.socket_options or ():
					sock.setsockopt(*option)
				if self.source_address:
					sock.bind(self.source_address)
				sys.audit("http.client.connect", self, self.host, self.port)
				sock.connect(address)
			except OSError:
				sock.close()
			except BaseException:
				sock.close()
				raise
			else:
				return sock
		raise NewConnectionError(self, "Connection failed")


class SafeHTTPSConnection(SafeConnection, HTTPSConnection):
	pass


class SafeHTTPConnection(SafeConnection, HTTPConnection):
	"""Plain HTTP passes only with pinned private addresses. The model gateway uses it."""


class _SafeHTTPSPool(HTTPSConnectionPool):
	ConnectionCls = SafeHTTPSConnection


class _SafeAdapter(requests.adapters.HTTPAdapter):
	def init_poolmanager(self, *args, **kwargs):
		super().init_poolmanager(*args, **kwargs)
		self.poolmanager.pool_classes_by_scheme = {"https": _SafeHTTPSPool}


class _RefusingAdapter(requests.adapters.BaseAdapter):
	def send(self, *args, **kwargs):
		raise FetchError("Only HTTPS is allowed")

	def close(self):
		pass


class SafeSession(requests.Session):
	"""Session for user-supplied HTTPS addresses. No proxy, netrc or redirect follow."""

	def __init__(self):
		super().__init__()
		self.trust_env = False
		self.headers["Accept-Encoding"] = "identity"
		self.mount("https://", _SafeAdapter())
		self.mount("http://", _RefusingAdapter())

	def get_redirect_target(self, response):
		# Requests otherwise drains redirect bodies even with allow_redirects=False.
		return None


def check_url(url):
	"""Refuse a URL that is not a plain HTTPS address with a DNS name or public IP."""
	if not isinstance(url, str) or _UNSAFE_URL_CHARACTERS.search(url):
		raise FetchError("URL is not allowed")
	try:
		parsed = urlsplit(url)
		hostname = parsed.hostname
		parsed.port  # Raises ValueError for a malformed port.
	except ValueError:
		raise FetchError("URL is not allowed") from None
	if (
		parsed.scheme != "https"
		or not hostname
		or parsed.username is not None
		or parsed.password is not None
		or "@" in parsed.netloc
		or parsed.fragment
		or url.endswith("#")
	):
		raise FetchError("URL is not allowed")
	try:
		literal = ip_address(hostname)
	except ValueError:
		return url
	if not is_public_address(literal):
		raise FetchError("URL is not allowed")
	return url


def _check_budgets(timeout, max_bytes, max_redirects):
	if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout):
		raise ValueError("timeout must be a finite number of seconds")
	if timeout <= 0:
		raise ValueError("timeout must be positive")
	if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
		raise ValueError("max_bytes must be a positive integer")
	if (
		isinstance(max_redirects, bool)
		or not isinstance(max_redirects, int)
		or not 0 <= max_redirects <= MAX_REDIRECTS
	):
		raise ValueError(f"max_redirects must be between 0 and {MAX_REDIRECTS}")


def _read_body(response, deadline, max_bytes):
	if response.headers.get("Content-Encoding", "identity").strip().lower() != "identity":
		raise FetchError("Compressed responses are not allowed")
	body = bytearray()
	while chunk := response.raw.read1(8192, decode_content=False):
		body.extend(chunk)
		if len(body) > max_bytes:
			raise FetchError("Response is too large")
		if monotonic() > deadline:
			raise FetchError("Response took too long")
	return bytes(body)


def _origin(url):
	parsed = urlsplit(url)
	return parsed.scheme, parsed.hostname, parsed.port or 443


ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})
_BODY_HEADERS = frozenset({"content-type", "content-length", "transfer-encoding"})


def request(
	method,
	url,
	*,
	timeout=10,
	max_bytes=1024 * 1024,
	max_redirects=0,
	headers=None,
	params=None,
	data=None,
	json=None,
	auth=None,
):
	"""Send one request to an HTTPS address and return the requests.Response.

	The body is read within `max_bytes` before the response is returned.
	Every failure raises FetchError with a fixed message. Redirects are refused
	unless `max_redirects` allows them. Each redirect target is checked again.
	Caller headers and credentials are dropped when a redirect leaves the first server.
	"""
	method = method.upper() if isinstance(method, str) else method
	if method not in ALLOWED_METHODS:
		raise FetchError("Method is not allowed")
	_check_budgets(timeout, max_bytes, max_redirects)
	check_url(url)
	deadline = monotonic() + timeout
	hops = 0
	with SafeSession() as session:
		while True:
			remaining = deadline - monotonic()
			if remaining <= 0:
				raise FetchError("Response took too long")
			try:
				response = session.request(
					method,
					url,
					headers=headers,
					params=params,
					data=data,
					json=json,
					auth=auth,
					timeout=remaining,
					allow_redirects=False,
					stream=True,
				)
			except FetchError:
				raise
			except Exception:
				raise FetchError("Request failed") from None
			try:
				if response.status_code in REDIRECT_STATUSES:
					location = response.headers.get("Location")
					if not location or hops >= max_redirects:
						raise FetchError("Redirect is not allowed")
					hops += 1
					target = check_url(urljoin(url, location))
					if _origin(target) != _origin(url):
						headers = auth = None
					# Follow requests.Session.rebuild_method: 303 and 302 become GET unless HEAD,
					# and 301 after POST becomes GET. The body and its headers are dropped.
					status = response.status_code
					if (status in (302, 303) and method != "HEAD") or (status == 301 and method == "POST"):
						method, data, json = "GET", None, None
						if headers:
							headers = {
								name: value
								for name, value in headers.items()
								if name.lower() not in _BODY_HEADERS
							}
					url, params = target, None
					continue
				try:
					response._content = _read_body(response, deadline, max_bytes)
					response._content_consumed = True
				except FetchError:
					raise
				except Exception:
					raise FetchError("Response could not be read") from None
				return response
			finally:
				response.close()


def fetch(url, *, timeout=10, max_bytes=1024 * 1024, max_redirects=0, headers=None):
	"""GET one HTTPS address and return the body as bytes.

	Every failure raises FetchError with a fixed message. Each redirect target
	is checked again before the next request, up to `max_redirects` hops.
	Caller headers are dropped when a redirect leaves the first server.
	"""
	response = request(
		"GET", url, timeout=timeout, max_bytes=max_bytes, max_redirects=max_redirects, headers=headers
	)
	if response.status_code != 200:
		raise FetchError("Unexpected response status")
	return response._content
