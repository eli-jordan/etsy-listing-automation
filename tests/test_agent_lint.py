"""The per-edit agent hook (spec S06, S07), driven through its stdin payload and exit code."""

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "agent_lint.py"


@pytest.fixture
def scratch() -> Iterator[Path]:
    # Inside the repo, so the repo's ruff configuration applies, and outside
    # `src`, so the mypy step stays out of these tests (it needs a warm daemon).
    directory = ROOT / f".agent-lint-scratch-{uuid.uuid4().hex[:8]}"
    directory.mkdir()
    yield directory
    shutil.rmtree(directory)


def run_hook(payload: dict[str, object], **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK), "edit"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        timeout=120,
    )


def edited(path: Path) -> dict[str, object]:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(path)}, "cwd": str(ROOT)}


def test_a_clean_python_file_passes(scratch: Path) -> None:
    source = scratch / "clean.py"
    source.write_text('def greet(name: str) -> str:\n    return f"hello {name}"\n')

    result = run_hook(edited(source))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_a_lint_error_is_reported_back_with_exit_2(scratch: Path) -> None:
    source = scratch / "broken.py"
    source.write_text("def total(values: list[int]) -> int:\n    return sum(valuez)\n")

    result = run_hook(edited(source))

    assert result.returncode == 2
    assert "broken.py:2:" in result.stderr
    assert "F821" in result.stderr


def test_auto_fixable_problems_are_fixed_in_place(scratch: Path) -> None:
    source = scratch / "fixable.py"
    # An unsorted, unused-free import block (I001) and unformatted spacing:
    # ruff's safe fixes and the formatter settle both.
    source.write_text(
        "import sys\nimport os\n\n\ndef where( )->str:\n    return os.sep+sys.prefix\n"
    )

    result = run_hook(edited(source))

    assert result.returncode == 0, result.stderr
    assert source.read_text() == (
        "import os\nimport sys\n\n\ndef where() -> str:\n    return os.sep + sys.prefix\n"
    )


def test_a_file_that_is_not_python_or_typescript_is_ignored(scratch: Path) -> None:
    notes = scratch / "notes.md"
    notes.write_text("def broken(:\n")

    assert run_hook(edited(notes)).returncode == 0


def test_a_file_outside_the_repository_is_ignored(tmp_path: Path) -> None:
    source = tmp_path / "elsewhere.py"
    source.write_text("print(undefined_name)\n")

    result = run_hook(edited(source))

    assert result.returncode == 0, result.stderr


def test_a_new_suppression_without_a_reason_is_rejected(scratch: Path) -> None:
    source = scratch / "suppressed.py"
    source.write_text("import os  # noqa: F401\n")

    result = run_hook(edited(source))

    assert result.returncode == 2
    assert "suppressed.py:1:" in result.stderr
    assert " -- <reason>" in result.stderr


def test_a_suppression_with_a_reason_is_accepted(scratch: Path) -> None:
    source = scratch / "suppressed.py"
    source.write_text(
        "import os  # noqa: F401 -- re-exported for callers\n"
        "\n"
        "\n"
        "def width() -> int:\n"
        '    return "80"  # type: ignore[return-value]  # -- mypy wants the reason apart\n'
    )

    result = run_hook(edited(source))

    assert result.returncode == 0, result.stderr


def test_output_is_capped_at_twenty_findings_with_a_count_of_the_rest(scratch: Path) -> None:
    source = scratch / "noisy.py"
    source.write_text("".join(f"print(undefined_{n})\n" for n in range(30)))

    result = run_hook(edited(source))

    assert result.returncode == 2
    reported = [line for line in result.stderr.splitlines() if "noisy.py:" in line]
    assert len(reported) == 20
    assert "10 more findings omitted" in result.stderr


