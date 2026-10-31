"""Install both toolchains in a new worktree: `uv sync`, then `npm install` in src/ui.

T3 runs this on worktree creation (t3.json) by typing the command into a
Windows PowerShell terminal and reading its exit code. It is Python rather
than a shell script because PowerShell cannot run a `.sh` itself: it hands
the file to its Windows file association (Git Bash, in a separate window),
returns at once with success, and never sees the install's output or exit
code, so the agent started before `.venv` and `node_modules` existed. `bash`
by name is no better there; on that PATH it can be WSL's. From cygwin,
`./setup_worktree.sh` runs this same script.

Exits with the first failing step's code.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from frontend_gate import UI, npm_command

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("setup_worktree: uv is not on PATH", file=sys.stderr)
        return 1
    print("== uv sync ==", flush=True)
    code = subprocess.run([uv, "sync"], cwd=ROOT).returncode
    if code:
        return code
    npm = npm_command()
    if npm is None:
        # The agent lint hook and the frontend gate need node_modules.
        print("setup_worktree: npm is not on PATH; src/ui is not installed", file=sys.stderr)
        return 1
    print("== npm install (src/ui) ==", flush=True)
    return subprocess.run([*npm, "install"], cwd=UI).returncode


if __name__ == "__main__":
    sys.exit(main())
