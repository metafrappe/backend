"""G-126: the existing OpenAPI registry must stop undocumented custom calls."""

import ast
import json
import re
import unittest
from pathlib import Path

import test_gate as fixtures
from contracts import HTTP_METHODS, method_path, yaml_entries, yaml_text

BACKEND = Path(__file__).resolve().parents[2]
# Frappe lets these guests in; the handler itself checks a token scheme listed in the contract.
TOKEN_CHECKED_GUEST_CALLS = {"platform_core.api.ai.mcp": "The MCP handler verifies the mcpOAuth token itself."}


def guest_functions(apps):
    """Dotted names of production functions whitelisted with allow_guest=True."""
    names = set()
    for path in sorted(apps.glob("*/*/**/*.py")):
        if path.name.startswith("test_") or "tests" in path.parts:
            continue
        module = path.relative_to(apps / path.relative_to(apps).parts[0]).with_suffix("")
        parts = list(module.parts)
        if parts[-1] == "__init__":
            parts.pop()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and getattr(decorator.func, "attr", getattr(decorator.func, "id", "")) == "whitelist"
                    and any(
                        keyword.arg == "allow_guest"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                        for keyword in decorator.keywords
                    )
                ):
                    names.add(".".join([*parts, node.name]))
    return names


def contract_app(path):
    return path.name.removesuffix(".openapi.yaml").removesuffix(".openapi.json").split("-")[0]


def contract_version(path):
    source = path.read_text(encoding="utf-8")
    if source.lstrip().startswith("{"):
        return str(json.loads(source).get("info", {}).get("version", "")).strip()
    match = re.search(r"^info:\n(?:[ \t]+.*\n)*?[ \t]+version:[ \t]*(\S.*)$", source, re.MULTILINE)
    return match.group(1).strip().strip("'\"") if match else ""


def contract_paths(directory):
    return sorted(path for path in directory.iterdir() if path.suffix in {".yaml", ".yml", ".json"})


def valid_security(value):
    return isinstance(value, list) and all(
        isinstance(item, dict)
        and bool(item)
        and all(
            isinstance(name, str)
            and bool(name.strip())
            and isinstance(scopes, list)
            and all(isinstance(scope, str) for scope in scopes)
            for name, scopes in item.items()
        )
        for item in value
    )


def yaml_security(value, children):
    if value == "[]" and not children:
        return True
    if value:
        # The existing contracts use this one-scheme flow form; fail closed for unsupported forms.
        return bool(re.fullmatch(r"\[\{[A-Za-z][\w-]*: \[\]\}\]", value)) and not children
    return bool(children) and children[0][1].lstrip().startswith("- ") and all(
        re.fullmatch(r"(?:-\s+)?[A-Za-z][\w-]*:\s*\[\]", text.strip()) for _, text in children
    )


def documented_error(response):
    if not isinstance(response, dict):
        return False
    return any(isinstance(response.get(key), str) and response[key].strip() for key in ("description", "$ref"))


def yaml_error(value, children):
    if value:
        # Inline response references are common in the mobile contract.
        if re.search(r"\$ref:\s*['\"]#/components/responses/[^'\"]+['\"]", value):
            return True
        # The AI contract writes one-line flow maps with a non-empty description.
        match = re.fullmatch(r"\{description:\s*(.*)\}", value.strip())
        return bool(match) and match.group(1).strip() not in {"", '""', "''"}
    return any(
        key in {"description", "$ref"} and yaml_text(text, nested, line)
        for key, text, line, nested in yaml_entries(children)
    )


