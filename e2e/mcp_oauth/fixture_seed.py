"""Create or update only the isolated MCP OAuth test site.

Runs inside the fixture tenant container. Settings, including secrets, arrive on stdin
so they never appear in process arguments or output.
"""

import json
import os
import sys
from pathlib import Path

BENCH = Path("/home/frappe/frappe-bench")
SITE = "tenant1.localhost"


def main() -> None:
    settings = json.load(sys.stdin)
    common = BENCH / "sites/common_site_config.json"
    common.write_text(
        json.dumps(
            {
                "db_host": "db",
                "redis_cache": "redis://redis:6379/0",
                "redis_queue": "redis://redis:6379/1",
                "redis_socketio": "redis://redis:6379/1",
                "pause_scheduler": True,
                "disable_scheduler": True,
                "serve_default_site": True,
            },
            indent=2,
        )
        + "\n"
    )
    os.chdir(BENCH / "sites")
    import frappe

    path = Path(SITE) / "site_config.json"
    created = not path.exists()
    if created:
        from frappe.commands.site import new_site

        # In-process click call keeps the database secrets out of process arguments.
        new_site.main(
            [
                SITE,
                "--db-type",
                "mariadb",
                "--db-host",
                "db",
                "--mariadb-user-host-login-scope",
                "%",
                "--db-root-password",
                settings["db_root"],
                "--admin-password",
                settings["admin"],
                "--install-app",
                "platform_core",
            ],
            standalone_mode=False,
        )
        frappe.destroy()
    conf = json.loads(path.read_text())
    conf.update(settings["site_config"])
    path.write_text(json.dumps(conf, indent=2) + "\n")
    path.chmod(0o600)
    if not created:
        from frappe.migrate import SiteMigration

        SiteMigration().run(site=SITE)
    frappe.init(site=SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")
    from platform_core.identity.provisioning import provision

    provision(settings["identity"])
    frappe.db.commit()
    frappe.destroy()
    print("Isolated MCP test site is ready." if created else "Isolated MCP test site was updated.")


if __name__ == "__main__":
    main()
