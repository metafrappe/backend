"""Compare the API ownership registry with the whitelisted methods in the apps (G-126).

Every whitelisted method and every `override_whitelisted_methods` entry in `apps/` needs one
record in `contracts/api-ownership.json`. A record names the endpoint, owner app and file, owner
team, status and version. Methods and access must match the decorator in the code. An endpoint
without a record, or a record without an endpoint, makes the check fail.

Run: python3 -I backend/dev/api_ownership/registry_check.py backend
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "security"))

from endpoints import (  # noqa: E402
    definitions,
    frappe_names,
    guest_access,
    is_whitelist,
    method_list,
    read_tree,
)

REGISTRY = "contracts/api-ownership.json"
STATUSES = ("upstream-ready", "new-custom", "upstream-patch")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
ENDPOINT_FIELDS = ("app", "file", "owner_team", "status", "version")
OVERRIDE_FIELDS = ("target", "app", "owner_team", "status", "version")


def scan(apps: Path) -> tuple[dict, dict, list[str]]:
    """Return whitelisted methods, overrides and read errors found in the app sources."""
    endpoints = {}
    overrides = {}
    errors = []
    if not apps.is_dir():
        return endpoints, overrides, [f"Application directory not found: {apps}"]
    for path in sorted(apps.rglob("*.py")):
        relative = path.relative_to(apps)
        if (
            len(relative.parts) < 3
            or path.name.startswith("test_")
            or any(part.startswith(".") for part in relative.parts)
        ):
            continue
        try:
            tree = read_tree(path)
        except (OSError, SyntaxError, UnicodeError) as error:
            errors.append(f"Could not read {relative}: {error}")
            continue
        file = (Path("apps") / relative).as_posix()
        imports = relative.with_suffix("").parts[1:]
        module = ".".join(imports[:-1] if path.name == "__init__.py" else imports)
        modules, decorators, _ = frappe_names(tree)
        for name, statement in definitions(tree):
            for decorator in statement.decorator_list:
                if is_whitelist(decorator, modules, decorators):
                    access = {True: "guest", False: "authenticated", None: "unknown"}
                    endpoints[f"{module}.{name}"] = {
                        "app": relative.parts[0],
                        "file": file,
                        "methods": method_list(decorator),
                        "access": access[guest_access(decorator)],
                    }
        if path.name == "hooks.py":
            for name, target in hook_overrides(tree):
                overrides[name] = {"app": relative.parts[0], "target": target}
    return endpoints, overrides, errors


def hook_overrides(tree: ast.Module) -> list[tuple[str, str]]:
    found = []
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or not isinstance(statement.value, ast.Dict):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "override_whitelisted_methods"
            for target in statement.targets
        ):
            continue
        for key, value in zip(statement.value.keys, statement.value.values):
            if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
                found.append((str(key.value), str(value.value)))
    return found


def records(registry: dict, section: str, fields: tuple, errors: list[str]) -> dict:
    result = {}
    entries = registry.get(section)
    if not isinstance(entries, list):
        errors.append(f"{REGISTRY}: '{section}' must be a list.")
        return result
    for entry in entries:
        name = entry.get("endpoint") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{REGISTRY}: a '{section}' record has no endpoint name.")
            continue
        if name in result:
            errors.append(f"{name} is registered twice.")
            continue
        result[name] = entry
        for field in fields:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{name}: {field} is missing or empty.")
        if entry.get("status") not in STATUSES:
            errors.append(f"{name}: status must be one of {', '.join(STATUSES)}.")
        if isinstance(entry.get("version"), str) and not VERSION.match(entry["version"]):
            errors.append(f"{name}: version must look like 1.2.3.")
    return result


def compare(found: dict, registered: dict, keys: tuple, errors: list[str]) -> None:
    for name in sorted(found.keys() - registered.keys()):
        errors.append(f"{name} is not in the API ownership registry ({REGISTRY}).")
    for name in sorted(registered.keys() - found.keys()):
        errors.append(f"{name} is registered but not whitelisted in the apps.")
    for name in sorted(found.keys() & registered.keys()):
        for key in keys:
            expected = found[name][key]
            actual = registered[name].get(key)
            if key == "methods" and isinstance(actual, list):
                actual = ", ".join(actual)
            if actual != expected:
                errors.append(f"{name}: {key} is {actual!r} in the registry but {expected!r} in the code.")


def check(backend: Path) -> list[str]:
    path = backend / REGISTRY
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"{REGISTRY} is missing."]
    except (OSError, ValueError) as error:
        return [f"Could not read {REGISTRY}: {error}"]
    if not isinstance(registry, dict):
        return [f"{REGISTRY} must be a JSON object."]

    found_endpoints, found_overrides, errors = scan(backend / "apps")
    endpoints = records(registry, "endpoints", ENDPOINT_FIELDS, errors)
    overrides = records(registry, "overrides", OVERRIDE_FIELDS, errors)
    compare(found_endpoints, endpoints, ("app", "file", "methods", "access"), errors)
    compare(found_overrides, overrides, ("app", "target"), errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("backend", type=Path, help="Backend directory")
    args = parser.parse_args()
    errors = check(args.backend)
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f"{REGISTRY} matches every whitelisted method and override.")
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
