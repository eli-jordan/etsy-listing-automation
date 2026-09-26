#!/usr/bin/env python
"""Count code, ignoring the prose that explains it.

Physical line count is the wrong measure for this repository. Both documents
and most modules are deliberately heavy on rationale -- CLAUDE.md asks for it,
because a decision without its reason is a decision that gets silently
reversed -- so a "shrink the codebase" pass measured in physical lines scores
its biggest wins by deleting the most valuable text.

So this strips blank lines, comments and docstring bodies, and counts what is
left. A refactoring only registers here when logic actually disappears.

    uv run python scripts/sloc.py            # src and tests, per file
    uv run python scripts/sloc.py --summary  # just the totals
    uv run python scripts/sloc.py src/etsy_listings/engine

Frontend TypeScript is counted too, minus the generated OpenAPI client, which
nobody writes and nobody should be credited for shrinking.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_ROOTS = ("src", "tests")

SKIP_PARTS = frozenset({"node_modules", "dist", "coverage", "__pycache__", ".venv", "htmlcov"})
GENERATED = ("api/schema.ts",)
"""Written by `npm run gen:api` from the OpenAPI document. Real code, but not
authored, so counting it would reward regenerating it smaller."""


def python_sloc(source: str) -> int:
    """Lines of Python that are neither blank, a comment, nor a docstring.

    Docstrings are found through the AST rather than by matching quotes: a
    triple-quoted string that is *not* a docstring is data, and deleting it
    would change behaviour, so it counts.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return sum(1 for line in source.splitlines() if line.strip())

    prose: set[int] = set()
    for node in ast.walk(tree):
        # A bare string expression statement: a module/class/function
        # docstring, or one of the attribute docstrings this codebase uses to
        # explain a constant.
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.end_lineno is not None
        ):
            prose.update(range(node.lineno, node.end_lineno + 1))

    return sum(
        1
        for number, line in enumerate(source.splitlines(), start=1)
        if line.strip() and not line.lstrip().startswith("#") and number not in prose
    )


def typescript_sloc(source: str) -> int:
    """The same, approximately, for TS/TSX.

    Approximate on purpose: a real parse would mean a node dependency for a
    number, and `//`, `/* */` and `*` continuation lines cover essentially all
    of this codebase's comments. A `//` inside a string literal is miscounted;
    at this scale it does not move the total.
    """
    total = 0
    in_block = False
    for raw in source.splitlines():
        line = raw.strip()
        if in_block:
            if "*/" in line:
                in_block = False
            continue
        if not line or line.startswith("//"):
            continue
        if line.startswith("/*"):
            in_block = "*/" not in line
            continue
        if line.startswith("*"):
            continue
        total += 1
    return total


def measure(path: Path) -> int:
    source = path.read_text(encoding="utf-8", errors="replace")
    return python_sloc(source) if path.suffix == ".py" else typescript_sloc(source)


def files(roots: list[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file():
            yield root
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in (".py", ".ts", ".tsx") or not path.is_file():
                continue
            if SKIP_PARTS & set(path.parts):
                continue
            if any(str(path).replace("\\", "/").endswith(g) for g in GENERATED):
                continue
            yield path


BUCKETS = ("src", "tests", "frontend", "frontend tests")


def bucket(path: Path) -> str:
    """Which of the four gated bodies of code this file belongs to.

    Four, not two: the Python and frontend suites carry separate 85% floors
    and separate runners, so rolling them together would hide one moving under
    the other.
    """
    text = str(path).replace("\\", "/")
    if path.suffix in (".ts", ".tsx"):
        return "frontend tests" if ".test." in text or "/test/" in text else "frontend"
    return "tests" if text.startswith("tests/") else "src"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", default=list(DEFAULT_ROOTS))
    parser.add_argument("--summary", action="store_true", help="totals only")
    args = parser.parse_args()

    roots = [Path(r) if Path(r).is_absolute() else REPO / r for r in args.roots]
    missing = [r for r in roots if not r.exists()]
    if missing:
        print(f"no such path: {missing[0]}", file=sys.stderr)
        return 2

    rows = [(measure(path), path.relative_to(REPO)) for path in files(roots)]
    totals: dict[str, int] = {}
    for count, path in rows:
        totals[bucket(path)] = totals.get(bucket(path), 0) + count

    if not args.summary:
        for count, path in sorted(rows, reverse=True):
            print(f"{count:6d}  {str(path).replace(chr(92), '/')}")
        print()

    for name in BUCKETS:
        if name in totals:
            print(f"{totals[name]:6d}  {name}")
    print(f"{sum(totals.values()):6d}  total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
