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
HOOK_TIMEOUT_S = 300
"""Only for a hook that hangs. Type-aware ESLint takes about 45s cold on its own,
and `poe test` runs it beside the browser layer on every core, where it passed
120s."""


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
        timeout=HOOK_TIMEOUT_S,
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
    ("config", "tools", "gate"),
    [
        (
            ".claude/settings.json",
            {"Bash", "PowerShell", "Edit", "Write"},
            "scripts/agent_lint_gate.py",
        ),
        (".codex/hooks.json", {"Bash", "apply_patch", "Edit", "Write"}, "agent_lint_gate.py"),
    ],
)
def test_each_agent_gates_edits_and_shell_commands_and_owns_the_daemon(
    config: str, tools: set[str], gate: str
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
    assert set(edit_group["matcher"].split("|")) == tools
    for event, subcommand in [
        ("PostToolUse", "edit"),
        ("SessionStart", "session-start"),
        ("SessionEnd", "session-end"),
    ]:
        for command in commands(event):
            assert gate in command.replace("\\", "/")
            # Codex's Windows form hands PowerShell the program's exit code.
            assert command.removesuffix("; exit $LASTEXITCODE").endswith(f" {subcommand}")
            # Codex runs hooks through PowerShell on Windows, not cmd.
            assert "if exist" not in command


# --- the shell gate (S06) -------------------------------------------------------

GATE = ROOT / "scripts" / "agent_lint_gate.py"

# (command, whether the gate skips it). A skip must be safe, since it delays
# that command's feedback; a lint only costs the snapshot check.
GATE_CASES = [
    ("git status --short", True),
    ("cd src && git diff HEAD~1", True),
    ("grep -rn foo src | head -5", True),
    ("uv run pytest -q 2>&1 | tail -3", True),
    ("gh pr checks 159", True),
    ("bash -lc 'git log --oneline -3'", True),
    ('powershell.exe -Command "Get-ChildItem src"', True),
    ("sed -i 's/a/b/' src/x.py", False),
    ("node fix.js > src/x.py", False),
    ("python scripts/generate_test_assets.py", False),
    ("git checkout main", False),
    ("uv run pytest --update-goldens", False),
    ("npx vitest run -u", False),
    ("find . -name '*.pyc' -delete", False),
    ("echo hi | tee out.txt", False),
    ("uv run ruff format .", False),
    ("bash -lc 'rm -rf build'", False),
    ('powershell.exe -Command "Set-Content x.py a"', False),
    # Redirects: only into a scratch location, never the repository.
    ("cat > /tmp/pr-body.md <<'EOF'\nFixes a -> b\nEOF", True),
    ("gh pr view 1 > /dev/null 2>&1 && echo ok", True),
    ("git diff > $TMP/a.diff", True),
    ("git diff > C:/cygwin64/tmp/a.diff", True),
    ("git diff > C:/Users/Admin/AppData/Local/Temp/a.diff", True),
    ("git diff >> /tmp/a.diff", True),
    ("git diff > a.diff", False),
    ("echo x >src/x.py", False),
    ('echo x > "src/x.py"', False),
    ("git diff > /tmp/../repo/src/x.py", False),
    ("echo x > /tmp/checkout/src/x.py", False),
    ("echo x > /tmp/$name", False),
    ("echo x > /tmp/*", False),
    ("TMP=src; git diff > $TMP/x.py", False),
    ("echo x &> src/x.py", False),
    ("echo x 2> src/err.log", False),
    ('rg -n "a > b" src', True),
    # Heredocs: the body is data; the command reading it must still be read-only.
    ("cat > /tmp/x <<EOF\nhello\nEOF\nrm src/a.py", False),
    ("cat > /tmp/x <<'EOF'\n$(rm src/a.py)\nEOF", True),
    ("cat > /tmp/x <<EOF\n$(rm src/a.py)\nEOF", False),
    ("cat > /tmp/x <<EOF\n`rm src/a.py`\nEOF", False),
    ("cat <<'EOF' > src/x.py\nprint(1)\nEOF", False),
    ("cat > /tmp/x <<'EOF'\nnever closed", False),
    ("python - <<'EOF'\nprint(1)\nEOF", False),
    ("uv run python - <<'EOF'\nprint(1)\nEOF", False),
    (".venv/Scripts/python.exe - <<'EOF'\nprint(1)\nEOF", False),
    ("node - <<'EOF'\nconsole.log(1)\nEOF", False),
    ("gh pr create --title t --body-file - <<'EOF'\nbody > x\nEOF", True),
    # Flags that write only for some tools.
    ("rg -i foo src", True),
    ("grep -i foo src", True),
    ("perl -i -pe 's/a/b/' src/x.py", False),
    ("sort -u names.txt", True),
    ("sort -o names.txt names.txt", False),
    ("npm test -- -u", False),
    ("grep -o 'def [a-z_]*' src/x.py", True),
    ("uv run ruff check --output-format concise src", True),
    ("npx eslint --output-file report.txt src", False),
    ("git diff --output=src/x.py", False),
    ("rg --pre 'rm -rf src' foo", False),
    ("find . -name '*.py' -execdir rm {} +", False),
    ("find . -okdir rm {} +", False),
    # sed and awk only read unless their script writes or runs something.
    ("sed -n '1,80p' src/x.py", True),
    ("sed -n '/^def /p;$p' src/x.py | head", True),
    ("sed -n 's/a/b/w src/y.py' src/x.py", False),
    ("sed -n '1e rm src/x.py' src/x.py", False),
    ("sed 's/a/b/' src/x.py", False),
    ("awk '{print $1}' src/x.py", True),
    ("awk '{print > \"src/y.py\"}' src/x.py", False),
    ("awk 'BEGIN{system(\"rm src/x.py\")}'", False),
    # git: staging, commits and pushes leave the working tree's files as they are.
    ("git add src/x.py && git commit -m 'a > b' && git push", True),
    ("git -c safe.directory=* status", True),
    ("git -c core.symlinks=false -c 'safe.directory=C:/x' log -1", True),
    ("/usr/bin/git -c color.ui=never diff", True),
    ("'C:/Program Files/Git/cmd/git.exe' status", True),
    ("git -c core.pager='rm src/x.py' log", False),
    ("git -c diff.external=./wipe.sh diff", False),
    ("git stash pop", False),
    ("git restore src/x.py", False),
    ("git pull", False),
    ("git merge origin/main", False),
    ("git rebase main", False),
    ("git reset --hard", False),
    ("git clean -fd", False),
    ("git apply fix.patch", False),
    ("git cherry-pick abc", False),
    ("git mv a.py b.py", False),
    ("git switch main", False),
    ("git grep -O'rm -rf src' foo", False),
    ("git grep 'a\nb' -O'rm -rf src' foo", False),
    ("GIT_PAGER='rm src/x.py\n' git log", False),
    # GitHub-only commands; checkout and merge change the tree.
    ("gh pr edit 1 --body-file /tmp/b.md", True),
    ("gh pr comment 1 --body 'ok'", True),
    ("gh pr review 1 --approve", True),
    ("gh workflow run ci.yml && gh workflow list", True),
    ("gh run rerun 123 --failed", True),
    ("gh pr checkout 1", False),
    ("gh pr merge 1 --squash", False),
    ("gh run download 123", False),
    # Environment: assignments, but not the variables that run commands.
    ("unset ETSY_LISTINGS_ROOT && uv run pytest -q", True),
    ("export FOO=bar; git status", True),
    ("PYTHONPATH=src uv run pytest -q", True),
    ("GIT_PAGER='rm src/x.py' git log", False),
    ("export GIT_EXTERNAL_DIFF=./wipe.sh; git diff", False),
    ("env rm src/x.py", False),
    ("env | grep PATH", True),
    # Nested shells are unwrapped, however deep.
    ("C:/cygwin64/bin/zsh.exe -lc 'cd /x && git status'", True),
    ("/c/cygwin64/bin/zsh.exe -l -c 'cd /x && sed -n 1,5p a.py'", True),
    ("C:\\cygwin64\\bin\\zsh.exe -lc 'git log -1'", True),
    ("exec C:/cygwin64/bin/zsh.exe -lc 'git status'", True),
    ("zsh.exe --no-login -c 'git status'", True),
    ("bash -c \"zsh -lc 'git status'\"", True),
    ("C:/cygwin64/bin/zsh.exe -lc 'git status && rm src/x.py'", False),
    ("bash -c \"zsh -lc 'rm src/x.py'\"", False),
    ("zsh -lc 'git status' 'rm src/x.py'", False),
    ("bash -c 'git status'; rm src/x.py", False),
    # Process tools, a build outside the source tree; loops and scripts.
    ("ps -ef | grep vite", True),
    ("ps -W && netstat -ano && tasklist", True),
    ("npm run build", True),
    ("npm run format", False),
    ("npm run gen:api", False),
    ("for f in src/*.py; do echo $f; done", False),
    ("( rm src/x.py )", False),
    ("{ rm src/x.py; }", False),
    # A single & runs the next command too, in every shell.
    ("echo a & python -c \"open('src/x.py','w').write(1)\"", False),
    ("ls & rm src/x.py", False),
    ("echo hi & py -3 -c \"open('prs.txt','w').write('ok')\" & echo done", False),
    ("uv run pytest -q 2>&1 >/dev/null", True),
    ("echo x >&2", True),
    ("echo x &>/dev/null", True),
    # A substitution runs its command, which must be read-only too.
    ("echo $(python -c \"open('src/x.py','w')\")", False),
    ("echo `rm src/x.py`", False),
    ("cat <(rm src/x.py)", False),
    ("diff <(git show HEAD:a.py) >(rm src/x.py)", False),
    ("git status && echo $(git checkout -- src)", False),
    ('echo "$(rm src/x.py)"', False),
    ("git log --oneline -1 $(git merge-base origin/main HEAD)", True),
    ("diff <(git show HEAD:src/a.py) src/a.py", True),
    ("echo '$(rm src/x.py)'", True),
    # Quoting: an escaped quote or separator is not what it looks like.
    ("echo \\'; rm src/x.py; echo \\'", False),
    ("echo 'a; rm src/x.py'", True),
    ('echo "unterminated', False),
    ("echo a # ; rm src/x.py", True),
    ("echo a#; rm src/x.py", False),
    # A Bash payload may be Codex's PowerShell, where a backslash escapes nothing.
    ('echo "a\\"; rm src/x.py; echo "b"', False),
    ('echo "\\$(rm src/x.py)"', False),
    ("rg -n 'a\\|b' src", True),
    ("echo '‘; rm src/x.py; ‘'", False),
    ("curl http://x/a.py –OutFile src/a.py", False),
    ("Sort-Object { rm src/x.py }", False),
    ('echo `"; rm src/x.py; echo `"', False),
    ("echo ${HOME} $HOME", True),
    ('grep -n "a\\|b" src', True),
    # Subshells, and prefixes that run the rest of the segment.
    ("(cd src/ui && npm run build) > /tmp/build.log 2>&1", True),
    ("(cd src/ui && npm run format)", False),
    ("env -u ETSY_LISTINGS_ROOT uv run pytest -q", True),
    ("env -u X rm src/x.py", False),
    ("timeout 60 gh run watch 1", True),
    ("timeout 60 rm src/x.py", False),
    ("export PATH=/usr/local/bin:/usr/bin:$PATH; git status", True),
    ("export PATH=./evil:$PATH; git status", False),
    ("GIT_PAGER=cat GIT_OPTIONAL_LOCKS=0 git log -1", True),
    ("git config core.autocrlf", True),
    ("git config core.pager 'rm src/x.py'", False),
    # curl reads unless it saves what it fetches.
    ('curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8007/', True),
    ("curl -sO http://x/a.py", False),
    ("curl -s http://x/a.py -o src/a.py", False),
    ("curl -s --output-dir src -O http://x/a.py", False),
]

# The same rules, read as PowerShell reads a command: Claude Code's PowerShell tool.
POWERSHELL_GATE_CASES = [
    ("Get-ChildItem src | Select-Object -First 5", True),
    ("Get-Content src/x.py -TotalCount 20", True),
    ("git status; git log -1", True),
    ("& 'C:/cygwin64/bin/zsh.exe' -lc 'cd /x && git status'", True),
    ("git diff 2>$null", True),
    ("Set-Content src/x.py 'a'", False),
    ("Get-Content a.py | Out-File src/x.py", False),
    ("git status > src/x.txt", False),
    ("echo a\\; Remove-Item src/x.py", False),
    ('Write-Output `"; Remove-Item src/x.py', False),
    ("Write-Output $(Remove-Item src/x.py)", False),
    ("& { Remove-Item src/x.py }", False),
    ("& 'C:/cygwin64/bin/zsh.exe' -lc 'rm src/x.py'", False),
    ('powershell -Command "rm src/x.py"', False),
]


def shell_command(command: str, tool: str = "Bash") -> dict[str, object]:
    return {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(ROOT)}


@pytest.mark.parametrize(("command", "read_only"), GATE_CASES)
def test_the_gate_skips_only_commands_that_cannot_write(command: str, *, read_only: bool) -> None:
    sys.path.insert(0, str(GATE.parent))
    try:
        import agent_lint_gate
    finally:
        sys.path.remove(str(GATE.parent))

    assert agent_lint_gate.is_read_only(command) is read_only


@pytest.mark.parametrize(("command", "read_only"), POWERSHELL_GATE_CASES)
def test_the_gate_reads_a_powershell_command_as_powershell_does(
    command: str, *, read_only: bool
) -> None:
    sys.path.insert(0, str(GATE.parent))
    try:
        import agent_lint_gate
    finally:
        sys.path.remove(str(GATE.parent))

    assert agent_lint_gate.is_read_only(command, powershell=True) is read_only


def test_the_gate_reads_the_command_as_text_and_refuses_escapes_it_cannot_decode() -> None:
    sys.path.insert(0, str(GATE.parent))
    try:
        import agent_lint_gate
    finally:
        sys.path.remove(str(GATE.parent))

    quoted = json.dumps(shell_command('grep -n "a b" src'))
    # A JSON encoder may spell `>` as >; a skip there could hide a write.
    escaped = json.dumps(shell_command("echo x > src/y.py"), ensure_ascii=True).replace(
        ">", "\\u003e"
    )

    assert agent_lint_gate.shell_command(quoted) == ('grep -n "a b" src', False)
    assert agent_lint_gate.shell_command(escaped) is None
    assert agent_lint_gate.shell_command(json.dumps(edited(ROOT / "x.py"))) is None


def git_bash() -> str | None:
    """Git's bash on Windows (`bash` on PATH there can be WSL's), else bash."""
    if os.name == "nt":
        candidate = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git/bin/bash.exe"
        return str(candidate) if candidate.is_file() else None
    return shutil.which("bash")


@pytest.mark.skipif(os.name != "nt", reason="Codex's Windows hook command")
def test_codex_windows_command_runs_through_powershell_as_codex_runs_it(
    scratch: Path, state: dict[str, str]
) -> None:
    # Codex runs hooks through the session's shell, always PowerShell on
    # Windows; a cmd-only command (`if exist ... (...)`) fails there silently.
    hooks = json.loads((ROOT / ".codex" / "hooks.json").read_text())["hooks"]
    command = hooks["PostToolUse"][0]["hooks"][0]["commandWindows"]
    source = scratch / "codex.py"
    source.write_text("print(missing)\n")

    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        input=json.dumps(edited(source)),
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, **state},
        timeout=120,
        check=False,
    )

    assert result.returncode == 2, result.stderr
    assert "codex.py:1:" in result.stderr


