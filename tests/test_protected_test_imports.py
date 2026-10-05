"""Only a protected module's own tests import it (ADR-0052; module-structure
plan, PR 11).

Import Linter's ``protected`` contracts in ``pyproject.toml`` name the
implementation-only modules behind core's application interfaces -- the
deployment worker behind ``Deployments``, the AI run thread behind
``AiCoordinator`` -- and admit only their coordinators as importers. Those
contracts see ``etsy_listings`` alone: ``tests/`` is not a package, so its
imports are outside their graph.

Tests still need a rule, or an operation test that reaches past the
coordinator would quietly certify the implementation as an interface. So
this reads the same contracts and allows a test file to import a protected
module only where :data:`OWNING_TESTS` names it as that module's own test.
Shared doubles in ``tests/support`` are never owners: what every layer leans
on must be public.
"""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

OWNING_TESTS: Mapping[str, frozenset[str]] = {
    # Numerical preparation is tested through prepare; sampling through the
    # public CPU scene renderer. No test may bypass those agreed seams.
    "etsy_listings.core.preparation._geometry": frozenset(),
    "etsy_listings.core.render._material_math": frozenset(),
    "etsy_listings.core.preparation.installation": frozenset(
        {"tests/core/unit/test_marigold_installation.py"}
    ),
    "etsy_listings.core.application.deploy.executor": frozenset(
        {"tests/core/behaviour/test_runs_executor.py"}
    ),
    "etsy_listings.core.application.deploy.review": frozenset(),
    "etsy_listings.core.application.ai.runner": frozenset(
        {
            "tests/core/behaviour/test_ai_runner.py",
            # The queue is the runner's other caller inside ``application.ai``,
            # and its test drives the two together (plan, PR 9).
            "tests/core/behaviour/test_batch_queue.py",
        }
    ),
}
"""Each protected module's own tests, as paths from the repository root."""


def protected_modules(pyproject: Path) -> frozenset[str]:
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return frozenset(
        module
        for contract in config["tool"]["importlinter"]["contracts"]
        if contract["type"] == "protected"
        for module in contract["protected_modules"]
    )


def imported_modules(source: str) -> Iterator[str]:
    """Every module a file's import statements could name, including
    ``from package import module``."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def unowned_imports(
    tests: Path, protected: frozenset[str], owners: Mapping[str, frozenset[str]]
) -> list[str]:
    root = tests.parent
    found = []
    for path in sorted(tests.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        for module in imported_modules(path.read_text(encoding="utf-8")):
            if module in protected and relative not in owners.get(module, frozenset()):
                found.append(f"{relative} imports {module}")
    return found


def test_every_protected_module_has_a_decision_about_its_tests() -> None:
    assert protected_modules(ROOT / "pyproject.toml") == set(OWNING_TESTS)


def test_only_a_protected_module_s_own_tests_import_it() -> None:
    assert unowned_imports(TESTS, protected_modules(ROOT / "pyproject.toml"), OWNING_TESTS) == []


@pytest.mark.parametrize(
    ("module", "owner"),
    [(module, owner) for module, owners in OWNING_TESTS.items() for owner in sorted(owners)],
)
def test_a_named_owner_really_tests_its_module(module: str, owner: str) -> None:
    assert module in set(imported_modules((ROOT / owner).read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "statement",
    [
        "from etsy_listings.core.application.deploy.executor import RunExecutor\n",
        "from etsy_listings.core.application.deploy import executor\n",
        "import etsy_listings.core.application.ai.runner\n",
    ],
)
def test_an_operation_test_reaching_past_its_coordinator_is_reported(
    tmp_path: Path, statement: str
) -> None:
    tests = tmp_path / "tests"
    (tests / "core" / "behaviour").mkdir(parents=True)
    (tests / "core" / "behaviour" / "test_deployments.py").write_text(statement, encoding="utf-8")

    found = unowned_imports(tests, protected_modules(ROOT / "pyproject.toml"), OWNING_TESTS)

    assert len(found) == 1
    assert found[0].startswith("tests/core/behaviour/test_deployments.py imports ")
