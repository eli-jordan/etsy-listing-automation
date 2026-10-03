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


def _npm_scripts(command: str) -> list[str]:
    words = shlex.split(command.replace("&&", " && ").replace("(", " ").replace(")", " "))
    return [
        words[i + 2] for i, word in enumerate(words[:-2]) if word == "npm" and words[i + 1] == "run"
    ]


def test_frontend_gate_runs_production_and_prototype_tests_in_ci_and_check_sh() -> None:
    # CI mirrors check.sh rather than calling it, so the frontend test scripts
    # each one runs are compared here: dropping the required prototype command
    # from either side, or folding it into coverage, fails.
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    ci = [
        script
        for step in workflow["jobs"]["frontend"]["steps"]
        for script in _npm_scripts(step.get("run", ""))
        if script.startswith("test")
    ]
    check = [
        script
        for line in (root / "scripts/check.sh").read_text().splitlines()
        if not line.lstrip().startswith("#")
        for script in _npm_scripts(line)
        if script.startswith("test")
    ]
    assert ci == check == ["test:coverage", "test:design"]
