"""The ordinary CI gate must never select real-service tests."""

import shlex
import subprocess
import sys
from pathlib import Path

import yaml


def test_python_ci_collects_only_hermetic_layers(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    command = next(
        step["run"]
        for step in workflow["jobs"]["python"]["steps"]
        if step.get("run", "").startswith("uv run pytest")
    )
    args = shlex.split(command)
    selection = args[args.index("-m") + 1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-m",
            selection,
            "-o",
            f"cache_dir={tmp_path / 'cache'}",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    selected = result.stdout.replace("\\", "/")
    for owner in ("core", "server", "cli"):
        assert f"tests/{owner}/behaviour/" in selected
    assert "tests/e2e/" not in selected
    assert "tests/browser/" not in selected
