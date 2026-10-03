"""Every server module imports on its own, whatever is imported first.

The server package initializers re-export nothing (one import path per
interface, ADR-0052), so no initializer pre-loads the app in an order that
happens to dodge a cycle. The worker modules still import
``server.api.schemas`` until PR 9 separates their events from wire schemas;
importing one of them first must still work.
"""

from __future__ import annotations

import json
import subprocess
import sys

_PROBE = """
import importlib, json, pkgutil, sys
import etsy_listings.server as server

prefix = "etsy_listings.server."
names = [info.name for info in pkgutil.walk_packages(server.__path__, prefix=prefix)]
failures = {}
for name in names:
    for loaded in [m for m in sys.modules if m.startswith(prefix)]:
        del sys.modules[loaded]
    try:
        importlib.import_module(name)
    except Exception as exc:
        failures[name] = f"{type(exc).__name__}: {exc}"
print(json.dumps({"checked": len(names), "failures": failures}))
"""


def test_each_server_module_imports_first() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["checked"] > 20
    assert report["failures"] == {}
