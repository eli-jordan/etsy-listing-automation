"""New worktrees get both toolchains, and a failed install is reported."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts" / "setup_worktree.py"

FAKE = """\
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps([sys.argv[1], sys.argv[2:], os.getcwd()]) + "\\n")
sys.exit(int(os.environ.get("FAKE_EXIT_" + sys.argv[1], "0")))
"""


@pytest.fixture
def fake_tools(tmp_path: Path) -> Path:
    """A PATH holding only recording stand-ins for uv and npm."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = tmp_path / "fake.py"
    fake.write_text(FAKE)
    for tool in ("uv", "npm"):
        if os.name == "nt":
            (bin_dir / f"{tool}.cmd").write_text(
                f'@"{sys.executable}" "{fake}" {tool} %*\r\n@exit /b %ERRORLEVEL%\r\n'
            )
        else:
            launcher = bin_dir / tool
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" {tool} "$@"\n')
            launcher.chmod(0o755)
    return bin_dir


def run_setup(bin_dir: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], list]:
    log = bin_dir.parent / "calls.jsonl"
    result = subprocess.run(
        [sys.executable, str(SETUP)],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": str(bin_dir), "FAKE_LOG": str(log), **env},
        timeout=60,
        check=False,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


def test_it_syncs_python_then_installs_the_frontend(fake_tools: Path) -> None:
    result, calls = run_setup(fake_tools)

    assert result.returncode == 0, result.stdout + result.stderr
    assert [(tool, args, Path(cwd)) for tool, args, cwd in calls] == [
        ("uv", ["sync"], ROOT),
        ("npm", ["install"], ROOT / "src" / "ui"),
    ]


def test_a_failed_sync_fails_setup_before_the_frontend(fake_tools: Path) -> None:
    result, calls = run_setup(fake_tools, FAKE_EXIT_uv="3")

    assert result.returncode == 3
    assert [tool for tool, _, _ in calls] == ["uv"]


def test_a_failed_npm_install_fails_setup(fake_tools: Path) -> None:
    result, _ = run_setup(fake_tools, FAKE_EXIT_npm="1")

    assert result.returncode == 1