def test_only_suppressions_the_edit_adds_need_a_reason() -> None:
    # A tracked file that already carries a reasonless `type: ignore` (line
    # 275): committed suppressions belong to the rollout, so only the line
    # this edit appends is reported. The file is restored afterwards.
    tracked = ROOT / "scripts" / "generate_test_assets.py"
    original = tracked.read_bytes()
    lines = original.decode().splitlines()
    try:
        tracked.write_bytes(original + b"UNUSED = 1  # noqa: E501\n")
        result = run_hook(edited(tracked))
    finally:
        tracked.write_bytes(original)

    assert result.returncode == 2
    assert f"generate_test_assets.py:{len(lines) + 1}: suppression" in result.stderr
    assert ":275:" not in result.stderr


def test_a_rewrite_with_windows_line_endings_adds_only_its_new_lines() -> None:
    tracked = ROOT / "scripts" / "generate_test_assets.py"
    original = tracked.read_bytes()
    try:
        tracked.write_bytes((original + b"UNUSED = 1  # noqa: E501\n").replace(b"\n", b"\r\n"))
        result = run_hook(edited(tracked))
    finally:
        tracked.write_bytes(original)

    assert ":275:" not in result.stderr


def test_a_missing_virtualenv_falls_back_to_uv_run_instead_of_skipping(
    scratch: Path, tmp_path: Path
) -> None:
    source = scratch / "broken.py"
    source.write_text("print(valuez)\n")

    result = run_hook(edited(source), AGENT_LINT_VENV=str(tmp_path / "no-venv"))

    assert result.returncode == 2
    assert "F821" in result.stderr


@pytest.fixture
def ui_scratch() -> Iterator[Path]:
    # Under src/ui/src, where the frontend's ESLint and Prettier configs apply.
    directory = ROOT / "src" / "ui" / "src" / f".agent-lint-scratch-{uuid.uuid4().hex[:8]}"
    directory.mkdir()
    yield directory
    shutil.rmtree(directory)


def test_typescript_is_formatted_and_its_eslint_findings_reported(ui_scratch: Path) -> None:
    source = ui_scratch / "widget.ts"
    source.write_text("export function widget(  ) : any {\n  return 1\n}\n")

    result = run_hook(edited(source))

    assert result.returncode == 2
    assert "widget.ts:1:" in result.stderr
    assert "@typescript-eslint/no-explicit-any" in result.stderr
    assert source.read_text() == "export function widget(): any {\n  return 1;\n}\n"


def test_a_codex_patch_has_every_file_it_touches_checked(scratch: Path) -> None:
    first = scratch / "first.py"
    second = scratch / "second.py"
    first.write_text("print(missing_one)\n")
    second.write_text("print(missing_two)\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            f"*** Add File: {scratch.name}/first.py",
            "+print(missing_one)",
            f"*** Update File: {scratch.name}/old_name.py",
            f"*** Move to: {scratch.name}/second.py",
            "@@",
            "-print(1)",
            "+print(missing_two)",
            "*** End Patch",
        ]
    )

    result = run_hook(
        {"tool_name": "apply_patch", "tool_input": {"command": patch}, "cwd": str(ROOT)}
    )

    assert result.returncode == 2
    assert "first.py:1:" in result.stderr
    assert "second.py:1:" in result.stderr


@pytest.mark.parametrize(
    ("config", "edit_tools"),
    [
        (".claude/settings.json", {"Edit", "Write"}),
        (".codex/hooks.json", {"apply_patch", "Edit", "Write"}),
    ],
)
def test_each_agent_runs_the_hook_on_edits_and_owns_the_daemon(
    config: str, edit_tools: set[str]
) -> None:
    hooks = json.loads((ROOT / config).read_text())["hooks"]

    def commands(event: str) -> list[str]:
        return [
            command
            for group in hooks[event]
            for hook in group["hooks"]
            for command in (hook["command"], hook.get("commandWindows", hook["command"]))
        ]

    (edit_group,) = hooks["PostToolUse"]
    assert set(edit_group["matcher"].split("|")) == edit_tools
    for event, subcommand in [
        ("PostToolUse", "edit"),
        ("SessionStart", "session-start"),
        ("SessionEnd", "session-end"),
    ]:
        for command in commands(event):
            assert "scripts/agent_lint.py" in command
            assert command.endswith(f" {subcommand}")


