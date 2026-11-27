"""G-146: Frappe paths that fetch a user-supplied address use the shared guard.

These tests import the real Frappe modules. They need no site and no network.
"""

import socket
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.automation_engine.actions import core as automation_actions
from frappe.core.doctype.file import file as file_doctype
from frappe.core.doctype.file import utils as file_utils
from frappe.integrations.doctype.slack_webhook_url import slack_webhook_url
from frappe.integrations.doctype.webhook import webhook
from frappe.utils import data as frappe_data

from platform_core.net import frappe_egress, safe_fetch


def resolution(address, port=443):
	family = socket.AF_INET6 if ":" in address else socket.AF_INET
	sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
	return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]


def reply(status=200, *, location=None, chunks=(b"fixture", b"")):
	result = MagicMock()
	result.status_code = status
	result.headers = {"Location": location} if location else {}
	result.raw.read1.side_effect = chunks
	return result


class InstallTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe_egress.install()

	def test_install_replaces_every_listed_path_and_is_idempotent(self):
		frappe_egress.install()
		self.assertIs(webhook.requests, frappe_egress.GUARDED_REQUESTS)
		self.assertIs(slack_webhook_url.requests, frappe_egress.GUARDED_REQUESTS)
		self.assertIs(file_utils.get_web_image, frappe_egress.get_web_image)
		self.assertIs(file_doctype.get_web_image, frappe_egress.get_web_image)
		self.assertIs(frappe_data.get_image_thumbnail_uri, frappe_egress.get_image_thumbnail_uri)
		self.assertIs(frappe.utils.get_image_thumbnail_uri, frappe_egress.get_image_thumbnail_uri)
		self.assertIs(automation_actions._send_guarded_request, frappe_egress.send_automation_request)

	def test_guarded_requests_keep_the_requests_exception_names(self):
		import requests

		self.assertIs(webhook.requests.exceptions, requests.exceptions)
		self.assertIs(webhook.requests.exceptions.ReadTimeout, requests.exceptions.ReadTimeout)

	def test_webhook_to_a_metadata_address_never_opens_a_socket(self):
		for address in ("169.254.169.254", "127.0.0.1", "10.0.0.5", "fd00::1"):
			with (
				self.subTest(address=address),
				patch("socket.getaddrinfo", return_value=resolution(address)),
				patch("socket.socket") as create,
				self.assertRaises(safe_fetch.FetchError),
			):
				webhook.requests.request(
					method="POST", url="https://hook.fixture.test/in", data="{}", headers={}, timeout=5
				)
			create.assert_not_called()

	def test_webhook_refuses_plain_http_and_a_redirect(self):
		with (
			patch.object(safe_fetch.SafeSession, "request") as send,
			self.assertRaises(safe_fetch.FetchError),
		):
			webhook.requests.request(method="POST", url="http://hook.fixture.test/in", data="{}")
		send.assert_not_called()
		with (
			patch.object(
				safe_fetch.SafeSession, "request", return_value=reply(302, location="https://127.0.0.1/")
			) as send,
			self.assertRaises(safe_fetch.FetchError),
		):
			webhook.requests.request(method="POST", url="https://hook.fixture.test/in", data="{}")
		self.assertEqual(send.call_count, 1)

	def test_webhook_keeps_its_body_headers_and_timeout(self):
		with patch.object(safe_fetch.SafeSession, "request", return_value=reply()) as send:
			result = webhook.requests.request(
				method="POST",
				url="https://hook.fixture.test/in",
				data='{"a": 1}',
				headers={"X-Fixture": "1"},
				timeout=5,
			)
		self.assertEqual(result.status_code, 200)
		self.assertEqual(send.call_args.kwargs["data"], '{"a": 1}')
		self.assertEqual(send.call_args.kwargs["headers"], {"X-Fixture": "1"})
		self.assertLessEqual(send.call_args.kwargs["timeout"], 5)

	def test_slack_webhook_post_uses_the_guard(self):
		with (
			patch("socket.getaddrinfo", return_value=resolution("192.168.1.1")),
			patch("socket.socket") as create,
			self.assertRaises(safe_fetch.FetchError),
		):
			slack_webhook_url.requests.post("https://hooks.fixture.test/x", data="{}")
		create.assert_not_called()

	def test_web_image_redirect_chain_to_a_private_address_is_refused(self):
		replies = [reply(302, location="/a"), reply(302, location="https://10.1.2.3/img.png")]
		with patch.object(safe_fetch.SafeSession, "request", side_effect=replies) as send:
			with self.assertRaises(OSError):
				file_doctype.get_web_image("https://images.fixture.test/start.png")
		self.assertEqual(send.call_count, 2)

	def test_web_image_refuses_a_relative_or_plain_http_address(self):
		for url in ("/api/method/fixture", "http://images.fixture.test/a.png"):
			with self.subTest(url=url), patch.object(safe_fetch.SafeSession, "request") as send:
				with self.assertRaises(OSError):
					file_utils.get_web_image(url)
				send.assert_not_called()

	def test_web_page_thumbnail_returns_the_address_without_a_request(self):
		frappe.local._print_thumbnail_cache = {}
		with (
			patch("socket.getaddrinfo", return_value=resolution("127.0.0.1")),
			patch("socket.socket") as create,
		):
			url = "https://images.fixture.test/a.png"
			# The refused address is not handed to the PDF renderer either.
			self.assertEqual(frappe.utils.get_image_thumbnail_uri(url), "")
			self.assertEqual(frappe.utils.get_image_thumbnail_uri(url), "")
		create.assert_not_called()

	def test_automation_webhook_action_checks_each_redirect_hop(self):
		replies = [reply(307, location="https://other.fixture.test/b"), reply(301, location="https://[::1]/")]
		with (
			patch.object(safe_fetch.SafeSession, "request", side_effect=replies) as send,
			# Translation needs a site. The message text is not under test.
			patch.object(frappe_egress, "_", side_effect=str),
		):
			with self.assertRaises(automation_actions.AutomationParamError):
				automation_actions._send_guarded_request(
					"POST", "https://flow.fixture.test/a", {"Authorization": "Bearer fixture"}, {"a": 1}, 10
				)
		self.assertEqual(send.call_count, 2)
		self.assertNotIn("Authorization", send.call_args_list[1].kwargs["headers"] or {})

	def test_file_thumbnail_skips_a_refused_image_without_failing_the_save(self):
		document = MagicMock(file_url="https://10.0.0.1/a.png")
		with patch.object(safe_fetch.SafeSession, "request") as send:
			self.assertIsNone(file_doctype.File.make_thumbnail(document))
		send.assert_not_called()

	def test_guarded_requests_do_not_hand_out_an_unguarded_session(self):
		for name in ("Session", "session", "api", "adapters"):
			with self.subTest(name=name), self.assertRaises(AttributeError):
				getattr(webhook.requests, name)

	def test_install_refuses_when_a_frappe_entry_point_is_missing(self):
		with patch.object(file_utils, "get_web_image", None):
			del file_utils.get_web_image
			with self.assertRaises(RuntimeError):
				frappe_egress.install()
		frappe_egress.install()
