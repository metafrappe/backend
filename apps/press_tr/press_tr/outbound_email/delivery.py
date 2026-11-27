"""Outbound delivery rules for G-47. This module does not import Frappe.

A message leaves only when all of these hold:

- An operator turned delivery on for the site.
- An operator approved the sender address and relay after SPF, DKIM, DMARC and PTR passed.
- The account uses STARTTLS on port 587 and the server certificate is verified.
- The message header sender is the approved sender.
- The plan quota still has room.

Checks that need no network run first. The quota is reserved next. The relay is contacted last.
"""

import smtplib
import ssl
from email.parser import BytesHeaderParser
from email.utils import getaddresses, parseaddr

QUOTA_FEATURE = "outbound_email_daily"
SUBMISSION_PORT = 587
DNS_CHECKS = ("spf", "dkim", "dmarc", "ptr")


class DeliveryDenied(Exception):
	"""The message was not sent. The text never includes credentials or message content."""


def address_of(value):
	return parseaddr(str(value or ""))[1].strip().lower()


def _flag(value):
	if isinstance(value, bool):
		return value
	try:
		return int(value) == 1
	except TypeError, ValueError:
		return False


def _check_transport(account):
	if not _flag(account.get("use_tls")):
		raise DeliveryDenied("outgoing account must use STARTTLS")
	if _flag(account.get("use_ssl_for_outgoing")):
		raise DeliveryDenied("outgoing account must use STARTTLS on the submission port")
	try:
		port = int(account.get("smtp_port"))
	except TypeError, ValueError:
		port = None
	if port != SUBMISSION_PORT:
		raise DeliveryDenied("outgoing account must use the submission port")


def _check_sender(sender, account, policy):
	address = address_of(sender)
	relay = str(account.get("smtp_server") or "").strip().lower()
	if not address or address != address_of(account.get("email_id")):
		raise DeliveryDenied("sender is not the outgoing account address")
	for approval in policy.get("verified_senders") or ():
		if not isinstance(approval, dict):
			continue
		if address_of(approval.get("email")) != address:
			continue
		if str(approval.get("smtp_server") or "").strip().lower() != relay:
			continue
		if all(approval.get(check) is True for check in DNS_CHECKS):
			return address
	raise DeliveryDenied("sender domain is not verified")


def _check_header(message, address):
	headers = BytesHeaderParser().parsebytes(message)
	senders = getaddresses(headers.get_all("From", []))
	if len(senders) != 1 or senders[0][1].strip().lower() != address:
		raise DeliveryDenied("message sender does not match the verified sender")


def _quota(policy):
	quota = policy.get("quota")
	if not isinstance(quota, dict) or quota.get("feature") != QUOTA_FEATURE:
		raise DeliveryDenied("no quota is set for outbound email")
	limit, plan = quota.get("limit"), quota.get("plan")
	if type(limit) is not int or limit < 0 or not isinstance(plan, str) or not plan:
		raise DeliveryDenied("no quota is set for outbound email")
	return plan, limit


def tls_context():
	"""Certificate and host name checks stay on. Frappe's own STARTTLS call passes no context."""
	context = ssl.create_default_context()
	context.minimum_version = ssl.TLSVersion.TLSv1_2
	return context


def deliver(*, site, sender, recipient, message, account, policy, reserve, timeout=30):
	"""Send one message to one recipient or raise `DeliveryDenied`.

	`reserve(site=, plan=, limit=)` takes one unit from the quota and returns False when the quota is used up.
	A reserved unit is not returned when the relay fails later. The quota errs on the safe side.
	"""
	if not isinstance(policy, dict) or policy.get("enabled") is not True:
		raise DeliveryDenied("outbound email is not enabled for this site")
	if isinstance(message, str):
		message = message.encode("utf-8")
	_check_transport(account)
	address = _check_sender(sender, account, policy)
	_check_header(message, address)
	plan, limit = _quota(policy)

	try:
		allowed = reserve(site=site, plan=plan, limit=limit)
	except Exception:
		raise DeliveryDenied("quota store is not available") from None
	if allowed is not True:
		raise DeliveryDenied("quota is used up")

	with smtplib.SMTP(account["smtp_server"], SUBMISSION_PORT, timeout=timeout) as connection:
		connection.ehlo()
		try:
			connection.starttls(context=tls_context())
		except ssl.SSLError, smtplib.SMTPException, OSError:
			raise DeliveryDenied("relay did not accept a verified TLS connection") from None
		connection.ehlo()
		if account.get("login_id"):
			connection.login(account["login_id"], account.get("password") or "")
		refused = connection.sendmail(account["email_id"], [recipient], message)
	if refused:
		raise DeliveryDenied("relay refused the recipient")
