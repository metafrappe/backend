"""Outgoing mail settings without secrets or real domain names. This module does not import Frappe.

DevOps writes the relay address, login and password on the server. They never enter the repository.
"""


def release_group_defaults():
	"""Settings every site of the platform gets. STARTTLS on port 587 is required (G-47)."""
	return {
		"mail_port": 587,
		"use_tls": 1,
		"use_ssl": 0,
		"email_retry_limit": 3,
		"always_use_account_email_id_as_sender": 1,
	}
