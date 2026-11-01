"""Run npm scripts in src/ui in order, for `poe frontend` (spec S09).

    python scripts/frontend_gate.py format lint typecheck test:coverage test:design

Stops at the first failing script with its exit code. When npm is not on PATH
it prints that the frontend checks were skipped and exits 0: a Python-only
contributor's `poe check` should not fail for a toolchain they do not use,
the same self-skip the browser pytest layer makes for a missing chromium.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "src" / "ui"


def npm_command() -> list[str] | None:
    """How to run npm from this Python, or None when npm is not on PATH.

    On Windows, Node's bundled npm CLI rather than a launcher: cygwin's is a
    shell script Windows Python cannot run, and npm.cmd brings cmd.exe
    quoting (the same choice as hatch_build.py).
    """
    npm = shutil.which("npm")
    if npm is None:
        return None
    if sys.platform == "win32":
        node = shutil.which("node")
        cli = Path(npm).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if node is not None and cli.is_file():
            return [node, str(cli)]
    return [npm]


def main(scripts: list[str]) -> int:
    npm = npm_command()
    if npm is None:
        print("== frontend checks skipped: npm not on PATH ==")
        return 0
    for script in scripts:
        print(f"== frontend: npm run {script} ==", flush=True)
        code = subprocess.run([*npm, "run", script], cwd=UI, check=False).returncode
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
