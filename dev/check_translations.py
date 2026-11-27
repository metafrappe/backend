"""Report user messages in backend app code that skip the translation catalog (G-73).

A message passed to ``frappe.throw`` or ``frappe.msgprint`` must go through ``_()``.
A plain, formatted or joined string literal is reported with its line number.
Tests and patches are skipped, because they do not show text to users.
"""

import ast
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APPS = BACKEND / "apps"
MESSAGE_FUNCTIONS = {"throw", "msgprint"}
MESSAGE_KEYWORDS = {"msg", "title"}
SKIPPED_PARTS = {"tests", "patches", "node_modules", "__pycache__"}


def is_literal_text(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp):
        return is_literal_text(node.left) or is_literal_text(node.right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr == "format" and is_literal_text(node.func.value)
    return False


def message_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Return local names for the frappe module and for its message functions."""
    modules, functions = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.asname or alias.name for alias in node.names if alias.name == "frappe")
        elif isinstance(node, ast.ImportFrom) and node.module == "frappe":
            functions.update(
                alias.asname or alias.name for alias in node.names if alias.name in MESSAGE_FUNCTIONS
            )
    return modules, functions


def is_message_call(node: ast.Call, modules: set[str], functions: set[str]) -> bool:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id in functions
    return (
        isinstance(target, ast.Attribute)
        and target.attr in MESSAGE_FUNCTIONS
        and isinstance(target.value, ast.Name)
        and target.value.id in modules
    )


def violations(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules, functions = message_names(tree)
    lines = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not is_message_call(node, modules, functions):
            continue
        arguments = node.args[:1] + [item.value for item in node.keywords if item.arg in MESSAGE_KEYWORDS]
        if any(is_literal_text(argument) for argument in arguments):
            lines.add(node.lineno)
    return sorted(lines)


def source_files() -> list[Path]:
    return sorted(
        path
        for path in APPS.rglob("*.py")
        if not SKIPPED_PARTS.intersection(path.relative_to(APPS).parts) and not path.name.startswith("test_")
    )


def main() -> int:
    failed = False
    for path in source_files():
        for line in violations(path):
            failed = True
            print(f"{path.relative_to(BACKEND)}:{line}: user message must use _()")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
