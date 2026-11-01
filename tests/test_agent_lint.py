"""The per-edit agent hook (spec S06, S07), driven through its stdin payload and exit code."""

import json
import os
import shutil
import subprocess
import sys
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
        check=False,
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


# Five nested branches: cognitive complexity 1+2+3+4+5 = 15, over S02's 10,
# while its cyclomatic complexity (6) stays under ruff's C901 limit of 8, so
# only the complexipy step can report it.
NESTED = """def deep(rows: list[list[int]]) -> int:
    total = 0
    for row in rows:
        for value in row:
            if value > 0:
                bits = value
                while bits:
                    if bits & 1:
                        total += 1
                    bits >>= 1
    return total
"""


def test_a_function_over_the_cognitive_complexity_limit_is_reported(scratch: Path) -> None:
    source = scratch / "nested.py"
    source.write_text(NESTED)

    result = run_hook(edited(source))

    assert result.returncode == 2, result.stderr
    assert "deep has cognitive complexity 15 (limit 10)" in result.stderr
    assert "C901" not in result.stderr


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
    # One undefined name per line. A `print` would also be T201 now that S01
    # enables T20, and the omitted count would no longer be the line count.
    source.write_text(
        "def keep(value: object) -> object:\n"
        "    return value\n"
        "\n" + "".join(f"keep(undefined_{n})\n" for n in range(30))
    )

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
    # A module assignment is not F841, and a short E501 suppression is unused:
    # RUF100's safe fix removes it before the reason check. A local binding
    # still needs the suppression. The marker is split so this file's own
    # added lines are not suppressions.
    marker = b"def unused_binding() -> None:\n    local = 1  # " + b"noqa: F841\n"
    body = original if original.endswith(b"\n") else original + b"\n"
    try:
        tracked.write_bytes(body + marker)
        result = run_hook(edited(tracked))
    finally:
        tracked.write_bytes(original)

    assert result.returncode == 2
    # Format inserts the two blank lines a new top-level function needs,
    # so the silenced binding lands four lines past the old end.
    assert f"generate_test_assets.py:{len(lines) + 4}: suppression" in result.stderr
    assert ":275:" not in result.stderr


def test_a_rewrite_with_windows_line_endings_adds_only_its_new_lines() -> None:
    tracked = ROOT / "scripts" / "generate_test_assets.py"
    original = tracked.read_bytes()
    try:
        marker = b"def unused_binding() -> None:\n    local = 1  # " + b"noqa: F841\n"
        # A core.autocrlf checkout is already CRLF. Replacing `\n` there
        # writes `\r\r\n`, and ruff format collapses that to bare CR, which
        # `git diff --ignore-cr-at-eol` does not report as added lines.
        normalized = original.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        body = normalized if normalized.endswith(b"\n") else normalized + b"\n"
        tracked.write_bytes((body + marker).replace(b"\n", b"\r\n"))
        result = run_hook(edited(tracked))
    finally:
        tracked.write_bytes(original)

    assert result.returncode == 2
    assert ":275:" not in result.stderr
    assert "suppression without a reason" in result.stderr


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
