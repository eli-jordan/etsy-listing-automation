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


# The five screenshot scenes are review artifacts, not regression tests (T11):
# they only assert that a PNG was written. They run when asked for by marker.
CAPTURE_SCENES = {
    "test_capture_full_page_screenshot",
    "test_capture_preview_all_screenshot",
    "test_capture_lightbox_screenshot",
    "test_capture_multiple_editor_screenshot",
    "test_capture_workbench_screenshot",
}


def _collected(root: Path, tmp_path: Path, *selection: str) -> set[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *selection]
        + ["-o", f"cache_dir={tmp_path / 'cache'}", "tests/browser"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.replace("\\", "/") for line in result.stdout.splitlines() if "::" in line}


def _names(ids: set[str]) -> set[str]:
    return {node.rsplit("::", 1)[-1] for node in ids}


def test_required_browser_selection_excludes_only_the_opt_in_captures(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    command = next(
        step["run"]
        for step in workflow["jobs"]["browser"]["steps"]
        if step.get("run", "").startswith("uv run pytest")
    )
    args = shlex.split(command)
    required = _collected(root, tmp_path, *args[args.index("-m") :])
    # check.sh runs the default selection, which must agree.
    default = _collected(root, tmp_path)
    everything = _collected(root, tmp_path, "-m", "browser or capture")
    assert required == default
    assert not _names(required) & CAPTURE_SCENES
    # Real witnesses -- decoded PNGs, saved YAML, geometry -- stay required.
    assert "test_the_preview_sits_on_the_surface_tone" in _names(required)
    assert everything - required == {n for n in everything if _names({n}) <= CAPTURE_SCENES}


def test_the_capture_marker_selects_exactly_the_five_scenes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    assert _names(_collected(root, tmp_path, "-m", "capture")) == CAPTURE_SCENES
