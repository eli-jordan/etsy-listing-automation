"""The ordinary CI gate must never select real-service tests."""

import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _poe_command(task: str) -> str:
    """The command line a poe task in pyproject.toml runs (S09)."""
    tasks = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["poe"]["tasks"]
    definition = tasks[task]
    return definition if isinstance(definition, str) else definition["cmd"]


def _ci_poe_command(job: str, prefix: str) -> str:
    """The command behind the poe task a CI job runs, where its name starts with prefix.

    CI calls poe tasks rather than listing commands (S10), so a selection is
    read from the task the workflow names.
    """
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    task = next(
        step["run"].split()[3]
        for step in workflow["jobs"][job]["steps"]
        if step.get("run", "").startswith(f"uv run poe {prefix}")
    )
    return _poe_command(task)


def test_python_ci_collects_only_hermetic_layers(tmp_path: Path) -> None:
    root = ROOT
    command = _ci_poe_command("python", "test")
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


def test_both_python_legs_select_the_same_tests_and_only_ubuntu_measures_coverage() -> None:
    # Windows runs `test-ci` without coverage, for speed; it must not also
    # drift onto a different selection.
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    legs = {
        step["if"]: shlex.split(_poe_command(step["run"].split()[3]))
        for step in workflow["jobs"]["python"]["steps"]
        if step.get("run", "").startswith("uv run poe test")
    }
    linux, windows = legs["runner.os == 'Linux'"], legs["runner.os == 'Windows'"]
    assert "--cov" in linux
    assert [arg for arg in linux if not arg.startswith("--cov")] == windows


def test_the_windows_shards_together_run_the_whole_selection() -> None:
    # `--shard i/N` runs one Nth; a matrix missing a shard, or a count that
    # disagrees with it, would silently skip tests.
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["python"]
    run = next(
        step["run"]
        for step in job["steps"]
        if step.get("if") == "runner.os == 'Windows'" and "poe test" in step.get("run", "")
    )
    count = int(run.split("--shard ")[1].split("/")[1])
    shards = sorted(
        leg["shard"]
        for leg in job["strategy"]["matrix"]["include"]
        if leg["os"] == "windows-latest"
    )
    assert shards == list(range(1, count + 1))
    # The ruleset's required check keeps its name through the gate job.
    assert workflow["jobs"]["windows"]["name"] == "python (windows-latest)"
    assert workflow["jobs"]["windows"]["needs"] == ["python"]


def _npm_scripts(command: str) -> list[str]:
    words = shlex.split(command.replace("&&", " && ").replace("(", " ").replace(")", " "))
    return [
        words[i + 2] for i, word in enumerate(words[:-2]) if word == "npm" and words[i + 1] == "run"
    ]


def test_frontend_gate_runs_production_and_prototype_tests_in_ci_and_poe_check() -> None:
    # The frontend CI job runs npm directly (it has no Python), so the test
    # scripts it runs are compared with those `poe check` runs: dropping the
    # required prototype command from either side, or folding it into
    # coverage, fails.
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    ci = [
        script
        for step in workflow["jobs"]["frontend"]["steps"]
        for script in _npm_scripts(step.get("run", ""))
        if script.startswith("test")
    ]
    gate = shlex.split(_poe_command("frontend"))
    check = [
        script
        for script in gate[gate.index("scripts/frontend_gate.py") + 1 :]
        if script.startswith("test")
    ]
    assert ci == check == ["test:coverage", "test:design"]


# The six screenshot scenes are review artifacts, not regression tests (T11):
# they only assert that a PNG was written. They run when asked for by marker.
CAPTURE_SCENES = {
    "test_capture_full_page_screenshot",
    "test_capture_preview_all_screenshot",
    "test_capture_lightbox_screenshot",
    "test_capture_multiple_editor_screenshot",
    "test_capture_workbench_screenshot",
    "test_capture_approved_marigold_states",
}
# The Admin journeys run once, in light; their dark pass only feeds review
# screenshots, so the `theme` fixture puts it under `capture` too.
DARK = "[dark]"


def _is_capture(name: str) -> bool:
    return name in CAPTURE_SCENES or name.endswith(DARK)


def _collected(root: Path, tmp_path: Path, *selection: str) -> set[str]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            *selection,
            "-o",
            f"cache_dir={tmp_path / 'cache'}",
            "tests/browser",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.replace("\\", "/") for line in result.stdout.splitlines() if "::" in line}


def _names(ids: set[str]) -> set[str]:
    return {node.rsplit("::", 1)[-1] for node in ids}


def test_required_browser_selection_excludes_only_the_opt_in_captures(tmp_path: Path) -> None:
    root = ROOT
    args = shlex.split(_ci_poe_command("browser", "test"))
    required = _collected(root, tmp_path, *args[args.index("-m") :])
    # `poe check` runs the default selection, which must agree.
    check = shlex.split(_poe_command("test"))
    assert "-m" not in check
    default = _collected(root, tmp_path)
    everything = _collected(root, tmp_path, "-m", "browser or capture")
    assert required == default
    assert not any(_is_capture(name) for name in _names(required))
    # Real witnesses -- decoded PNGs, saved YAML, geometry -- stay required.
    assert "test_the_preview_sits_on_the_surface_tone" in _names(required)
    assert "test_the_marigold_toolbar_fits_its_bar_at_desktop_widths" in _names(required)
    assert everything - required == {n for n in everything if _is_capture(_names({n}).pop())}


def test_the_capture_marker_selects_the_six_scenes_and_each_journey_s_dark_pass(
    tmp_path: Path,
) -> None:
    root = ROOT
    captured = _names(_collected(root, tmp_path, "-m", "capture"))
    assert captured - {n for n in captured if n.endswith(DARK)} == CAPTURE_SCENES
    light = {n for n in _names(_collected(root, tmp_path)) if n.endswith("[light]")}
    assert light
    assert {n.replace(DARK, "[light]") for n in captured if n.endswith(DARK)} == light


def test_lint_runs_once_in_the_quality_job_and_the_test_matrix_only_tests() -> None:
    # S02/S04/S05/S10: complexity and whole-program checks run once alongside lint on ubuntu,
    # through the same poe task a developer can run; the two-OS matrix exists
    # for the render goldens and runs tests alone.
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    quality = [step.get("run", "") for step in workflow["jobs"]["quality"]["steps"]]
    assert "uv run poe lint" in quality
    tasks = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["poe"]["tasks"]
    lint = [_poe_command(name) for name in tasks["lint"]]
    assert lint == [
        "ruff format --check .",
        "ruff check .",
        "mypy src",
        "lint-imports",
        "complexipy --failed --plain",
        "vulture src/etsy_listings --min-confidence 90",
        "node src/ui/node_modules/jscpd/bin/jscpd "
        "src/etsy_listings src/ui/src --config .jscpd.json",
    ]
    assert "lint" in tasks["check"]
    assert "npm ci" in quality
    node = next(
        step
        for step in workflow["jobs"]["quality"]["steps"]
        if step.get("uses", "").startswith("actions/setup-node@")
    )
    assert node["with"]["cache-dependency-path"] == "src/ui/package-lock.json"
    python = [step.get("run", "") for step in workflow["jobs"]["python"]["steps"]]
    assert not [run for run in python if any(tool in run for tool in ("ruff", "mypy", "lint"))]
