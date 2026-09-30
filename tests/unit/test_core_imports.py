"""Core imports stay transport-independent (spec, "Responsibility and dependency rules").

Each ``etsy_listings.core`` package, with every submodule it contains, is
imported in a fresh interpreter, which then reports which forbidden modules
ended up in ``sys.modules``. A fresh process is the point: in this test run
FastAPI and Typer are already loaded by other tests, so an in-process check
could not see an eager import.

Import Linter (added later in the stack) enforces the same rules statically;
this proves the runtime effect, including imports made at module load.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

CORE_MODULES = [
    "etsy_listings.core",
    "etsy_listings.core.ai",
    "etsy_listings.core.batches",
    "etsy_listings.core.clients",
    "etsy_listings.core.config",
    "etsy_listings.core.connections",
    "etsy_listings.core.engine",
    "etsy_listings.core.errors",
    "etsy_listings.core.listing_templates",
    "etsy_listings.core.market",
    "etsy_listings.core.render",
    "etsy_listings.core.workspace",
]

FORBIDDEN = [
    "fastapi",
    "starlette",
    "uvicorn",
    "typer",
    "questionary",
    "etsy_listings.server",
    "etsy_listings.cli",
    "etsy_listings.newcmd",
    "etsy_listings.setupcmd",
    "etsy_listings.authcmd",
    "etsy_listings.credentials",
    "etsy_listings.prompts",
    "etsy_listings.terminal",
]

_PROBE = """
import importlib, json, pkgutil, sys

name, forbidden = sys.argv[1], json.loads(sys.argv[2])
module = importlib.import_module(name)
if name != "etsy_listings.core" and hasattr(module, "__path__"):
    for info in pkgutil.walk_packages(module.__path__, prefix=name + "."):
        importlib.import_module(info.name)
loaded = sorted(
    m for m in sys.modules if any(m == f or m.startswith(f + ".") for f in forbidden)
)
print(json.dumps(loaded))
"""


@pytest.mark.parametrize("module", CORE_MODULES)
def test_core_module_imports_no_adapter_or_framework(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, module, json.dumps(FORBIDDEN)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []


def test_core_initializer_is_lightweight() -> None:
    """Importing ``etsy_listings.core`` alone must not load its subpackages."""
    probe = (
        "import sys, etsy_listings.core; "
        "print(sorted(m for m in sys.modules if m.startswith('etsy_listings.core.')))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
