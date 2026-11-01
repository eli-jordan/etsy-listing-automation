"""Per-edit lint feedback for coding agents (spec S06).

Claude Code (`.claude/settings.json`, which Grok Build also reads) and Codex
(`.codex/hooks.json`) run this after every edit with the hook payload on
stdin. For each edited source file it applies safe fixes, then reports what is
left on stderr with exit 2, which both agents feed back to the model. Exit 0
means clean, or nothing to check.

Standard library only, so any Python can run it; the tools it calls come from
the project's `.venv` and `src/ui/node_modules`.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_FINDINGS = 20

ESLINT_ERROR = 2  # ESLint's severity for an error; 1 is a warning
COMPLEXIPY_FIELDS = 3  # a `--plain` finding line: path, function, complexity

# S07: a suppression ends with ` -- <reason>`. mypy rejects text after
# `# type: ignore[code]`, so there the reason is a comment of its own:
# `# type: ignore[code]  # -- <reason>`.
SUPPRESSION = re.compile(r"#\s*(noqa\b|type:\s*ignore\b)|\beslint-disable")
REASON = re.compile(r"\s--\s+\S")
# Deleted files and the old name of a moved one are gone; the hook skips paths
# that are not files, so only their surviving names matter.
PATCH_TARGET = re.compile(r"^\*\*\* (?:Add File|Update File|Move to): (.+)$", re.MULTILINE)
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _edited_paths(payload: dict[str, object]) -> list[Path]:
    """Files an edit touched: Claude's and Grok's `file_path`, or every file
    named in a Codex `apply_patch` (its patch text is `tool_input.command`)."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    cwd = Path(str(payload.get("cwd") or Path.cwd()))
    file_path = tool_input.get("file_path")
    if isinstance(file_path, str):
        return [cwd / file_path]
    command = tool_input.get("command")
    if isinstance(command, list):
        command = "\n".join(str(part) for part in command)
    if not isinstance(command, str):
        return []
    return [cwd / name.strip() for name in PATCH_TARGET.findall(command)]


def _inside_repo(path: Path) -> Path | None:
    try:
        return path.resolve().relative_to(ROOT)
    except ValueError:
        return None


PYTHON_SUFFIXES = {".py", ".pyi"}
TYPESCRIPT_SUFFIXES = {".ts", ".tsx"}
UI = ROOT / "src" / "ui"


def _venv_tool(name: str) -> list[str]:
    venv = Path(os.environ.get("AGENT_LINT_VENV", ROOT / ".venv"))
    binary = venv / "Scripts" / f"{name}.exe" if os.name == "nt" else venv / "bin" / name
    # Direct, because `uv run` costs a second per call (S06). Without a
    # synced venv, slower beats skipping the check.
    return [str(binary)] if binary.is_file() else ["uv", "run", "--quiet", name]


def _node_tool(name: str) -> list[str]:
    bin_dir = Path(os.environ.get("AGENT_LINT_NODE_BIN", UI / "node_modules" / ".bin"))
    binary = bin_dir / (f"{name}.cmd" if os.name == "nt" else name)
    if binary.is_file():
        return [str(binary)]
    return [shutil.which("npx") or "npx", "--yes", name]


