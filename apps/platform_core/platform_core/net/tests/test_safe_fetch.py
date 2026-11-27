"""G-146 acceptance cases. No request leaves the test process."""

import socket
import unittest
from unittest.mock import MagicMock, patch

from platform_core.net import safe_fetch


def resolution(address, port=443):
	family = socket.AF_INET6 if ":" in address else socket.AF_INET
	sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
	return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]


def response(status=200, *, location=None, chunks=(b"fixture", b"")):
	result = MagicMock()
	result.status_code = status
	result.headers = {"Location": location} if location else {}
	result.raw.read1.side_effect = chunks
	result.raw._fp = None
	return result


class SafeFetchTests(unittest.TestCase):
	def test_private_special_and_metadata_addresses_never_open_a_socket(self):
		for address in (
			"127.0.0.1",
			"10.1.2.3",
			"172.16.0.1",
			"192.168.1.1",
			"169.254.169.254",
			"0.0.0.0",
			"100.64.0.1",
			"224.0.0.1",
			"::1",
			"fe80::1",
			"fc00::1",
			"::ffff:127.0.0.1",
			"64:ff9b::a00:1",
			"2002:7f00:1::",
			"fec0::1",
		):
			with (
				self.subTest(address=address),
				patch("socket.getaddrinfo", return_value=resolution(address)),
				patch("socket.socket") as create,
				self.assertRaises(safe_fetch.FetchError),
			):
				safe_fetch.SafeHTTPSConnection("fixture.test", timeout=1)._new_conn()
			create.assert_not_called()

	def test_mixed_public_and_private_dns_answers_are_rejected(self):
		with (
			patch("socket.getaddrinfo", return_value=resolution("1.1.1.1") + resolution("::1")),
			patch("socket.socket") as create,
			self.assertRaises(safe_fetch.FetchError),
		):
			safe_fetch.SafeHTTPSConnection("fixture.test", timeout=1)._new_conn()
		create.assert_not_called()

	def test_dns_is_pinned_then_a_rebound_connection_is_rejected(self):
		with (
			patch("socket.getaddrinfo", side_effect=[resolution("1.1.1.1"), resolution("127.0.0.1")]) as dns,
			patch("socket.socket") as create,
		):
			connection = safe_fetch.SafeHTTPSConnection("fixture.test", timeout=1)
			connection._new_conn()
			self.assertEqual(dns.call_count, 1)
			create.return_value.connect.assert_called_once_with(("1.1.1.1", 443))
			self.assertEqual(connection.host, "fixture.test")
			with self.assertRaises(safe_fetch.FetchError):
				safe_fetch.SafeHTTPSConnection("fixture.test", timeout=1)._new_conn()
			self.assertEqual(create.call_count, 1)

	def test_default_redirect_policy_rejects_without_reading_body(self):
		reply = response(302, location="https://127.0.0.1/secret")
		with patch.object(safe_fetch.SafeSession, "request", return_value=reply) as get:
			with self.assertRaises(safe_fetch.FetchError):
				safe_fetch.fetch("https://fixture.test")
		self.assertEqual(get.call_count, 1)
		reply.raw.read1.assert_not_called()
		reply.close.assert_called_once()

	def test_redirect_chain_to_private_address_is_rejected(self):
		replies = [response(302, location="/next"), response(307, location="https://169.254.169.254/latest")]
		with patch.object(safe_fetch.SafeSession, "request", side_effect=replies) as get:
			with self.assertRaises(safe_fetch.FetchError):
				safe_fetch.fetch("https://fixture.test/start", max_redirects=3)
		self.assertEqual(get.call_count, 2)
		for reply in replies:
			reply.close.assert_called_once()

	def test_redirect_limit_closes_every_response(self):
		replies = [response(302, location="/loop") for attempt in range(4)]
		with patch.object(safe_fetch.SafeSession, "request", side_effect=replies) as get:
			with self.assertRaises(safe_fetch.FetchError):
				safe_fetch.fetch("https://fixture.test/start", max_redirects=3)
		self.assertEqual(get.call_count, 4)
		for reply in replies:
			reply.close.assert_called_once()

	def test_caller_headers_do_not_follow_a_redirect_to_another_server(self):
		for location in ("https://other.test/next", "https://fixture.test:8443/next", "//other.test/next"):
			replies = [response(302, location=location), response()]
			with (
				self.subTest(location=location),
				patch.object(safe_fetch.SafeSession, "request", side_effect=replies) as get,
			):
				safe_fetch.fetch(
					"https://fixture.test/start", max_redirects=1, headers={"Authorization": "Bearer fixture"}
				)
				self.assertEqual(get.call_args_list[0].kwargs["headers"], {"Authorization": "Bearer fixture"})
				self.assertNotIn("Authorization", get.call_args_list[1].kwargs["headers"] or {})

	def test_caller_headers_stay_on_a_redirect_to_the_same_server(self):
		replies = [response(302, location="/next"), response()]
		with patch.object(safe_fetch.SafeSession, "request", side_effect=replies) as get:
			safe_fetch.fetch("https://Fixture.test/start", max_redirects=1, headers={"X-Fixture": "1"})
		self.assertEqual(get.call_args_list[1].kwargs["headers"], {"X-Fixture": "1"})

	def test_unsafe_urls_are_rejected_before_the_transport(self):
		for url in (
			"http://example.test",
			"file:///etc/passwd",
			"gopher://example.test",
			"https://user:pass@example.test",
			"https://example.test/#fragment",
			"https://[::1]/",
			"https://example.test\\@127.0.0.1/",
			" https://example.test",
		):
			with self.subTest(url=url), patch.object(safe_fetch.SafeSession, "request") as get:
				with self.assertRaises(safe_fetch.FetchError):
					safe_fetch.fetch(url)
				get.assert_not_called()

	def test_body_budget_and_compression_are_enforced(self):
		for reply in (response(chunks=(b"12345", b"")), response()):
			with patch.object(safe_fetch.SafeSession, "request", return_value=reply):
				with self.assertRaises(safe_fetch.FetchError):
					safe_fetch.fetch("https://fixture.test", max_bytes=4)
			reply.close.assert_called_once()
		reply = response()
		reply.headers = {"Content-Encoding": "gzip"}
		with patch.object(safe_fetch.SafeSession, "request", return_value=reply):
			with self.assertRaises(safe_fetch.FetchError):
				safe_fetch.fetch("https://fixture.test")
		reply.raw.read1.assert_not_called()

	def test_public_success_returns_bytes_and_preserves_request_bounds(self):
		reply = response()
		with patch.object(safe_fetch.SafeSession, "request", return_value=reply) as get:
			self.assertEqual(safe_fetch.fetch("https://fixture.test/path?key=fixture"), b"fixture")
		self.assertFalse(get.call_args.kwargs["allow_redirects"])
		self.assertTrue(get.call_args.kwargs["stream"])
		self.assertGreater(get.call_args.kwargs["timeout"], 0)
		reply.close.assert_called_once()

	def test_safe_session_does_not_inherit_proxy_or_netrc_credentials(self):
		with safe_fetch.SafeSession() as session:
			self.assertFalse(session.trust_env)
			self.assertIsNone(session.get_redirect_target(response(302, location="https://example.test")))

	def test_invalid_resource_budgets_fail_before_request(self):
		for kwargs in ({"timeout": 0}, {"timeout": float("nan")}, {"max_bytes": 0}, {"max_redirects": 4}):
			with self.subTest(kwargs=kwargs), patch.object(safe_fetch.SafeSession, "request") as get:
				with self.assertRaises(ValueError):
					safe_fetch.fetch("https://fixture.test", **kwargs)
				get.assert_not_called()


