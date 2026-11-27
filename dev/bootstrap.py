"""Prepare only this Compose project's development and test sites."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from zoneinfo import available_timezones

BENCH = Path("/home/frappe/frappe-bench")
# Decision 44: a new tenant site starts in British English.
SITE_LANGUAGE = "en-GB"
# The tenant's country is not known at creation. Türkiye is the only open market for now.
DEFAULT_TIME_ZONE = "Europe/Istanbul"


def check_time_zone(time_zone: str) -> str:
    """Return the IANA time zone name or stop with a clear message."""
    if time_zone not in available_timezones():
        raise SystemExit(f"Invalid time zone {time_zone!r}: use an IANA name such as Europe/Istanbul.")
    return time_zone


def apply_locale(site: str, time_zone: str) -> None:
    """Write the language and time zone of a site that was just created."""
    import frappe
    from frappe.translate import set_default_language

    frappe.init(site)
    frappe.connect()
    try:
        frappe.db.set_single_value("System Settings", {"language": SITE_LANGUAGE, "time_zone": time_zone})
        frappe.db.set_default("time_zone", time_zone)
        set_default_language(SITE_LANGUAGE)
        frappe.db.commit()
    finally:
        frappe.destroy()


def configure() -> None:
    path = BENCH / "sites/common_site_config.json"
    config = json.loads(path.read_text()) if path.exists() else {}
    config.update(
        db_host="tenant-db",
        redis_cache="redis://tenant-redis:6379/0",
        redis_queue="redis://tenant-redis:6379/1",
        redis_socketio="redis://tenant-redis:6379/1",
        socketio_port=int(os.environ["FS_TENANT_SOCKET_PORT"]),
        webserver_port=int(os.environ["FS_TENANT_WEB_PORT"]),
        pause_scheduler=True,
        disable_scheduler=True,
        server_script_enabled=False,
    )
    # Never enable tests across all sites.
    config.pop("allow_tests", None)
    path.write_text(json.dumps(config, indent=2) + "\n")
    apps_path = BENCH / "sites/apps.txt"
    apps = apps_path.read_text().splitlines()
    apps_path.write_text("\n".join(dict.fromkeys([a for a in apps if a] + ["platform_core"])) + "\n")


def prepare(site: str, apps: list[str], time_zone: str = DEFAULT_TIME_ZONE) -> None:
    check_time_zone(time_zone)
    import frappe
    from frappe.commands.site import new_site

    configure()
    os.chdir(BENCH / "sites")
    path = Path(site) / "site_config.json"
    if not path.exists():
        # Run the actual new-site command without placing secrets in process arguments.
        new_site.main(
            [
                site,
                "--db-type",
                "mariadb",
                "--db-host",
                "tenant-db",
                "--mariadb-user-host-login-scope",
                "%",
                "--db-root-password",
                os.environ["MARIADB_ROOT_PASSWORD"],
                "--admin-password",
                os.environ["ADMIN_PASSWORD"],
            ],
            standalone_mode=False,
        )
        frappe.destroy()
        # Only a new site gets these values; a second run never creates or changes a site.
        apply_locale(site, time_zone)
    config = json.loads(path.read_text())
    config.update(
        allow_tests=site.startswith("test-"),
        developer_mode=True,
        pause_scheduler=True,
        disable_scheduler=True,
        mute_emails=True,
        host_name=f"http://{site}:{os.environ['FS_TENANT_WEB_PORT']}",
    )
    path.write_text(json.dumps(config, indent=2) + "\n")
    path.chmod(0o600)
    os.chdir(BENCH)
    for app in apps:
        subprocess.run(["bench", "--site", site, "install-app", app], check=True)
    print(f"Prepared {site}; allow_tests={site.startswith('test-')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site")
    parser.add_argument("--app", action="append", default=[])
    parser.add_argument("--time-zone", default=DEFAULT_TIME_ZONE, help="IANA name, e.g. Europe/Istanbul")
    args = parser.parse_args()
    if args.site != "tenant1.localhost" and not re.fullmatch(r"test-[a-z0-9-]+\.localhost", args.site):
        parser.error("Only tenant1.localhost and test-*.localhost are allowed")
    if any(not re.fullmatch(r"[a-z][a-z0-9_]*", app) for app in args.app):
        parser.error("Invalid app name")
    try:
        check_time_zone(args.time_zone)
    except SystemExit as error:
        parser.error(str(error))
    prepare(args.site, args.app, args.time_zone)


if __name__ == "__main__":
    main()