# Stand-ins for `uv` and `npx`, reached through the hook's fallback when the
# venv or node_modules is missing. `uv run dmypy` behaves like a daemon whose
# predecessor died; `uv run ruff` forwards to the real ruff.
FAKE_TOOLS = """\
import json, os, subprocess, sys
from pathlib import Path

tool, args = sys.argv[1], sys.argv[2:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps([tool, args]) + "\\n")
if tool == "uv":
    name, rest = args[2], args[3:]  # uv run --quiet <name> ...
    if name == "ruff":
        sys.exit(subprocess.run([os.environ["REAL_RUFF"], *rest]).returncode)
    status, command = Path(rest[1]), rest[2]  # dmypy --status-file <path> <command>
    alive = status.is_file() and json.loads(status.read_text())["pid"] == 4242
    if command == "status":
        sys.exit(0 if alive else 2)
    if command == "run":
        if status.is_file() and not alive:
            sys.exit(2)  # as real dmypy: a dead daemon's status file blocks a new one
        status.write_text(json.dumps({"pid": 4242, "connection_name": "fake"}))
    sys.exit(0)
if tool == "npx":
    name, rest = args[1], args[2:]  # npx --yes <name> ...
    if name == "eslint":
        message = {"line": 1, "column": 1, "ruleId": "fake/rule", "severity": 2,
                   "message": "from the npx fallback"}
        print(json.dumps([{"filePath": rest[-1], "messages": [message]}]))
"""


@pytest.fixture
def fake_tools(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Env that puts the fakes first on PATH, and the log of their calls."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    script = tmp_path / "fake_tools.py"
    script.write_text(FAKE_TOOLS)
    for tool in ("uv", "npx"):
        if os.name == "nt":
            (bin_dir / f"{tool}.cmd").write_text(
                f'@"{sys.executable}" "{script}" {tool} %*\r\n@exit /b %ERRORLEVEL%\r\n'
            )
        else:
            launcher = bin_dir / tool
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" {tool} "$@"\n')
            launcher.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    real_ruff = Path(sys.executable).parent / ("ruff.exe" if os.name == "nt" else "ruff")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_LOG": str(log),
        "REAL_RUFF": str(real_ruff),
    }
    return env, log


def calls(log: Path) -> list[list[object]]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_a_daemon_that_died_is_replaced_despite_its_stale_status_file(
    fake_tools: tuple[dict[str, str], Path], tmp_path: Path
) -> None:
    env, _ = fake_tools
    state = tmp_path / "state"
    state.mkdir()
    # What a killed daemon leaves: its status file, and the warm marker
    # naming its pid.
    (state / "dmypy.json").write_text(json.dumps({"pid": 999999, "connection_name": "gone"}))
    warm = state / "agent-lint-dmypy.warm"
    warm.write_text("999999")
    source = ROOT / "src" / "etsy_listings" / "__init__.py"

    result = run_hook(
        edited(source),
        **env,
        AGENT_LINT_VENV=str(tmp_path / "no-venv"),
        AGENT_LINT_STATE_DIR=str(state),
    )

    # mypy is skipped, not waited for, while the replacement warms up.
    assert result.returncode == 0, result.stderr
    deadline = time.monotonic() + 60
    while not warm.is_file() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert warm.read_text() == "4242"


def test_missing_node_modules_falls_back_to_npx_instead_of_skipping(
    fake_tools: tuple[dict[str, str], Path], ui_scratch: Path, tmp_path: Path
) -> None:
    env, log = fake_tools
    source = ui_scratch / "widget.ts"
    source.write_text("export const widget = 1;\n")

    result = run_hook(edited(source), **env, AGENT_LINT_NODE_BIN=str(tmp_path / "no-modules"))

    assert result.returncode == 2
    assert "widget.ts:1:1: fake/rule from the npx fallback" in result.stderr
    assert [args[:2] for tool, args in calls(log) if tool == "npx"] == [
        ["--yes", "prettier"],
        ["--yes", "eslint"],
    ]