def test_a_missing_git_skips_the_git_checks_instead_of_crashing(scratch: Path) -> None:
    source = scratch / "no_git.py"
    source.write_text("print(missing)\n")
    # Only the Windows system directory on PATH: no git, as in a sparse hook
    # environment. ruff still runs from the venv by its full path.
    system = os.environ.get("SYSTEMROOT", r"C:\Windows")
    env = {name: value for name, value in os.environ.items() if name.upper() != "PATH"}
    env["PATH"] = str(Path(system) / "System32") if os.name == "nt" else "/nonexistent"

    result = subprocess.run(
        [sys.executable, str(HOOK), "edit"],
        input=json.dumps(edited(source)),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )

    assert "Traceback" not in result.stderr
    assert result.returncode == 2
    assert "F821" in result.stderr


@pytest.mark.skipif(os.name != "nt", reason="the Claude settings command starts the Windows venv")
@pytest.mark.parametrize("agent", ["Claude Code", "Grok"])
def test_the_claude_settings_command_runs_in_each_agents_shell(
    agent: str, scratch: Path, state: dict[str, str]
) -> None:
    # Claude Code runs a hook command through Git Bash; Grok reads the same
    # .claude/settings.json and runs it through PowerShell, with
    # $CLAUDE_PROJECT_DIR a PowerShell variable and the `&` call operator put
    # in front of a command that opens with a quoted program path. A bash-only
    # command fails there, and a failed hook does not block, so Grok would get
    # no lint.
    hooks = json.loads((ROOT / ".claude" / "settings.json").read_text())["hooks"]
    command = hooks["PostToolUse"][0]["hooks"][0]["command"]
    if agent == "Claude Code":
        bash = git_bash()
        if bash is None:
            pytest.skip("no Git Bash")
        argv = [bash, "-c", command]
    else:
        argv = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"$CLAUDE_PROJECT_DIR = '{ROOT}'; & {command}",
        ]
    source = scratch / "launched.py"
    source.write_text("print(missing)\n")

    def launch(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT), **state},
            timeout=120,
            check=False,
        )

    skipped = launch(shell_command("git status"))
    checked = launch(edited(source))

    assert skipped.returncode == 0, skipped.stderr
    assert checked.returncode == 2
    assert "launched.py:1:" in checked.stderr


