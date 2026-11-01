"""`poe frontend` skips, rather than fails, without npm (spec S09)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_the_frontend_gate_is_skipped_when_npm_is_not_on_path(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "frontend_gate.py"), "lint"],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": str(tmp_path)},
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "frontend checks skipped: npm not on PATH" in result.stdout


@pytest.mark.skipif(shutil.which("npm") is None, reason="needs npm on PATH")
def test_a_failing_npm_script_fails_the_gate_with_its_exit_code() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "frontend_gate.py"), "no-such-script"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode != 0
