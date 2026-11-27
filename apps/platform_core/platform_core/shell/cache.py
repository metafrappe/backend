"""Site-local permission generations and the per-user shell bootstrap cache."""

import re
from uuid import uuid4

import frappe

VERSION_KEY = "platform_core:shell:permission_version"
BOOTSTRAP_KEY_PREFIX = "platform_core:shell:bootstrap:v1:"
# Redis KEYS patterns treat these characters as wildcards. A user name may contain them.
GLOB_CHARACTERS = re.compile(r"([\\*?\[\]])")


def permission_version() -> str:
	version = frappe.cache.get_value(VERSION_KEY)
	if not version:
		version = bump_permission_version()
	return version


def bump_permission_version() -> str:
	"""Opaque generations cannot collide after Redis/global-cache resets."""
	version = uuid4().hex
	frappe.cache.set_value(VERSION_KEY, version)
	return version


def invalidate_permissions(doc=None, method=None) -> None:
	"""Only committed permission changes invalidate other requests."""
	frappe.db.after_commit.add(bump_permission_version)


def clear_cache() -> None:
	"""Frappe calls the global clear_cache hook without arguments."""
	bump_permission_version()


def forget_user_bootstrap(user: str) -> None:
	"""Deletes every cached bootstrap payload of the user on this site (O-64).

	The pattern carries the site prefix and the escaped user name. Keys of other sites and other users
	never match it.
	"""
	if not user:
		return
	site = GLOB_CHARACTERS.sub(r"\\\1", str(frappe.local.conf.get("db_name")))
	name = GLOB_CHARACTERS.sub(r"\\\1", user)
	keys = frappe.cache.get_keys(f"{site}|user:{name}:{BOOTSTRAP_KEY_PREFIX}", shared=True)
	frappe.cache.delete_value(keys, make_keys=False)
