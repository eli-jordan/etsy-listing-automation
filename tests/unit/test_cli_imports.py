"""Ordinary CLI imports do not load the HTTP server (ADR-0052; module-structure
spec, "Responsibility and dependency rules").

Only the dedicated ``ui`` launcher may reach server startup, and only while
the command runs: registering commands -- which is all importing the CLI
does -- must not load FastAPI or ``etsy_listings.server``. A fresh
interpreter is the point, as in ``test_core_imports``: this test run has
already imported both.

Import Linter checks the static graph; this proves the runtime effect of
package initializers and module-level imports.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

SERVER_SIDE = ["fastapi", "starlette", "uvicorn", "etsy_listings.server"]

_PROBE = """
import importlib, json, sys

name, forbidden = sys.argv[1], json.loads(sys.argv[2])
importlib.import_module(name)
print(json.dumps(sorted(
    m for m in sys.modules if any(m == f or m.startswith(f + ".") for f in forbidden)
)))
"""


@pytest.mark.parametrize(
    "module", ["etsy_listings.cli", "etsy_listings.cli.app", "etsy_listings.cli.ui"]
)
def test_cli_import_loads_no_server(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, module, json.dumps(SERVER_SIDE)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []


def test_ui_command_is_registered_from_the_dedicated_launcher() -> None:
    from etsy_listings.cli.app import app

    [ui] = [
        command
        for command in app.registered_commands
        if (command.name or getattr(command.callback, "__name__", None)) == "ui"
    ]
    assert ui.callback is not None
    assert ui.callback.__module__ == "etsy_listings.cli.ui"


def test_no_python_ui_package_remains() -> None:
    old = importlib.util.find_spec("etsy_listings.ui")
    # A checkout that was on an older commit can keep an untracked
    # `ui/__pycache__` directory, which imports as an empty namespace
    # package; what must not remain is a module with source behind it.
    assert old is None or old.origin is None
    assert importlib.util.find_spec("etsy_listings.server.hosting") is not None