@pytest.fixture
def state(tmp_path: Path) -> dict[str, str]:
    """A private snapshot and daemon state, already holding the tree as it is."""
    env = {"AGENT_LINT_STATE_DIR": str(tmp_path / "state")}
    seeded = run_mode("snapshot", {}, **env)
    assert seeded.returncode == 0, seeded.stderr
    return env


def run_mode(
    mode: str, payload: dict[str, object], *, script: Path = HOOK, **env: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), mode],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        timeout=120,
        check=False,
    )


def test_a_file_a_shell_command_writes_is_checked_once(
    scratch: Path, state: dict[str, str]
) -> None:
    (scratch / "written.py").write_text("print(missing)\n")

    first = run_mode("edit", shell_command("python make_it.py"), **state)
    second = run_mode("edit", shell_command("python make_it.py"), **state)

    assert first.returncode == 2
    assert "written.py:1:" in first.stderr
    assert "F821" in first.stderr
    assert second.returncode == 0, second.stderr


def test_a_shell_command_after_an_edit_does_not_report_the_edit_again(
    scratch: Path, state: dict[str, str]
) -> None:
    source = scratch / "edited.py"
    source.write_text("print(missing)\n")

    edit = run_mode("edit", edited(source), **state)
    after = run_mode("edit", shell_command("python make_it.py"), **state)

    assert edit.returncode == 2
    assert after.returncode == 0, after.stderr


