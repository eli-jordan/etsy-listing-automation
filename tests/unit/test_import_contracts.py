"""The Import Linter contracts reject what they exist to reject (ADR-0052).

``uv run lint-imports`` passing on the real tree only shows the tree is
clean; it cannot show the contracts would notice a violation. So each test
runs the real contracts -- this repository's ``pyproject.toml``, copied
verbatim -- over an isolated fixture tree in ``tmp_path`` that mirrors the
modules the contracts name, then adds one representative import. The real
source is never edited to prove a point.

The fixture contains every import edge the contracts deliberately ignore
(Import Linter reports an ignored import that matches nothing), so the
unmodified fixture is the passing control.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "etsy_listings"


def _contracts() -> list[dict[str, Any]]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts: list[dict[str, Any]] = config["tool"]["importlinter"]["contracts"]
    return contracts


def _write_module(tree: Path, module: str, body: str = "") -> None:
    """``module`` as a package directory, appending ``body`` to its
    ``__init__.py`` -- a package stands in equally well for a module here."""
    path = tree.joinpath(*module.split("."))
    for depth in range(1, len(module.split(".")) + 1):
        init = tree.joinpath(*module.split(".")[:depth]) / "__init__.py"
        init.parent.mkdir(parents=True, exist_ok=True)
        init.touch()
    with (path / "__init__.py").open("a", encoding="utf-8") as handle:
        handle.write(body)


def _fixture(tmp_path: Path) -> Path:
    tree = tmp_path / "tree"
    tree.mkdir()
    shutil.copyfile(ROOT / "pyproject.toml", tree / "pyproject.toml")
    for contract in _contracts():
        for key in ("source_modules", "forbidden_modules"):
            for module in contract.get(key, []):
                if module.startswith(PACKAGE):
                    _write_module(tree, module)
        for edge in contract.get("ignore_imports", []):
            importer, imported = (part.strip() for part in edge.split("->"))
            _write_module(tree, imported)
            _write_module(tree, importer, f"import {imported}\n")
    # Command registration reaching the launcher is intended (plan, PR 5).
    _write_module(tree, f"{PACKAGE}.cli.app", f"import {PACKAGE}.cli.ui\n")
    return tree


def _lint(tree: Path) -> subprocess.CompletedProcess[str]:
    lint_imports = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    assert lint_imports is not None, "import-linter is a locked dev dependency"
    return subprocess.run(
        [lint_imports, "--no-cache"],
        cwd=tree,
        env={**os.environ, "PYTHONPATH": str(tree)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_fixture_mirroring_the_real_layout_passes(tmp_path: Path) -> None:
    result = _lint(_fixture(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr


VIOLATIONS = {
    "core imports server directly": {
        f"{PACKAGE}.core.leak": f"import {PACKAGE}.server.hosting\n",
    },
    "core reaches a framework indirectly": {
        f"{PACKAGE}.core.leak": f"import {PACKAGE}.helper\n",
        f"{PACKAGE}.helper": "import fastapi\n",
    },
    "core reaches the CLI indirectly": {
        f"{PACKAGE}.core.leak": f"import {PACKAGE}.helper\n",
        f"{PACKAGE}.helper": f"import {PACKAGE}.cli.app\n",
    },
    "core reaches the prompt adapter indirectly": {
        f"{PACKAGE}.core.leak": f"import {PACKAGE}.helper\n",
        f"{PACKAGE}.helper": f"import {PACKAGE}.cli.prompts\n",
    },
    "server imports the CLI": {
        f"{PACKAGE}.server.leak": f"import {PACKAGE}.cli\n",
    },
    "server reaches a CLI wizard indirectly": {
        f"{PACKAGE}.server.leak": f"import {PACKAGE}.helper\n",
        f"{PACKAGE}.helper": f"import {PACKAGE}.cli.setup\n",
    },
    "an ordinary CLI module imports server startup": {
        f"{PACKAGE}.cli.other": f"import {PACKAGE}.server.hosting\n",
    },
    "the launcher imports beyond server startup": {
        f"{PACKAGE}.cli.ui": f"import {PACKAGE}.server.api\n",
    },
    "a CLI module reaches server indirectly": {
        f"{PACKAGE}.cli.other": f"import {PACKAGE}.helper\n",
        f"{PACKAGE}.helper": f"import {PACKAGE}.server.api\n",
    },
}


@pytest.mark.parametrize("modules", VIOLATIONS.values(), ids=VIOLATIONS.keys())
def test_a_forbidden_import_breaks_a_contract(tmp_path: Path, modules: dict[str, str]) -> None:
    tree = _fixture(tmp_path)
    for module, body in modules.items():
        _write_module(tree, module, body)

    result = _lint(tree)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "BROKEN" in result.stdout
