"""A function named ``*_locked`` expects its caller to hold a lock. It may be
called only inside a ``with`` whose context expression names a lock or
condition, or from another ``*_locked`` function."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
GUARD = re.compile(r"lock|condition", re.IGNORECASE)

ALLOWED = {
    # The lambda runs inside Preparations.rename_template, under both templates' locks.
    ("src/etsy_listings/core/application/template_rename.py", "_move_locked"),
}


def unguarded_calls(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    _visit(tree, found, guarded=False)
    return found


def _visit(node: ast.AST, found: list[tuple[int, str]], *, guarded: bool) -> None:
    for child in ast.iter_child_nodes(node):
        if not guarded and isinstance(child, ast.Call) and _callee(child.func).endswith("_locked"):
            found.append((child.lineno, _callee(child.func)))
        _visit(child, found, guarded=_guards(child, inherited=guarded))


def _guards(node: ast.AST, *, inherited: bool) -> bool:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return node.name.endswith("_locked")
    if isinstance(node, ast.Lambda):
        return False
    if isinstance(node, ast.With | ast.AsyncWith):
        return inherited or any(GUARD.search(ast.unparse(i.context_expr)) for i in node.items)
    return inherited


def _callee(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def test_locked_functions_are_called_only_with_a_lock_held() -> None:
    violations = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        violations += [
            f"{relative}:{line} calls {name}"
            for line, name in unguarded_calls(tree)
            if (relative, name) not in ALLOWED
        ]
    assert violations == []


def test_the_rule_catches_an_unguarded_call() -> None:
    source = """
def outside(self):
    self._admit_locked()
    with self.lock(x), self.store.condition:
        self._admit_locked()
        callback = lambda: self._admit_locked()
    with open(path):
        self._admit_locked()

def _caller_locked(self):
    self._admit_locked()
"""
    assert unguarded_calls(ast.parse(source)) == [
        (3, "_admit_locked"),
        (6, "_admit_locked"),
        (8, "_admit_locked"),
    ]
