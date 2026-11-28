"""Gate: every `ignore_permissions` bypass in app code complies with G-4.

Rule G-4 requires two safeguards for every production bypass under `apps/`
(excluding test files):

1. Every `ignore_permissions=True` call and every
   `*.flags.ignore_permissions = True` assignment must have a non-empty
   `# ignore-permissions: <reason>` comment on the same line or directly above
   the statement.
2. Every `*.flags.ignore_permissions = True` assignment must restore that flag
   in a `try ... finally` block so the flag cannot leak onto later operations.

Run without Frappe:

    python3.14 -B -m unittest dev/tests/test_ignore_permissions_gate.py
"""

from __future__ import annotations

import ast
import importlib.util
import io
import re
import sys
import tempfile
import tokenize
import types
import unittest
from pathlib import Path
from unittest import mock

APPS = Path(__file__).resolve().parents[2] / "apps"
MARKER = "# ignore-permissions:"
PRAGMA_RE = re.compile(r"#\s*(?:nosemgrep|noqa|type:|ruff:|pylint:)")


def _comments_by_line(source: str) -> dict[int, str]:
    comments: dict[int, str] = {}
    reader = io.StringIO(source).readline
    for token in tokenize.generate_tokens(reader):
        if token.type == tokenize.COMMENT:
            comments[token.start[0]] = token.string
    return comments


def _has_valid_marker(comment: str) -> bool:
    index = comment.find(MARKER)
    if index == -1:
        return False
    if index > 0 and not comment[index - 1].isspace():
        return False
    reason = comment[index + len(MARKER) :]
    reason = PRAGMA_RE.split(reason, maxsplit=1)[0]
    return bool(reason.strip())


def _has_reason(
    lines: list[str],
    comments: dict[int, str],
    target_lines: set[int],
    statement_line: int,
) -> bool:
    for lineno in target_lines:
        comment = comments.get(lineno)
        if comment and _has_valid_marker(comment):
            return True

    index = statement_line - 2
    while index >= 0 and lines[index].strip().startswith("#"):
        comment = comments.get(index + 1)
        if comment and _has_valid_marker(comment):
            return True
        index -= 1

    for lineno in sorted(target_lines):
        if lineno <= statement_line:
            continue
        index = lineno - 2
        while index >= statement_line - 1 and lines[index].strip().startswith("#"):
            comment = comments.get(index + 1)
            if comment and _has_valid_marker(comment):
                return True
            index -= 1

    return False