def test_the_gate_skips_a_read_only_command_and_checks_one_that_writes(
    scratch: Path, state: dict[str, str]
) -> None:
    (scratch / "written.py").write_text("print(missing)\n")

    skipped = run_mode("edit", shell_command("git status"), script=GATE, **state)
    checked = run_mode("edit", shell_command("python make_it.py"), script=GATE, **state)

    assert skipped.returncode == 0, skipped.stderr
    assert checked.returncode == 2
    assert "written.py:1:" in checked.stderr


@pytest.mark.parametrize("tool", ["PowerShell", "run_terminal_command"])
def test_a_powershell_or_grok_shell_command_is_gated_and_checked_as_a_shell_command(
    tool: str, scratch: Path, state: dict[str, str]
) -> None:
    # Claude Code's PowerShell tool and Grok's terminal tool write files no
    # edit reports.
    (scratch / "written.py").write_text("print(missing)\n")

    read = shell_command("Get-ChildItem src | Select-Object -First 3", tool=tool)
    write = shell_command("Set-Content written.py 'print(missing)'", tool=tool)
    skipped = run_mode("edit", read, script=GATE, **state)
    checked = run_mode("edit", write, script=GATE, **state)

    assert skipped.returncode == 0, skipped.stderr
    assert checked.returncode == 2
    assert "written.py:1:" in checked.stderr


# --- the commit backstop (S06) --------------------------------------------------


def test_pre_commit_refuses_findings_without_fixing_anything(scratch: Path) -> None:
    source = scratch / "staged.py"
    original = "import sys\nimport os\n\nprint( missing , os , sys)\n"
    source.write_text(original)

    result = subprocess.run(
        [sys.executable, str(HOOK), "pre-commit", str(source)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 1
    assert "staged.py:4:" in result.stderr
    assert "F821" in result.stderr
    assert "staged.py: not formatted" in result.stderr
    assert source.read_text() == original


def test_the_pre_commit_hook_is_executable_and_runs_the_backstop() -> None:
    listing = subprocess.run(
        ["git", "ls-files", "--stage", ".githooks/pre-commit"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert listing.startswith("100755 ")
    assert 'agent_lint.py" pre-commit' in (ROOT / ".githooks" / "pre-commit").read_text()


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
