"""Tenant site endpoint inventory (G-143).

The inventory lists every `/api/method/*` endpoint that a tenant site serves, with the client that
calls it. It also lists the Frappe Desk methods a tenant site still needs, each with a reason.
The edge server allow list is built from this file later; this script does not change any server.

    python3.14 -B dev/security/tenant_endpoints.py .          # check, exit 1 when stale
    python3.14 -B dev/security/tenant_endpoints.py --write .  # add new rows as "unclassified"
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

from endpoints import inventory

INVENTORY = Path("dev/security/tenant-endpoints.json")
UNCLASSIFIED = "unclassified"
METHOD_PREFIX = "/api/method/"
ENTRY = re.compile(r"^(?P<route>\S+) \[(?P<methods>[^\]]*)\] \[(?P<access>\w+)\]$")


def load(backend: Path) -> dict:
    return json.loads((backend / INVENTORY).read_text(encoding="utf-8"))


def scan(backend: Path, apps: list[str]) -> tuple[dict[str, dict], list[str]]:
    """Return the endpoints of the tenant apps by route, and the files that could not be read."""
    routes, _, errors = inventory(backend / "apps")
    found = {}
    for entry in routes:
        match = ENTRY.match(entry)
        if not match or not match["route"].startswith(METHOD_PREFIX):
            continue
        module = match["route"][len(METHOD_PREFIX) :]
        if module.split(".", 1)[0] not in apps:
            continue
        found[match["route"]] = {
            "methods": [method.strip() for method in match["methods"].split(",")],
            "access": match["access"],
        }
    unreadable = [
        error
        for error in errors
        if error.startswith("Could not read ") and error[len("Could not read ") :].split("/", 1)[0] in apps
    ]
    return found, unreadable


def hook_values(backend: Path, apps: list[str]) -> tuple[dict[str, str], list[str]]:
    """Read `override_whitelisted_methods` and `website_user_allowed_methods` of the tenant apps."""
    overrides: dict[str, str] = {}
    allowed: list[str] = []
    for app in apps:
        path = backend / "apps" / app / app / "hooks.py"
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for statement in tree.body:
            if not isinstance(statement, ast.Assign):
                continue
            names = {target.id for target in statement.targets if isinstance(target, ast.Name)}
            if "override_whitelisted_methods" in names:
                overrides.update(ast.literal_eval(statement.value))
            if "website_user_allowed_methods" in names:
                allowed.extend(ast.literal_eval(statement.value))
    return overrides, allowed


def check(backend: Path) -> list[str]:
    data = load(backend)
    apps = data["apps"]
    sources = data["sources"]
    found, problems = scan(backend, apps)
    overrides, allowed = hook_values(backend, apps)
    override_targets = set(overrides.values())
    listed = {row["route"]: row for row in data["endpoints"]}

    for route in sorted(found.keys() - listed.keys()):
        problems.append(f"{route} is missing from {INVENTORY}.")
    for route in sorted(listed.keys() - found.keys()):
        problems.append(f"{route} is no longer in the code. Remove it from {INVENTORY}.")
    for route in sorted(found.keys() & listed.keys()):
        row, code = listed[route], found[route]
        if row["methods"] != code["methods"]:
            problems.append(f"{route} methods are {code['methods']} in the code, not {row['methods']}.")
        if row["access"] != code["access"]:
            problems.append(f"{route} access is {code['access']} in the code, not {row['access']}.")

    for route, row in sorted(listed.items()):
        if row.get("source") not in sources:
            problems.append(f"{route} has no known source: {row.get('source')!r}.")
        if not str(row.get("evidence", "")).strip():
            problems.append(f"{route} has no evidence of its caller.")
        if row.get("source") == "override" and route[len(METHOD_PREFIX) :] not in override_targets:
            problems.append(f"{route} is marked override but no override_whitelisted_methods entry uses it.")

    desk = {row["route"]: row for row in data["desk"]}
    for route, row in sorted(desk.items()):
        if not str(row.get("reason", "")).strip():
            problems.append(f"Desk method {route} has no reason.")
        if not row.get("methods"):
            problems.append(f"Desk method {route} has no methods.")
        handler = row.get("handler")
        if handler and overrides.get(route[len(METHOD_PREFIX) :]) != handler:
            problems.append(
                f"Desk method {route}: override_whitelisted_methods does not send it to {handler}."
            )

    for method in allowed:
        route = METHOD_PREFIX + method
        if route not in listed and route not in desk:
            problems.append(f"{method} is in website_user_allowed_methods but not in {INVENTORY}.")
    return problems


def update(backend: Path) -> None:
    """Write the scanned routes, methods and access; keep the existing source and evidence."""
    data = load(backend)
    found, _ = scan(backend, data["apps"])
    old = {row["route"]: row for row in data["endpoints"]}
    data["endpoints"] = [
        {
            "route": route,
            **code,
            "source": old.get(route, {}).get("source", UNCLASSIFIED),
            "evidence": old.get(route, {}).get("evidence", ""),
        }
        for route, code in sorted(found.items())
    ]
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    (backend / INVENTORY).write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the tenant site endpoint inventory.")
    parser.add_argument("backend", type=Path, help="Backend directory")
    parser.add_argument("--write", action="store_true", help="Update routes from the code first")
    args = parser.parse_args()
    if args.write:
        update(args.backend)
    problems = check(args.backend)
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"{INVENTORY} matches the code.")
    return int(bool(problems))


if __name__ == "__main__":
    sys.exit(main())
