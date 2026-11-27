"""The seven G-17 e-mail kinds. This module does not import Frappe.

Each kind has its own template in `templates/emails/`. Six templates use the Press template name, so Frappe's
Jinja loader reads the press_tr file first and Press code stays unchanged (M-4). `ptr_invoice` is new: Press
v0.154.1 sends no invoice e-mail of its own.

Press writes its subjects as plain strings, not through `_()`. `localized_subject` maps those exact subjects
to the Turkish subject of their kind. An unknown subject is left alone (O-69).
"""

import re
from urllib.parse import urlsplit

CONTEXT = "press_tr.email"

# template name -> English source subject, required arguments, link arguments
KINDS = {
	"ptr_invoice": ("Your invoice is ready", ("invoice_name", "amount", "billing_link"), ("billing_link",)),
	"payment_failed": (
		"We could not take your payment",
		("amount", "account_update_link"),
		("account_update_link", "payment_link"),
	),
	"suspended_sites": ("Your sites have been stopped", ("sites",), ()),
	"notify_before_site_archival": (
		"Your site will be archived",
		("site_name", "site_archive_notification_days"),
		(),
	),
	"product_trial_email": ("Your trial has ended", ("message",), ()),
	"payment_method_invalid": ("Update your card details", ("amount", "billing_link"), ("billing_link",)),
	"invite_team_member": ("You have been invited to a team", ("invited_by", "link"), ("link",)),
}

# Subjects written in Press v0.154.1 code. A Press upgrade must check this list again (O-69).
PRESS_SUBJECTS = (
	(re.compile(r"Your sites have been suspended on Frappe Cloud"), "suspended_sites"),
	(re.compile(r"Alert: Your site \S+ will be archived in \d+ days"), "notify_before_site_archival"),
	(re.compile(r"Invoice Payment Failed for Frappe Cloud Subscription"), "payment_failed"),
	(re.compile(r"Card on Frappe Cloud could not be charged"), "payment_method_invalid"),
	(re.compile(r"You are invited by .+ to join Frappe Cloud"), "invite_team_member"),
	(re.compile(r"Your .+ site is expired"), "product_trial_email"),
)


def _empty(value):
	return value is None or (isinstance(value, (str, list, tuple, dict)) and not value)


def check_link(url):
	parts = urlsplit(str(url))
	if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
		raise ValueError("link must be an https address without credentials")
	return url


def subject_for(template, translate):
	return translate(KINDS[template][0], context=CONTEXT)


def prepare(template, args, translate):
	"""Return the template, Turkish subject and checked arguments, or None for a kind outside G-17."""
	if template not in KINDS:
		return None
	_, required, links = KINDS[template]
	args = dict(args or {})
	missing = [name for name in required if _empty(args.get(name))]
	if missing:
		raise ValueError("missing e-mail data: " + ", ".join(missing))
	for name in links:
		if not _empty(args.get(name)):
			check_link(args[name])
	return {"template": template, "subject": subject_for(template, translate), "args": args}


def localized_subject(subject, translate):
	"""Return the Turkish subject for a known Press subject, otherwise None."""
	if not subject:
		return None
	for pattern, template in PRESS_SUBJECTS:
		if pattern.fullmatch(subject.strip()):
			return subject_for(template, translate)
	return None