def _is_truthy_constant(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and bool(node.value)


def _is_flags_attr(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "flags"


def _is_flags_ignore_permissions(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr == "ignore_permissions" and _is_flags_attr(node.value)
    if isinstance(node, ast.Subscript):
        return (
            _is_flags_attr(node.value)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "ignore_permissions"
        )
    return False


def _flag_owner_expr(node: ast.Attribute | ast.Subscript) -> str:
    return ast.unparse(node.value)


def _flag_assign_targets(stmt: ast.stmt) -> list[ast.Attribute | ast.Subscript]:
    if isinstance(stmt, ast.Assign) and _is_truthy_constant(stmt.value):
        return [target for target in stmt.targets if _is_flags_ignore_permissions(target)]
    if isinstance(stmt, ast.AnnAssign) and _is_truthy_constant(stmt.value):
        if _is_flags_ignore_permissions(stmt.target):
            return [stmt.target]
    return []


def _restores_flag(try_node: ast.stmt, owner_expr: str) -> bool:
    finalbody = getattr(try_node, "finalbody", None)
    if not finalbody:
        return False
    for stmt in finalbody:
        if isinstance(stmt, ast.Assign):
            if _is_truthy_constant(stmt.value):
                continue
            if any(
                _is_flags_ignore_permissions(target) and _flag_owner_expr(target) == owner_expr
                for target in stmt.targets
            ):
                return True
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            if _is_truthy_constant(stmt.value):
                continue
            if _is_flags_ignore_permissions(stmt.target) and _flag_owner_expr(stmt.target) == owner_expr:
                return True
    return False


def _is_try_stmt(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Try):
        return True
    return hasattr(ast, "TryStar") and isinstance(stmt, ast.TryStar)


def _iter_statement_exprs(stmt: ast.stmt):
    for child in ast.iter_child_nodes(stmt):
        if isinstance(child, (ast.stmt, ast.ExceptHandler)):
            continue
        if hasattr(ast, "match_case") and isinstance(child, ast.match_case):
            continue
        yield child


def scan_source(source: str) -> list[tuple[int, str]]:
    """Return sorted (line, code) pairs for G-4 violations in `source`."""
    tree = ast.parse(source)
    lines = source.splitlines()
    comments = _comments_by_line(source)
    findings: set[tuple[int, str]] = set()

    def inspect_block(stmts: list[ast.stmt], active_tries: tuple[ast.stmt, ...]) -> None:
        for index, stmt in enumerate(stmts):
            for target in _flag_assign_targets(stmt):
                owner_expr = _flag_owner_expr(target)
                target_lines = {stmt.lineno, target.lineno}
                if not _has_reason(lines, comments, target_lines, stmt.lineno):
                    findings.add((stmt.lineno, "missing-reason"))

                restored = any(_restores_flag(enclosing, owner_expr) for enclosing in active_tries)
                if not restored and index + 1 < len(stmts) and _is_try_stmt(stmts[index + 1]):
                    restored = _restores_flag(stmts[index + 1], owner_expr)
                if not restored:
                    findings.add((stmt.lineno, "missing-finally"))

            for expr in _iter_statement_exprs(stmt):
                for node in ast.walk(expr):
                    if not isinstance(node, ast.Call):
                        continue
                    for keyword in node.keywords:
                        if keyword.arg == "ignore_permissions" and _is_truthy_constant(keyword.value):
                            target_lines = {stmt.lineno, node.lineno, keyword.lineno}
                            if not _has_reason(lines, comments, target_lines, stmt.lineno):
                                findings.add((keyword.lineno, "missing-reason"))

            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inspect_block(stmt.body, ())
            elif _is_try_stmt(stmt):
                inspect_block(stmt.body, (*active_tries, stmt))
                for handler in stmt.handlers:
                    inspect_block(handler.body, active_tries)
                inspect_block(stmt.orelse, active_tries)
                inspect_block(stmt.finalbody, active_tries)
            else:
                for field_name in ("body", "orelse", "finalbody"):
                    nested = getattr(stmt, field_name, None)
                    if isinstance(nested, list):
                        inspect_block(nested, active_tries)
                if hasattr(ast, "Match") and isinstance(stmt, ast.Match):
                    for case in stmt.cases:
                        inspect_block(case.body, active_tries)

    inspect_block(tree.body, ())
    return sorted(findings)


def app_files(root: Path = APPS) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts
        if (
            any(part in ("tests", "test") for part in parts)
            or path.name.startswith("test_")
            or path.name.endswith("_test.py")
        ):
            continue
        files.append(path)
    return files


def gate_problems(root: Path = APPS) -> list[str]:
    """Every G-4 violation under `root`, formatted as `path:line [code]`."""
    problems = []
    for path in app_files(root):
        rel = path.relative_to(root).as_posix()
        for line, code in scan_source(path.read_text(encoding="utf-8")):
            problems.append(f"{rel}:{line} [{code}]")
    return problems


class IgnorePermissionsGateTest(unittest.TestCase):
    def test_app_code_complies_with_g4(self):
        self.maxDiff = None
        message = (
            "Every ignore_permissions=True call and *.flags.ignore_permissions = True "
            "assignment must have a '# ignore-permissions: <reason>' comment, and flag "
            "assignments must restore the previous value in a try/finally block (G-4)."
        )
        self.assertEqual(gate_problems(), [], message)

    def test_scan_finds_app_files(self):
        self.assertGreater(len(app_files()), 50)


class DetectorTest(unittest.TestCase):
    def test_call_without_reason_is_caught(self):
        source = (
            "import frappe\n"
            "doc.save(ignore_permissions=True)\n"
            "frappe.delete_doc('ToDo', '1', ignore_permissions=True)\n"
        )
        self.assertEqual(
            scan_source(source),
            [(2, "missing-reason"), (3, "missing-reason")],
        )

    def test_ignore_permissions_false_is_allowed(self):
        source = "import frappe\nfrappe.get_list('ToDo', ignore_permissions=False)\n"
        self.assertEqual(scan_source(source), [])

    def test_empty_reason_and_pragma_only_reason_fail(self):
        source = (
            "# ignore-permissions:\n"
            "doc.save(ignore_permissions=True)\n"
            "# ignore-permissions:   \n"
            "doc.insert(ignore_permissions=True)\n"
            "doc.delete(ignore_permissions=True)  "
            "# ignore-permissions:  # nosemgrep: frappe-ignore-permissions\n"
        )
        self.assertEqual(
            scan_source(source),
            [(2, "missing-reason"), (4, "missing-reason"), (5, "missing-reason")],
        )

    def test_far_comment_and_string_literal_marker_fail(self):
        source = (
            "# ignore-permissions: separated by code.\n"
            "x = 1\n"
            "doc.save(ignore_permissions=True)\n"
            "# ignore-permissions: separated by blank line.\n"
            "\n"
            "doc.insert(ignore_permissions=True)\n"
            "doc.save('# ignore-permissions: inside string', ignore_permissions=True)\n"
        )
        self.assertEqual(
            scan_source(source),
            [(3, "missing-reason"), (6, "missing-reason"), (7, "missing-reason")],
        )

    def test_valid_call_comments_pass(self):
        source = (
            "# ignore-permissions: internal system write after role check.\n"
            "doc.save(ignore_permissions=True)\n"
            "# Additional context line.\n"
            "# ignore-permissions: verified webhook inserts internal notice.\n"
            "doc.insert(\n"
            "\tignore_permissions=True,\n"
            ")\n"
            "doc.delete(ignore_permissions=True)  "
            "# ignore-permissions: retention purge.  # nosemgrep: frappe-ignore-permissions\n"
        )
        self.assertEqual(scan_source(source), [])

    def test_flag_assignment_without_finally_is_caught(self):
        source = (
            "# ignore-permissions: Tenant Admin syncs plain-role users.\n"
            "user.flags.ignore_permissions = True\n"
            "user.save()\n"
        )
        self.assertEqual(scan_source(source), [(2, "missing-finally")])

    def test_flag_assignment_with_gap_before_try_finally_is_caught(self):
        source = (
            "previous = doc.flags.ignore_permissions\n"
            "# ignore-permissions: internal write.\n"
            "doc.flags.ignore_permissions = True\n"
            "prepare(doc)\n"
            "try:\n"
            "\tdoc.save()\n"
            "finally:\n"
            "\tdoc.flags.ignore_permissions = previous\n"
        )
        self.assertEqual(scan_source(source), [(3, "missing-finally")])

    def test_flag_assignment_without_reason_is_caught(self):
        source = (
            "previous = doc.flags.ignore_permissions\n"
            "doc.flags.ignore_permissions = True\n"
            "try:\n"
            "\tdoc.save()\n"
            "finally:\n"
            "\tdoc.flags.ignore_permissions = previous\n"
        )
        self.assertEqual(scan_source(source), [(2, "missing-reason")])

    def test_flag_assignment_with_invalid_finally_restore_is_caught(self):
        empty_finally = (
            "# ignore-permissions: internal write.\n"
            "doc.flags.ignore_permissions = True\n"
            "try:\n"
            "\tdoc.save()\n"
            "finally:\n"
            "\tpass\n"
        )
        wrong_target = (
            "# ignore-permissions: internal write.\n"
            "doc.flags.ignore_permissions = True\n"
            "try:\n"
            "\tdoc.save()\n"
            "finally:\n"
            "\tother.flags.ignore_permissions = previous\n"
        )
        stays_true = (
            "# ignore-permissions: internal write.\n"
            "doc.flags.ignore_permissions = True\n"
            "try:\n"
            "\tdoc.save()\n"
            "finally:\n"
            "\tdoc.flags.ignore_permissions = True\n"
        )
        self.assertEqual(scan_source(empty_finally), [(2, "missing-finally")])
        self.assertEqual(scan_source(wrong_target), [(2, "missing-finally")])
        self.assertEqual(
            scan_source(stays_true),
            [(2, "missing-finally"), (6, "missing-finally"), (6, "missing-reason")],
        )

    def test_flag_assignment_inside_nested_function_in_try_is_caught(self):
        source = (
            "previous = doc.flags.ignore_permissions\n"
            "try:\n"
            "\tdef helper():\n"
            "\t\t# ignore-permissions: internal write.\n"
            "\t\tdoc.flags.ignore_permissions = True\n"
            "\t\tdoc.save()\n"
            "finally:\n"
            "\tdoc.flags.ignore_permissions = previous\n"
        )
        self.assertEqual(scan_source(source), [(5, "missing-finally")])

    def test_valid_flag_assignments_pass(self):
        before_try = (
            "previous = doc.flags.ignore_permissions\n"
            "# ignore-permissions: internal system record write.\n"
            "doc.flags.ignore_permissions = True  # nosemgrep: frappe-ignore-permissions\n"
            "try:\n"
            "\tdoc.save()\n"
            "finally:\n"
            "\tdoc.flags.ignore_permissions = previous\n"
        )
        inside_try = (
            "previous = frappe.flags.ignore_permissions\n"
            "try:\n"
            "\t# ignore-permissions: migration step.\n"
            "\tfrappe.flags.ignore_permissions = True\n"
            "\tapply_step()\n"
            "finally:\n"
            "\tfrappe.flags.ignore_permissions = previous\n"
        )
        self.assertEqual(scan_source(before_try), [])
        self.assertEqual(scan_source(inside_try), [])

    def test_gate_skips_test_files_and_catches_new_production_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "app" / "tests").mkdir(parents=True)
            (root / "app" / "module.py").write_text(
                "doc.save(ignore_permissions=True)\n",
                encoding="utf-8",
            )
            (root / "app" / "test_module.py").write_text(
                "doc.save(ignore_permissions=True)\n",
                encoding="utf-8",
            )
            (root / "app" / "tests" / "helper.py").write_text(
                "doc.flags.ignore_permissions = True\n",
                encoding="utf-8",
            )
            self.assertEqual(gate_problems(root), ["app/module.py:1 [missing-reason]"])

    def test_conditional_finally_restore_is_caught(self):
        cases = {
            "if": (
                "# ignore-permissions: internal write.\n"
                "doc.flags.ignore_permissions = True\n"
                "try:\n"
                "\tdoc.save()\n"
                "finally:\n"
                "\tif should_restore:\n"
                "\t\tdoc.flags.ignore_permissions = previous\n"
            ),
            "for": (
                "# ignore-permissions: internal write.\n"
                "doc.flags.ignore_permissions = True\n"
                "try:\n"
                "\tdoc.save()\n"
                "finally:\n"
                "\tfor _item in items:\n"
                "\t\tdoc.flags.ignore_permissions = previous\n"
            ),
            "except": (
                "# ignore-permissions: internal write.\n"
                "doc.flags.ignore_permissions = True\n"
                "try:\n"
                "\tdoc.save()\n"
                "finally:\n"
                "\ttry:\n"
                "\t\tcleanup()\n"
                "\texcept RuntimeError:\n"
                "\t\tdoc.flags.ignore_permissions = previous\n"
            ),
            "match": (
                "# ignore-permissions: internal write.\n"
                "doc.flags.ignore_permissions = True\n"
                "try:\n"
                "\tdoc.save()\n"
                "finally:\n"
                "\tmatch state:\n"
                '\t\tcase "done":\n'
                "\t\t\tdoc.flags.ignore_permissions = previous\n"
            ),
        }
        for name, source in cases.items():
            with self.subTest(block=name):
                self.assertEqual(scan_source(source), [(2, "missing-finally")])

    def test_subscript_flag_assignment_is_caught_and_restored(self):
        unrestored = 'doc.flags["ignore_permissions"] = True\ndoc.save()\n'
        self.assertEqual(
            scan_source(unrestored),
            [(1, "missing-finally"), (1, "missing-reason")],
        )
        missing_finally = (
            '# ignore-permissions: internal write.\ndoc.flags["ignore_permissions"] = True\ndoc.save()\n'
        )
        self.assertEqual(scan_source(missing_finally), [(2, "missing-finally")])
        valid_subscript = (
            'previous = doc.flags.get("ignore_permissions")\n'
            "# ignore-permissions: internal write.\n"
            'doc.flags["ignore_permissions"] = True\n'
            "try:\n"
            "\tdoc.save()\n"
            "finally:\n"
            '\tdoc.flags["ignore_permissions"] = previous\n'
        )
        self.assertEqual(scan_source(valid_subscript), [])
        valid_mixed_restore = (
            "previous = doc.flags.ignore_permissions\n"
            "# ignore-permissions: internal write.\n"
            'doc.flags["ignore_permissions"] = True\n'
            "try:\n"
            "\tdoc.save()\n"
            "finally:\n"
            "\tdoc.flags.ignore_permissions = previous\n"
        )
        self.assertEqual(scan_source(valid_mixed_restore), [])
        stays_true = (
            "# ignore-permissions: internal write.\n"
            'doc.flags["ignore_permissions"] = True\n'
            "try:\n"
            "\tdoc.save()\n"
            "finally:\n"
            '\tdoc.flags["ignore_permissions"] = True\n'
        )
        self.assertEqual(
            scan_source(stays_true),
            [(2, "missing-finally"), (6, "missing-finally"), (6, "missing-reason")],
        )

    def test_truthy_constant_ignore_permissions_is_caught(self):
        truthy_calls = 'doc.save(ignore_permissions=1)\ndoc.insert(ignore_permissions="yes")\n'
        self.assertEqual(
            scan_source(truthy_calls),
            [(1, "missing-reason"), (2, "missing-reason")],
        )
        truthy_flags = 'doc.flags.ignore_permissions = 1\ndoc.flags["ignore_permissions"] = 1\n'
        self.assertEqual(
            scan_source(truthy_flags),
            [
                (1, "missing-finally"),
                (1, "missing-reason"),
                (2, "missing-finally"),
                (2, "missing-reason"),
            ],
        )
        falsy = (
            "doc.save(ignore_permissions=0)\n"
            "doc.save(ignore_permissions=None)\n"
            "doc.flags.ignore_permissions = 0\n"
            'doc.flags["ignore_permissions"] = False\n'
        )
        self.assertEqual(scan_source(falsy), [])


class _FakeFlags(dict):
    def __getattr__(self, name: str):
        return self.get(name)

    def __setattr__(self, name: str, value) -> None:
        self[name] = value


class _FakeExceptionDoc:
    def __init__(self, *, initial_ignore_permissions, fail_on_save: bool = False):
        self.name = "EIDP-0001"
        self.kind = "grant"
        self.provider_alias = "acme-entra"
        self.issuer = "https://login.microsoftonline.com/tenant/v2.0"
        self.organization = "acme"
        self.supersedes = None
        self.reason = "The provider omits email_verified."
        self.provider_document = "https://docs.example/provider"
        self.expires_on = None
        self.requested_by = "owner@example.test"
        self.approved_by = None
        self.approved_on = None
        self.approval_principal = None
        self.allowed_domains = []
        self.flags = _FakeFlags()
        if initial_ignore_permissions is not None:
            self.flags.ignore_permissions = initial_ignore_permissions
        self.save_calls: list[bool] = []
        self._fail_on_save = fail_on_save

    def get(self, field: str, default=None):
        return getattr(self, field, default)

    def save(self, *, ignore_permissions: bool = False):
        self.save_calls.append(ignore_permissions)
        if ignore_permissions:
            self.flags.ignore_permissions = True
        if self._fail_on_save:
            raise RuntimeError("save failed")
        return self


def _load_enterprise_membership(doc: _FakeExceptionDoc):
    frappe_mod = types.ModuleType("frappe")
    frappe_mod._ = lambda text, context=None: text
    frappe_mod.ValidationError = type("ValidationError", (Exception,), {})
    frappe_mod.PermissionError = type("PermissionError", (Exception,), {})
    frappe_mod.session = types.SimpleNamespace(user="security@example.test", data={})
    frappe_mod.only_for = lambda role: None
    frappe_mod.get_doc = lambda doctype, name: doc
    frappe_mod.get_all = lambda *args, **kwargs: []
    frappe_mod.whitelist = lambda *args, **kwargs: lambda fn: fn

    def _throw(message, exc=None):
        raise (exc or frappe_mod.ValidationError)(message)

    frappe_mod.throw = _throw

    utils_mod = types.ModuleType("frappe.utils")
    utils_mod.get_datetime = lambda value: value
    utils_mod.get_system_timezone = lambda: "UTC"
    utils_mod.now_datetime = lambda: None
    frappe_mod.utils = utils_mod

    pkg_root = types.ModuleType("platform_core")
    pkg_identity = types.ModuleType("platform_core.identity")
    rules_mod = types.ModuleType("platform_core.identity.enterprise_rules")
    rules_mod.APPROVAL_PRINCIPAL = "human_session"
    rules_mod.EnterpriseRuleError = type("EnterpriseRuleError", (Exception,), {})
    rules_mod.check_record = lambda record: record
    pkg_identity.enterprise_rules = rules_mod
    pkg_root.identity = pkg_identity

    stubs = {
        "frappe": frappe_mod,
        "frappe.utils": utils_mod,
        "platform_core": pkg_root,
        "platform_core.identity": pkg_identity,
        "platform_core.identity.enterprise_rules": rules_mod,
    }
    module_path = APPS / "platform_core/platform_core/identity/enterprise_membership.py"
    spec = importlib.util.spec_from_file_location("_test_enterprise_membership", module_path)
    assert spec is not None and spec.loader is not None
    with mock.patch.dict(sys.modules, stubs):
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, stubs


class EnterpriseMembershipApproveFlagTest(unittest.TestCase):
    def test_approve_restores_ignore_permissions_on_returned_doc(self):
        for previous in (False, None):
            with self.subTest(previous=previous):
                doc = _FakeExceptionDoc(initial_ignore_permissions=previous)
                module, stubs = _load_enterprise_membership(doc)
                with mock.patch.dict(sys.modules, stubs):
                    returned = module.approve(doc.name, principal="human_session")
                self.assertIs(returned, doc)
                self.assertEqual(doc.save_calls, [True])
                self.assertEqual(returned.flags.ignore_permissions, previous)

    def test_approve_restores_ignore_permissions_when_save_raises(self):
        doc = _FakeExceptionDoc(initial_ignore_permissions=False, fail_on_save=True)
        module, stubs = _load_enterprise_membership(doc)
        with mock.patch.dict(sys.modules, stubs):
            with self.assertRaisesRegex(RuntimeError, "save failed"):
                module.approve(doc.name, principal="human_session")
        self.assertEqual(doc.save_calls, [True])
        self.assertFalse(doc.flags.ignore_permissions)


if __name__ == "__main__":
    unittest.main()
