"""G-14: app release flow rules for Press, written as code.

This module holds the release definitions that the operator applies in Press:

- ``APP_SOURCES``: the only App Sources a release may use (GitHub repository and branch).
- ``RELEASE_GROUPS``: the staging group deploys automatically, the production group deploys
  only through ``Scheduled Deploy Settings``.
- ``DEPLOY_HOURS``: Press's ``deploy_hours`` hook constant, server time (UTC). A production
  deploy starts only inside these hours. The maintenance window in the contract uses them.
- ``validate_pyproject``: every app carries ``pyproject.toml`` with
  ``[tool.bench.frappe-dependencies] frappe = ">=16.x.y,<17.0.0"`` (Press CHANGELOG
  03-02-2026 rule).

The module imports nothing from Frappe or Press. It does not change Press records; the live
steps are in ``docs/handoff/g14-app-release-flow.md``.
"""

import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime

FRAPPE_MAJOR = 16
BRANCH = "version-16"
STAGING_GROUP = "erpnext-v16-tr-staging"
PRODUCTION_GROUP = "erpnext-v16-tr-prod"
# Press hooks.py ``deploy_hours``: 01:00-05:59 and 21:00-23:59 UTC.
DEPLOY_HOURS = frozenset({1, 2, 3, 4, 5, 21, 22, 23})


class ReleaseRuleError(ValueError):
	"""A release input breaks a G-14 rule."""


@dataclass(frozen=True)
class AppSource:
	app: str
	repository_url: str
	branch: str = BRANCH


@dataclass(frozen=True)
class ReleaseGroup:
	name: str
	apps: tuple[str, ...]
	enable_auto_deploy: bool
	scheduled_deploy: bool


APP_SOURCES = {
	source.app: source
	for source in (
		AppSource("frappe", "https://github.com/frappe/frappe"),
		AppSource("erpnext", "https://github.com/frappe/erpnext"),
		AppSource("hrms", "https://github.com/frappe/hrms"),
	)
}

_GROUP_APPS = ("frappe", "erpnext", "hrms")

RELEASE_GROUPS = {
	group.name: group
	for group in (
		ReleaseGroup(STAGING_GROUP, _GROUP_APPS, enable_auto_deploy=True, scheduled_deploy=False),
		ReleaseGroup(PRODUCTION_GROUP, _GROUP_APPS, enable_auto_deploy=False, scheduled_deploy=True),
	)
}


def validate_app_source(app, repository_url, branch):
	source = APP_SOURCES.get(app)
	if source is None:
		raise ReleaseRuleError(f"App {app!r} has no approved App Source.")
	if repository_url != source.repository_url or branch != source.branch:
		raise ReleaseRuleError(
			f"App {app!r} must come from {source.repository_url} on branch {source.branch}."
		)
	return source


def scheduled_deploy_groups():
	"""The Release Groups to list in Press ``Scheduled Deploy Settings.groups``."""
	return tuple(name for name, group in RELEASE_GROUPS.items() if group.scheduled_deploy)


def deploy_allowed(group_name, when):
	group = RELEASE_GROUPS.get(group_name)
	if group is None:
		raise ReleaseRuleError(f"Release Group {group_name!r} is not defined.")
	if when.tzinfo is None or when.utcoffset() is None:
		raise ReleaseRuleError("Deploy time must carry a time zone.")
	if not group.scheduled_deploy:
		return True
	return when.astimezone(UTC).hour in DEPLOY_HOURS


_SPEC = re.compile(r"(>=|<)\s*(\d+)\.(\d+)\.(\d+)")


def _frappe_range_ok(spec):
	parts = [part for part in re.split(r"[,\s]+", spec.strip()) if part]
	# Rejoin an operator that a space separated from its version.
	joined = []
	for part in parts:
		if joined and joined[-1] in (">=", "<"):
			joined[-1] += part
		else:
			joined.append(part)
	bounds = {}
	for part in joined:
		match = _SPEC.fullmatch(part)
		if match is None or match.group(1) in bounds:
			return False
		bounds[match.group(1)] = tuple(int(number) for number in match.groups()[1:])
	lower, upper = bounds.get(">="), bounds.get("<")
	return lower is not None and lower[0] == FRAPPE_MAJOR and upper == (FRAPPE_MAJOR + 1, 0, 0)


def validate_pyproject(text):
	"""Return the app name when ``pyproject.toml`` text follows the rule."""
	try:
		data = tomllib.loads(text)
	except tomllib.TOMLDecodeError as error:
		raise ReleaseRuleError(f"pyproject.toml is not valid TOML: {error}") from None
	name = data.get("project", {}).get("name")
	if not isinstance(name, str) or not name:
		raise ReleaseRuleError("pyproject.toml has no [project] name.")
	spec = data.get("tool", {}).get("bench", {}).get("frappe-dependencies", {}).get("frappe")
	if not isinstance(spec, str):
		raise ReleaseRuleError(f"{name}: [tool.bench.frappe-dependencies] frappe is missing.")
	if not _frappe_range_ok(spec):
		raise ReleaseRuleError(
			f"{name}: frappe must be >={FRAPPE_MAJOR}.x.y,<{FRAPPE_MAJOR + 1}.0.0, found {spec!r}."
		)
	return name
