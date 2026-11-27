"""Frappe hooks for G-17 and G-47 (O-69).

- `send_queued` is the `override_email_send` hook. Frappe calls it once per recipient inside its Email Queue
  loop. Frappe still writes the recipient status, the retry count and the error.
- `localize_subject` is the `make_email_body_message` hook. It replaces known Press subjects.
"""

import datetime

import frappe

from press_tr.outbound_email import delivery, messages

QUOTA_TTL_SECONDS = 2 * 24 * 60 * 60


def reserve_daily(*, site, plan, limit):
	"""Take one unit from today's counter. Redis INCR is atomic, so parallel workers cannot overshoot."""
	day = datetime.datetime.now(datetime.UTC).date().isoformat()
	key = frappe.cache.make_key(f"{delivery.QUOTA_FEATURE}:{plan}:{day}")
	count = frappe.cache.incr(key)
	if count == 1:
		frappe.cache.expire(key, QUOTA_TTL_SECONDS)
	return count <= limit


def _account(doc):
	login = None
	if not doc.no_smtp_authentication:
		login = doc.login_id if doc.login_id_is_different and doc.login_id else doc.email_id
	return {
		"email_id": doc.email_id,
		"smtp_server": doc.smtp_server,
		"smtp_port": doc.smtp_port,
		"use_tls": doc.use_tls,
		"use_ssl_for_outgoing": doc.use_ssl_for_outgoing,
		"login_id": login,
		"password": doc._password if login else None,
		"always_use_account_email_id_as_sender": doc.always_use_account_email_id_as_sender,
	}


def send_queued(email_queue, sender, recipient, message):
	# Frappe skips delivery in tests unless a test asks for it. Keep that behaviour.
	if frappe.flags.in_test and not frappe.flags.testing_email:
		return
	account = email_queue.get_email_account(raise_error=True)
	delivery.deliver(
		site=frappe.local.site,
		sender=delivery.address_of(sender),
		recipient=recipient,
		message=message,
		account=_account(account),
		policy=frappe.conf.get("outbound_email_policy") or {},
		reserve=reserve_daily,
	)


def localize_subject(email):
	subject = messages.localized_subject(email.subject, translate=frappe._)
	if subject:
		email.subject = subject
		email.set_header("Subject", subject)
