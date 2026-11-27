"""G-37 restore drill on the local development stack.

The drill writes a marker note to a local site, backs the site up with its files,
restores the backup into a new temporary site and compares the two sites. It then
drops the temporary site, removes the backup and deletes the marker.

It runs each step in a one-off tenant-web container of this checkout's stack
(dev/bin/compose, so PANE_PORT must be set). Database passwords are read inside
the container from its environment; they never appear in this process's arguments.
Only local development sites are accepted. It never touches a server.

Usage: python3 deploy/restore_drill.py --site tenant1.localhost --result result.json
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

# G-37 service level, written in docs/contracts/backup-sla.md.
REPORT_INTERVAL_MONTHS = 1
FULL_RESTORE_INTERVAL_MONTHS = 3
PARTS = ("database", "public", "private")
COUNTED_DOCTYPES = ("DocType", "User", "Note")
LOCAL_SITE = re.compile(r"(tenant1|test-[a-z0-9-]+)\.localhost")
DRILL_ROOT = "/home/frappe/frappe-bench/sites/restore-drill"
DEV_COMPOSE = Path(__file__).resolve().parents[1] / "dev" / "bin" / "compose"

# Frappe 16 restores only into an existing site, so an empty site comes first.
# The site's database user may log in from any container of the stack, as in dev/bootstrap.py.
RESTORE = (
    'set -e; bench new-site "$1" --db-type mariadb --db-host tenant-db '
    "--mariadb-user-host-login-scope % "
    '--db-root-password "$MARIADB_ROOT_PASSWORD" --admin-password "$ADMIN_PASSWORD"; '
    'exec bench --site "$1" --force restore "$2" --with-public-files "$3" '
    '--with-private-files "$4" --db-root-password "$MARIADB_ROOT_PASSWORD" '
    '--admin-password "$ADMIN_PASSWORD"'
)
# A restore that failed before creating the site leaves nothing to drop.
DROP = (
    'if [ ! -d "sites/$1" ]; then exit 0; fi; '
    'exec bench drop-site "$1" --force --no-backup --db-root-password "$MARIADB_ROOT_PASSWORD"'
)

Runner = Callable[[list[str]], str]


class DrillError(Exception):
    """A step failed. The message holds no password."""


def compose_runner(argv: list[str]) -> str:
    """Run one command in a one-off tenant-web container and return its output."""
    command = [str(DEV_COMPOSE), "run", "--rm", "--no-deps", "-T", "tenant-web", *argv]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-5:])
        raise DrillError(f"{' '.join(argv[:4])} exited with {result.returncode}: {tail}")
    return result.stdout


def last_value(output: str) -> str | None:
    """bench execute prints a truthy result on its last line and nothing otherwise."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else None


def execute(run: Runner, site: str, method: str, flag: str, value) -> str | None:
    return last_value(run(["bench", "--site", site, "execute", method, flag, json.dumps(value)]))


def count(run: Runner, site: str, doctype: str) -> int:
    value = execute(run, site, "frappe.db.count", "--args", [doctype])
    return int(value) if value else 0


def classify(names: list[str]) -> dict[str, str]:
    """Map each backup part to its file name."""
    found = {}
    for name in names:
        if name.endswith("-database.sql.gz"):
            found["database"] = name
        elif name.endswith("-private-files.tar"):
            found["private"] = name
        elif name.endswith("-files.tar"):
            found["public"] = name
    return found


def utc_text(now: Callable[[], datetime]) -> str:
    return now().astimezone(timezone.utc).isoformat(timespec="seconds")