class CallRegistryTests(unittest.TestCase):
    def test_every_rpc_contract_has_an_owner_and_status(self):
        source = (BACKEND / "docs/contracts.md").read_text(encoding="utf-8")
        rows = {
            path: (owner.strip(), status.strip())
            for path, owner, status in re.findall(
                r"^\| `contracts/([^`]+)` \| ([^|]+) \| ([^|]+) \|$", source, re.MULTILINE
            )
        }
        for path in contract_paths(BACKEND / "contracts"):
            with self.subTest(contract=path.name):
                self.assertIn(path.name, rows, "Every custom call inherits its contract owner and status")
                owner, status = rows[path.name]
                self.assertTrue(owner)
                self.assertEqual(status, "Etkin")

    def test_each_custom_call_records_authorization_and_errors(self):
        for path in contract_paths(BACKEND / "contracts"):
            for name, method, has_security, errors, _open in self.policy_entries(path):
                if name.startswith("frappe."):
                    continue
                with self.subTest(contract=path.name, call=name, method=method):
                    self.assertTrue(has_security, "Declare security locally or inherit it from the contract")
                    self.assertTrue(errors, "Record at least one error response for the custom call")
                    self.assertTrue(all(errors), "Every declared error needs a description or response reference")

    def test_registry_rejects_empty_policy_and_error_metadata(self):
        for value in (None, {}, "", [None], [{}], [{"session": None}]):
            with self.subTest(security=value):
                self.assertFalse(valid_security(value))
        self.assertTrue(valid_security([]))
        self.assertTrue(valid_security([{"session": []}]))
        for value in ("", "null", "{}", "[{}]", "false"):
            with self.subTest(yaml_security=value):
                self.assertFalse(yaml_security(value, []))
        for value in (None, {}, {"description": ""}, {"$ref": ""}):
            with self.subTest(error=value):
                self.assertFalse(documented_error(value))
        self.assertFalse(yaml_error("{}", []))
        self.assertFalse(yaml_error("", []))
        self.assertFalse(yaml_error("", [(1, 'description: ""')]))
        for value in ('{description: ""}', "{description: ''}", "{description: }", "{summary: Missing}"):
            with self.subTest(yaml_error=value):
                self.assertFalse(yaml_error(value, []))
        self.assertTrue(yaml_error("{description: Unknown method or unknown tool.}", []))
        self.assertTrue(yaml_error('{description: "The proposal does not exist."}', []))

    def test_registry_includes_every_contract_extension_accepted_by_the_gate(self):
        case = self.fixture()
        for name in ("one.json", "two.yml", "three.yaml", "ignored.md"):
            case.write(f"contracts/{name}", "{}")
        self.assertEqual(
            [path.name for path in contract_paths(case.root / "contracts")],
            ["one.json", "three.yaml", "two.yml"],
        )

    def test_contract_table_lists_each_contract_exactly_once(self):
        source = (BACKEND / "docs/contracts.md").read_text(encoding="utf-8")
        listed = re.findall(r"^\| `contracts/([^`]+)` \|", source, re.MULTILINE)
        files = [path.name for path in contract_paths(BACKEND / "contracts")]
        self.assertEqual(sorted(listed), files, "Each contract file appears in the owner table exactly once")

    def test_every_contract_has_a_version(self):
        for path in contract_paths(BACKEND / "contracts"):
            with self.subTest(contract=path.name):
                self.assertTrue(contract_version(path), "info.version records the contract version")

    def test_call_namespace_matches_the_contract_app(self):
        for path in contract_paths(BACKEND / "contracts"):
            for name, method, *_ in self.policy_entries(path):
                if name.startswith("frappe."):
                    continue
                with self.subTest(contract=path.name, call=name, method=method):
                    self.assertEqual(name.split(".")[0], contract_app(path))

    def test_guest_flag_and_empty_security_match_in_both_directions(self):
        guests = guest_functions(BACKEND / "apps")
        open_calls, listed = set(), set()
        for path in contract_paths(BACKEND / "contracts"):
            for name, _method, _has, _errors, is_open in self.policy_entries(path):
                listed.add(name)
                if is_open:
                    open_calls.add(name)
        self.assertTrue(guests, "The scan must find the known guest calls")
        for name in sorted((guests & listed) - set(TOKEN_CHECKED_GUEST_CALLS)):
            with self.subTest(guest_without_open_security=name):
                self.assertIn(name, open_calls, "allow_guest=True needs security: [] in the contract")
        for name in sorted(open_calls - guests):
            with self.subTest(open_security_without_guest=name):
                self.fail(f"{name} has security: [] but its function is not allow_guest=True")
        for name in TOKEN_CHECKED_GUEST_CALLS:
            with self.subTest(token_checked=name):
                self.assertIn(name, guests)
                self.assertNotIn(name, open_calls)

    def test_guest_scan_reads_decorator_flags(self):
        case = self.fixture()
        case.write(
            f"{fixtures.APP}/api.py",
            "import frappe\n\n@frappe.whitelist(allow_guest=True)\ndef open_call():\n    return {}\n\n"
            "@frappe.whitelist(allow_guest=False)\ndef closed_call():\n    return {}\n",
        )
        case.write(f"{fixtures.APP}/test_api.py", "import frappe\n\n@frappe.whitelist(allow_guest=True)\ndef ignored():\n    pass\n")
        self.assertEqual(guest_functions(case.root / "apps"), {f"{fixtures.APP.split('/')[-1]}.api.open_call"})

    @staticmethod
    def policy_entries(path):
        source = path.read_text(encoding="utf-8")
        if source.lstrip().startswith("{"):
            document = json.loads(source)
            for route, methods in document["paths"].items():
                name = method_path(route, 1)
                if not name:
                    continue
                for method, operation in methods.items():
                    if method in HTTP_METHODS:
                        yield (
                            name,
                            method,
                            valid_security(operation.get("security", document.get("security"))),
                            [
                                documented_error(response)
                                for code, response in operation.get("responses", {}).items()
                                if str(code).startswith(("4", "5"))
                            ],
                            operation.get("security", document.get("security")) == [],
                        )
            return
        lines = [
            (number, line.rstrip())
            for number, line in enumerate(source.splitlines(), 1)
            if line.strip() and not line.lstrip().startswith("#") and line not in {"---", "..."}
        ]
        document = {key: (value, line, children) for key, value, line, children in yaml_entries(lines)}
        for route, _value, line, methods in yaml_entries(document["paths"][2]):
            name = method_path(route, line)
            if not name:
                continue
            for method, _value, _line, properties in yaml_entries(methods):
                if method not in HTTP_METHODS:
                    continue
                fields = {key: (value, line, children) for key, value, line, children in yaml_entries(properties)}
                security = fields.get("security", document.get("security", ("null", 1, [])))
                yield (
                    name,
                    method,
                    yaml_security(security[0], security[2]),
                    [
                        yaml_error(value, children)
                        for code, value, _, children in yaml_entries(fields.get("responses", ("", 1, []))[2])
                        if code.startswith(("4", "5"))
                    ],
                    security[0] == "[]" and not security[2],
                )

    def fixture(self):
        case = fixtures.GateTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.write(
            f"{fixtures.APP}/api.py",
            'import frappe\n\n@frappe.whitelist(methods=["POST"])\ndef run():\n    return {}\n',
        )
        return case

    def test_unregistered_custom_call_fails_the_public_gate(self):
        case = self.fixture()
        result = case.run_gate("--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        findings = json.loads(result.stdout)["findings"]
        self.assertTrue(
            any(
                item["rule"] == "endpoint"
                and item["message"] == "Missing OpenAPI operation for sample_app.api.run."
                for item in findings
            ),
            findings,
        )
        case.write_contract()
        accepted = case.run_gate("--json")
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        self.assertEqual(json.loads(accepted.stdout)["findings"], [])

    def test_contract_for_a_different_call_does_not_register_the_missing_call(self):
        case = self.fixture()
        case.write_contract(function="different_call")
        result = case.run_gate("--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        messages = {item["message"] for item in json.loads(result.stdout)["findings"]}
        self.assertIn("Missing OpenAPI operation for sample_app.api.run.", messages)
        self.assertIn("No whitelisted function for sample_app.api.different_call.", messages)


if __name__ == "__main__":
    unittest.main()
