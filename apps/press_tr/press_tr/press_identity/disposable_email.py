"""Reject disposable email addresses (G-79). Keycloak rejects the same domains in its user profile."""

from pathlib import Path

import frappe
from frappe import _

DOMAINS = frozenset(
	line
	for line in Path(__file__)
	.with_name("disposable_email_domains.txt")
	.read_text(encoding="utf-8")
	.splitlines()
	if line and not line.startswith("#")
)


def is_disposable(email: str) -> bool:
	domain = email.strip().lower().rpartition("@")[2].rstrip(".")
	labels = domain.split(".")
	return any(".".join(labels[index:]) in DOMAINS for index in range(len(labels) - 1))


def reject_disposable(email: str) -> None:
	if is_disposable(email):
		frappe.throw(
			_(
				"Use a permanent email address. Temporary email addresses are not accepted.",
				context="press_tr",
			),
			frappe.ValidationError,
		)