def run_drill(
    site: str,
    run: Runner,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    token: str | None = None,
) -> dict:
    if not isinstance(site, str) or not LOCAL_SITE.fullmatch(site):
        raise DrillError("Only tenant1.localhost and test-*.localhost sites are accepted")
    token = token or secrets.token_hex(4)
    drill_site = f"restore-drill-{token}.localhost"
    folder = f"{DRILL_ROOT}/{token}"
    marker_title = f"restore-drill-{token}"
    result = {
        "requirement": "G-37",
        "kind": "restore-drill",
        "stack": "local",
        "started_at": utc_text(now),
        "source_site": site,
        "drill_site": drill_site,
        "parts": [],
        "checks": {"marker_restored": False, "counts": {}},
        "cleanup": {"drill_site_dropped": False, "backup_removed": False, "marker_removed": False},
        "error": None,
    }
    marker = None
    backup_taken = False
    restore_started = False
    try:
        inserted = execute(
            run, site, "frappe.client.insert", "--kwargs",
            {"doc": {"doctype": "Note", "title": marker_title, "content": "G-37 restore drill marker"}},
        )
        marker = json.loads(inserted)["name"] if inserted else None
        if not marker:
            raise DrillError("The marker note was not created")
        source_counts = {doctype: count(run, site, doctype) for doctype in COUNTED_DOCTYPES}
        backup_taken = True
        run(["bench", "--site", site, "backup", "--with-files", "--backup-path", folder])
        files = classify(run(["sh", "-c", 'ls -1 "$1"', "sh", folder]).split())
        result["parts"] = [part for part in PARTS if part in files]
        missing = [part for part in PARTS if part not in files]
        if missing:
            raise DrillError(f"The backup has no {', '.join(missing)} part")
        restore_started = True
        run(["sh", "-c", RESTORE, "sh", drill_site, *(f"{folder}/{files[part]}" for part in PARTS)])
        result["checks"]["counts"] = {
            doctype: [source_counts[doctype], count(run, drill_site, doctype)]
            for doctype in COUNTED_DOCTYPES
        }
        result["checks"]["marker_restored"] = (
            execute(run, drill_site, "frappe.db.exists", "--args", ["Note", marker]) == marker
        )
    except (DrillError, ValueError, KeyError) as error:
        result["error"] = str(error)
    finally:
        # Each cleanup step runs even when an earlier one fails.
        if restore_started:
            try:
                run(["sh", "-c", DROP, "sh", drill_site])
                result["cleanup"]["drill_site_dropped"] = True
            except DrillError as error:
                result["error"] = result["error"] or str(error)
        else:
            result["cleanup"]["drill_site_dropped"] = True
        if backup_taken:
            try:
                run(["rm", "-rf", "--", folder])
                result["cleanup"]["backup_removed"] = True
            except DrillError as error:
                result["error"] = result["error"] or str(error)
        else:
            result["cleanup"]["backup_removed"] = True
        if marker:
            try:
                execute(run, site, "frappe.client.delete", "--args", ["Note", marker])
                result["cleanup"]["marker_removed"] = True
            except DrillError as error:
                result["error"] = result["error"] or str(error)
        else:
            result["cleanup"]["marker_removed"] = True
    result["finished_at"] = utc_text(now)
    result["status"] = "fail" if evaluate(result) else "pass"
    return result


def evaluate(result: dict) -> list[str]:
    """Return the reasons the drill failed. An empty list means it passed."""
    problems = []
    if result.get("error"):
        problems.append(f"error: {result['error']}")
    if result.get("parts") != list(PARTS):
        problems.append("backup parts are incomplete")
    checks = result.get("checks", {})
    if checks.get("marker_restored") is not True:
        problems.append("the marker note is missing in the restored site")
    counts = checks.get("counts", {})
    for doctype in COUNTED_DOCTYPES:
        pair = counts.get(doctype)
        if not pair or len(pair) != 2 or pair[0] != pair[1] or pair[0] <= 0:
            problems.append(f"{doctype} count differs: {pair}")
    cleanup = result.get("cleanup", {})
    if not cleanup or not all(cleanup.get(key) is True for key in
                              ("drill_site_dropped", "backup_removed", "marker_removed")):
        problems.append("cleanup is incomplete")
    return problems


def main(
    argv: list[str] | None = None,
    *,
    runner: Runner = compose_runner,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    token: str | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="G-37 restore drill on the local stack")
    parser.add_argument("--site", default="tenant1.localhost")
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_drill(args.site, runner, now=now, token=token)
    except DrillError as error:
        print(f"restore drill refused: {error}", file=sys.stderr)
        return 2
    args.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"restore drill {result['status']}: {result['source_site']} -> {result['drill_site']}")
    for problem in evaluate(result):
        print(f"  {problem}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