class SafeRequestTests(unittest.TestCase):
	"""safe_fetch.request serves callers that need a response object, such as webhooks."""

	def test_request_returns_a_response_with_a_bounded_body(self):
		reply = response(201, chunks=(b"created", b""))
		with patch.object(safe_fetch.SafeSession, "request", return_value=reply) as send:
			result = safe_fetch.request("POST", "https://fixture.test/hook", data=b"{}", headers={"X-A": "1"})
		self.assertIs(result, reply)
		self.assertEqual(result._content, b"created")
		self.assertEqual(send.call_args.args[:2], ("POST", "https://fixture.test/hook"))
		self.assertFalse(send.call_args.kwargs["allow_redirects"])
		self.assertTrue(send.call_args.kwargs["stream"])
		self.assertEqual(send.call_args.kwargs["data"], b"{}")
		reply.close.assert_called_once()

	def test_request_refuses_a_redirect_by_default(self):
		reply = response(302, location="https://fixture.test/next")
		with patch.object(safe_fetch.SafeSession, "request", return_value=reply) as send:
			with self.assertRaises(safe_fetch.FetchError):
				safe_fetch.request("POST", "https://fixture.test/hook")
		self.assertEqual(send.call_count, 1)
		reply.raw.read1.assert_not_called()

	def test_request_checks_every_redirect_hop_again(self):
		replies = [response(307, location="/next"), response(302, location="https://[fd00::1]/meta")]
		with patch.object(safe_fetch.SafeSession, "request", side_effect=replies) as send:
			with self.assertRaises(safe_fetch.FetchError):
				safe_fetch.request("POST", "https://fixture.test/hook", data=b"x", max_redirects=3)
		self.assertEqual(send.call_count, 2)
		self.assertEqual(send.call_args_list[1].args, ("POST", "https://fixture.test/next"))
		self.assertEqual(send.call_args_list[1].kwargs["data"], b"x")

	def test_request_turns_a_see_other_redirect_into_get_without_body(self):
		replies = [response(303, location="/done"), response()]
		with patch.object(safe_fetch.SafeSession, "request", side_effect=replies) as send:
			safe_fetch.request("POST", "https://fixture.test/hook", data=b"x", max_redirects=1)
		self.assertEqual(send.call_args_list[1].args, ("GET", "https://fixture.test/done"))
		self.assertIsNone(send.call_args_list[1].kwargs["data"])

	def test_request_refuses_unknown_methods_and_unsafe_urls(self):
		for method, url in (
			("CONNECT", "https://fixture.test"),
			("POST", "http://fixture.test"),
			("POST", "https://10.0.0.1/"),
		):
			with (
				self.subTest(method=method, url=url),
				patch.object(safe_fetch.SafeSession, "request") as send,
			):
				with self.assertRaises(safe_fetch.FetchError):
					safe_fetch.request(method, url)
				send.assert_not_called()

	def test_rebound_dns_is_refused_on_the_real_transport(self):
		"""The DNS answer changes from public to private between two requests."""
		with (
			patch("socket.getaddrinfo", side_effect=[resolution("1.1.1.1"), resolution("169.254.169.254")]),
			patch("socket.socket") as create,
		):
			create.return_value.connect.side_effect = OSError("fixture network is closed")
			with self.assertRaises(safe_fetch.FetchError):
				safe_fetch.request("POST", "https://rebind.fixture.test/a")
			self.assertEqual(create.call_count, 1)
			create.return_value.connect.assert_called_once_with(("1.1.1.1", 443))
			with self.assertRaises(safe_fetch.FetchError):
				safe_fetch.request("POST", "https://rebind.fixture.test/b")
			self.assertEqual(create.call_count, 1)

	def test_request_follows_the_requests_method_rules_on_a_found_redirect(self):
		replies = [response(302, location="/done"), response()]
		with patch.object(safe_fetch.SafeSession, "request", side_effect=replies) as send:
			safe_fetch.request(
				"PUT",
				"https://fixture.test/hook",
				data=b"x",
				headers={"Content-Type": "application/json", "X-Fixture": "1"},
				max_redirects=1,
			)
		second = send.call_args_list[1]
		self.assertEqual(second.args, ("GET", "https://fixture.test/done"))
		self.assertIsNone(second.kwargs["data"])
		self.assertEqual(second.kwargs["headers"], {"X-Fixture": "1"})