def _run(command: list[str], *args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*command, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _ruff(*args: str) -> subprocess.CompletedProcess[str]:
    return _run(_venv_tool("ruff"), *args)


def _typescript_findings(relative: Path) -> list[str]:
    target = (ROOT / relative).relative_to(UI).as_posix()
    _run(_node_tool("prettier"), "--write", "--ignore-unknown", "--log-level=warn", target, cwd=UI)
    result = _run(
        _node_tool("eslint"), "--fix", "--no-warn-ignored", "--format=json", target, cwd=UI
    )
    # Errors only: warnings do not fail `npm run lint`, so they do not block here.
    return [
        f"{relative.as_posix()}:{message.get('line', 0)}:{message.get('column', 0)}: "
        f"{message.get('ruleId') or 'eslint'} {message['message']}"
        for report in json.loads(result.stdout or "[]")
        for message in report["messages"]
        if message.get("severity") == ESLINT_ERROR
    ]


def _python_findings(relative: Path) -> list[str]:
    # Fix first, format last: a fix can leave lines the formatter would
    # rewrap, and the report should describe the file as it is left.
    _ruff("check", "--fix", "--force-exclude", "--quiet", str(relative))
    _ruff("format", "--force-exclude", "--quiet", str(relative))
    result = _ruff("check", "--force-exclude", "--output-format=json", str(relative))
    return (
        [
            f"{relative.as_posix()}:{item['location']['row']}:{item['location']['column']}: "
            f"{item['code']} {item['message']}"
            for item in json.loads(result.stdout or "[]")
        ]
        + _complexity_findings(relative)
        + _mypy_findings(relative)
    )


def _cognitive_complexity_limit() -> int:
    """S02's limit, from the `[tool.complexipy]` table `poe complexity` reads."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    limit: int = config["tool"]["complexipy"]["max-complexity-allowed"]
    return limit


def _complexity_findings(relative: Path) -> list[str]:
    limit = _cognitive_complexity_limit()
    result = _run(
        _venv_tool("complexipy"),
        "--max-complexity-allowed",
        str(limit),
        "--failed",
        "--plain",
        "--color=no",
        relative.as_posix(),
    )
    findings = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= COMPLEXIPY_FIELDS and parts[-1].isdigit():
            findings.append(
                f"{relative.as_posix()}: {parts[-2]} has cognitive complexity {parts[-1]} "
                f"(limit {limit}); split it rather than suppress it"
            )
    return findings


# --- mypy through dmypy (S08) ---------------------------------------------
#
# A cold `mypy src` takes about 34s and a warm daemon recheck under a second,
# so the edit hook only ever asks a daemon that has finished its first check.
# Everything lives in the gitignored .mypy_cache, one daemon per worktree.
DMYPY_STATUS = ROOT / ".mypy_cache" / "dmypy.json"
# Holds the pid of the daemon whose first full check has finished.
DMYPY_WARM = ROOT / ".mypy_cache" / "agent-lint-dmypy.warm"
# Present while a warm-up runs, so concurrent edits do not start a second one.
DMYPY_WARMING = ROOT / ".mypy_cache" / "agent-lint-dmypy.warming"
WARMING_STALE_AFTER_S = 300
DMYPY_IDLE_TIMEOUT_S = 1800
DMYPY_CHECK_TIMEOUT_S = 20


def _dmypy(*args: str, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_venv_tool("dmypy"), "--status-file", str(DMYPY_STATUS), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _daemon_pid() -> str | None:
    try:
        return str(json.loads(DMYPY_STATUS.read_text())["pid"])
    except (OSError, ValueError, KeyError):
        return None


def _daemon_alive() -> bool:
    return _daemon_pid() is not None and _dmypy("status").returncode == 0


def _spawn_warm_up() -> None:
    """Start `warm-dmypy` in the background, detached from the hook."""
    try:
        if time.time() - DMYPY_WARMING.stat().st_mtime < WARMING_STALE_AFTER_S:
            return
    except OSError:
        pass
    DMYPY_WARMING.parent.mkdir(exist_ok=True)
    DMYPY_WARMING.touch()
    DMYPY_WARM.unlink(missing_ok=True)
    options: dict[str, object] = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    # No inherited pipes: an agent waits for the hook's stdout to close.
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "warm-dmypy"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **options,  # type: ignore[call-overload]  # -- platform-specific Popen flags
    )


def warm_dmypy() -> int:
    try:
        # A killed daemon leaves its status file behind, and `dmypy run`
        # then gives up instead of starting a new one.
        if not _daemon_alive():
            DMYPY_STATUS.unlink(missing_ok=True)
        _dmypy("run", "--timeout", str(DMYPY_IDLE_TIMEOUT_S), "--", "src")
        pid = _daemon_pid()
        if pid is not None:
            DMYPY_WARM.write_text(pid)
    finally:
        DMYPY_WARMING.unlink(missing_ok=True)
    return 0


def _mypy_findings(relative: Path) -> list[str]:
    # `mypy src` is the gate; tests and scripts are not type-checked.
    if relative.parts[:1] != ("src",):
        return []
    if not _daemon_alive():
        _spawn_warm_up()
        return []
    pid = _daemon_pid()
    try:
        if DMYPY_WARM.read_text().strip() != pid:
            return []  # still on its first check
    except OSError:
        return []
    try:
        result = _dmypy("check", "src", timeout=DMYPY_CHECK_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return []
    # The whole of src is rechecked (rechecking one file would reset the
    # daemon's source set), but only the edited file's findings are reported.
    findings = []
    for line in result.stdout.splitlines():
        path, colon, rest = line.partition(":")
        if colon and path.replace("\\", "/") == relative.as_posix():
            findings.append(f"{relative.as_posix()}:{rest}")
    return findings


def session_start() -> int:
    if not _daemon_alive():
        _spawn_warm_up()
    return 0


def session_end() -> int:
    if _daemon_pid() is not None:
        # Codex gives SessionEnd hooks at most 3s.
        with contextlib.suppress(subprocess.TimeoutExpired):
            _dmypy("stop", timeout=3)
    DMYPY_WARM.unlink(missing_ok=True)
    return 0


def _added_lines(relative: Path) -> list[tuple[int, str]]:
    """Lines this working tree adds to the file, relative to HEAD.

    Only new suppressions must carry a reason; the ones already committed are
    the rollout's business, not the agent's.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative.as_posix()],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    text = (ROOT / relative).read_text(encoding="utf-8", errors="replace")
    if tracked.returncode != 0:
        return list(enumerate(text.splitlines(), start=1))
    diff = subprocess.run(
        # An editor that rewrites the file with CRLF endings has not added
        # every line in it.
        [
            "git",
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--ignore-cr-at-eol",
            "-U0",
            "HEAD",
            "--",
            relative.as_posix(),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    ).stdout
    added: list[tuple[int, str]] = []
    number = 0
    for line in diff.splitlines():
        hunk = HUNK.match(line)
        if hunk:
            number = int(hunk.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            added.append((number, line[1:]))
            number += 1
    return added


def _unexplained_suppressions(relative: Path) -> list[str]:
    findings = []
    for number, line in _added_lines(relative):
        match = SUPPRESSION.search(line)
        if match and not REASON.search(line, match.end()):
            findings.append(
                f"{relative.as_posix()}:{number}: suppression without a reason; "
                "end it with ` -- <reason>` (for `type: ignore`, add `  # -- <reason>`), "
                "or fix the finding instead (AGENTS.md, spec S07)"
            )
    return findings


def _report(findings: list[str]) -> None:
    shown = findings[:MAX_FINDINGS]
    omitted = len(findings) - len(shown)
    if omitted:
        shown.append(f"... {omitted} more findings omitted")
    print("\n".join(shown), file=sys.stderr)


def edit(payload: dict[str, object]) -> int:
    findings: list[str] = []
    for path in _edited_paths(payload):
        relative = _inside_repo(path)
        if relative is None or not path.is_file():
            continue
        if path.suffix in PYTHON_SUFFIXES:
            findings += _python_findings(relative)
        elif path.suffix in TYPESCRIPT_SUFFIXES and (ROOT / relative).is_relative_to(UI):
            findings += _typescript_findings(relative)
        else:
            continue
        findings += _unexplained_suppressions(relative)
    if not findings:
        return 0
    _report(findings)
    return 2


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "edit"
    if command == "warm-dmypy":
        return warm_dmypy()
    # Hooks always send a payload; only the edit hook needs it.
    payload = json.loads(sys.stdin.read() or "{}")
    if command == "session-start":
        return session_start()
    if command == "session-end":
        return session_end()
    return edit(payload)


if __name__ == "__main__":
    sys.exit(main())
