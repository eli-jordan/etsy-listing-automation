"""Lint feedback for coding agents (spec S06).

Claude Code and Grok (`.claude/settings.json`) and Codex (`.codex/hooks.json`)
run this after every edit and every shell command, with the hook payload on
stdin, behind a gate that ends the hook at once after a shell command that
cannot have written a file (scripts/agent_lint_gate.py, which Claude Code and
Grok start through scripts/agent_lint_launch.sh). For each changed source file it
applies safe fixes, then reports what is left on stderr with exit 2, which
every agent feeds back to the model. Exit 0 means clean, or nothing to check.

An edit names its files. A shell command does not, so the hook compares the
working tree's dirty source files with a snapshot of their contents taken at
the last check: whatever wrote them (sed, a script, a formatter), each changed
file is checked once. `.githooks/pre-commit` runs the same checks, without
fixing anything, on what is staged.

Standard library only, so any Python can run it, and the gates start it with
`-S`; the tools it calls come from the project's `.venv` and
`src/ui/node_modules`.
"""

from __future__ import annotations

import contextlib  # free: subprocess imports it anyway
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Modules only the checks need are imported where they are used: after most
# shell commands nothing changed, and those imports would cost 50ms on each.

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get("AGENT_LINT_STATE_DIR", ROOT / ".mypy_cache"))
MAX_FINDINGS = 20

ESLINT_ERROR = 2  # ESLint's severity for an error; 1 is a warning
COMPLEXIPY_FIELDS = 3  # a `--plain` finding line: path, function, complexity
FINDINGS = 2  # the exit code every agent feeds back to the model
REFUSED = 1  # the exit code that stops a commit

# S07: a suppression ends with ` -- <reason>`. mypy rejects text after
# `# type: ignore[code]`, so there the reason is a comment of its own:
# `# type: ignore[code]  # -- <reason>`.
SUPPRESSION = re.compile(r"#\s*(noqa\b|type:\s*ignore\b)|\beslint-disable")
REASON = re.compile(r"\s--\s+\S")
# Deleted files and the old name of a moved one are gone; the hook skips paths
# that are not files, so only their surviving names matter.
PATCH_TARGET = re.compile(r"^\*\*\* (?:Add File|Update File|Move to): (.+)$", re.MULTILINE)
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

PYTHON_SUFFIXES = {".py", ".pyi"}
TYPESCRIPT_SUFFIXES = {".ts", ".tsx"}
SOURCE_SUFFIXES = PYTHON_SUFFIXES | TYPESCRIPT_SUFFIXES
UI = ROOT / "src" / "ui"


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


def _lintable(paths: list[Path]) -> tuple[list[Path], list[Path]]:
    """The repository's Python and frontend TypeScript files among `paths`."""
    python: list[Path] = []
    typescript: list[Path] = []
    for path in paths:
        relative = _inside_repo(path)
        if relative is None or not path.is_file():
            continue
        if path.suffix in PYTHON_SUFFIXES:
            python.append(relative)
        elif path.suffix in TYPESCRIPT_SUFFIXES and (ROOT / relative).is_relative_to(UI):
            typescript.append(relative)
    return python, typescript


def _venv_tool(name: str) -> list[str]:
    venv = Path(os.environ.get("AGENT_LINT_VENV", ROOT / ".venv"))
    binary = venv / "Scripts" / f"{name}.exe" if os.name == "nt" else venv / "bin" / name
    # Direct, because `uv run` costs a second per call (S06). Without a
    # synced venv, slower beats skipping the check.
    if binary.is_file():
        return [str(binary)]
    import shutil  # noqa: PLC0415 -- only the fallbacks need it (see the imports)

    # `which`, because on Windows a bare "uv" finds only uv.exe on PATH.
    return [shutil.which("uv") or "uv", "run", "--quiet", name]


def _node_tool(name: str) -> list[str]:
    bin_dir = Path(os.environ.get("AGENT_LINT_NODE_BIN", UI / "node_modules" / ".bin"))
    binary = bin_dir / (f"{name}.cmd" if os.name == "nt" else name)
    if binary.is_file():
        return [str(binary)]
    import shutil  # noqa: PLC0415 -- only the npx fallback needs it (see the imports)

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


def _git(*args: str) -> str:
    return _run(["git"], *args).stdout


def _relative_name(reported: str) -> str:
    """A tool's report of a file, as a repo-relative posix path."""
    path = Path(reported.removeprefix("//?/"))
    relative = _inside_repo(path if path.is_absolute() else ROOT / path)
    return relative.as_posix() if relative else reported


# --- TypeScript -------------------------------------------------------------


def _typescript_findings(relative: Path, *, fix: bool) -> list[str]:
    target = (ROOT / relative).relative_to(UI).as_posix()
    findings = []
    prettier = "--write" if fix else "--check"
    formatted = _run(
        _node_tool("prettier"), prettier, "--ignore-unknown", "--log-level=warn", target, cwd=UI
    )
    if not fix and formatted.returncode:
        findings.append(f"{relative.as_posix()}: not formatted; run prettier --write")
    eslint_fix = ["--fix"] if fix else []
    result = _run(
        _node_tool("eslint"), *eslint_fix, "--no-warn-ignored", "--format=json", target, cwd=UI
    )
    # Errors only: warnings do not fail `npm run lint`, so they do not block here.
    return findings + [
        f"{relative.as_posix()}:{message.get('line', 0)}:{message.get('column', 0)}: "
        f"{message.get('ruleId') or 'eslint'} {message['message']}"
        for report in json.loads(result.stdout or "[]")
        for message in report["messages"]
        if message.get("severity") == ESLINT_ERROR
    ]


# --- Python -------------------------------------------------------------------


def _ruff(*args: str) -> subprocess.CompletedProcess[str]:
    return _run(_venv_tool("ruff"), *args)


def _fix_python(relative: Path) -> None:
    # Fix first, format last: a fix can leave lines the formatter would
    # rewrap, and the report should describe the file as it is left.
    _ruff("check", "--fix", "--force-exclude", "--quiet", str(relative))
    _ruff("format", "--force-exclude", "--quiet", str(relative))


def _ruff_findings(relatives: list[Path]) -> list[str]:
    result = _ruff("check", "--force-exclude", "--output-format=json", *map(str, relatives))
    return [
        f"{_relative_name(item['filename'])}:{item['location']['row']}:"
        f"{item['location']['column']}: {item['code']} {item['message']}"
        for item in json.loads(result.stdout or "[]")
    ]


def _unformatted(relatives: list[Path]) -> list[str]:
    return [
        f"{relative.as_posix()}: not formatted; run ruff format"
        for relative in relatives
        if _ruff("format", "--check", "--force-exclude", "--quiet", str(relative)).returncode
    ]


def _cognitive_complexity_limit() -> int:
    """S02's limit, from the `[tool.complexipy]` table `poe complexity` reads."""
    import tomllib  # noqa: PLC0415 -- only the complexity check needs it (see the imports)

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    limit: int = config["tool"]["complexipy"]["max-complexity-allowed"]
    return limit


def _complexity_findings(relatives: list[Path]) -> list[str]:
    limit = _cognitive_complexity_limit()
    result = _run(
        _venv_tool("complexipy"),
        "--max-complexity-allowed",
        str(limit),
        "--failed",
        "--plain",
        "--color=no",
        *(relative.as_posix() for relative in relatives),
    )
    findings = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= COMPLEXIPY_FIELDS and parts[-1].isdigit():
            findings.append(
                f"{_relative_name(' '.join(parts[:-2]))}: {parts[-2]} has cognitive "
                f"complexity {parts[-1]} (limit {limit}); split it rather than suppress it"
            )
    return findings


def _python_findings(relatives: list[Path]) -> list[str]:
    """ruff, complexipy and mypy over the (already fixed) files, side by side."""
    if not relatives:
        return []
    import concurrent.futures  # noqa: PLC0415 -- only the checks need it (see the imports)

    with concurrent.futures.ThreadPoolExecutor() as pool:
        ruff = pool.submit(_ruff_findings, relatives)
        complexity = pool.submit(_complexity_findings, relatives)
        mypy = pool.submit(_mypy_findings, relatives)
        return ruff.result() + complexity.result() + mypy.result()


# --- mypy through dmypy (S08) -----------------------------------------------
#
# A cold `mypy src` takes about 34s and a warm daemon recheck well under a
# second, so the hook only ever asks a daemon that has finished its first
# check. Everything lives in the gitignored .mypy_cache, one daemon per
# worktree.
DMYPY_STATUS = STATE / "dmypy.json"
# Holds the pid of the daemon whose first full check has finished.
DMYPY_WARM = STATE / "agent-lint-dmypy.warm"
# Present while a warm-up runs, so concurrent edits do not start a second one.
DMYPY_WARMING = STATE / "agent-lint-dmypy.warming"
WARMING_STALE_AFTER_S = 300
DMYPY_IDLE_TIMEOUT_S = 1800
DMYPY_CHECK_TIMEOUT_S = 20
# The daemon colours its report however its client asks, and agents read text.
ANSI = re.compile(r"\x1b\[[0-9;]*m")
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
INHERIT_HANDLE_NO = 0  # OpenProcess's bInheritHandle


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


def _pid_alive(pid: int) -> bool:
    """Whether a process runs, without starting one (`dmypy status` costs 0.3s)."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    # os.kill(pid, 0) would terminate the process on Windows.
    import ctypes  # noqa: PLC0415 -- only the mypy step needs it (see the imports)

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]  # -- Windows-only API
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, INHERIT_HANDLE_NO, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and (
            code.value == STILL_ACTIVE
        )
    finally:
        kernel32.CloseHandle(handle)


def _daemon_alive() -> bool:
    pid = _daemon_pid()
    return pid is not None and pid.isdigit() and _pid_alive(int(pid))


def _spawn_warm_up() -> None:
    """Start `warm-dmypy` in the background, detached from the hook."""
    try:
        if time.time() - DMYPY_WARMING.stat().st_mtime < WARMING_STALE_AFTER_S:
            return
    except OSError:
        pass
    DMYPY_WARMING.parent.mkdir(parents=True, exist_ok=True)
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
        # then gives up instead of starting a new one. Off the hot path, so
        # the exact `dmypy status` is affordable here.
        if _daemon_pid() is not None and _dmypy("status").returncode:
            DMYPY_STATUS.unlink(missing_ok=True)
        _dmypy("run", "--timeout", str(DMYPY_IDLE_TIMEOUT_S), "--", "src")
        pid = _daemon_pid()
        if pid is not None:
            DMYPY_WARM.write_text(pid)
    finally:
        DMYPY_WARMING.unlink(missing_ok=True)
    return 0


def _dmypy_check_in_process() -> str:
    """Ask the daemon directly, saving the 0.3s a `dmypy` client process costs."""
    if sys.flags.no_site:
        import site  # noqa: PLC0415 -- the gates start Python without site; only mypy needs the venv

        site.main()
    from mypy.dmypy.client import request  # noqa: PLC0415 -- loaded only when a src file changed

    response = request(
        str(DMYPY_STATUS), "check", timeout=DMYPY_CHECK_TIMEOUT_S, files=["src"], export_types=False
    )
    if "error" in response:
        raise RuntimeError(str(response["error"]))
    return str(response.get("out", ""))


def _dmypy_check() -> str:
    try:
        return _dmypy_check_in_process()
    except Exception:  # noqa: BLE001 -- mypy's client is private API; any failure falls back to the command
        pass
    try:
        return _dmypy("check", "src", timeout=DMYPY_CHECK_TIMEOUT_S).stdout
    except subprocess.TimeoutExpired:
        return ""


def _mypy_findings(relatives: list[Path]) -> list[str]:
    # `mypy src` is the gate; tests and scripts are not type-checked.
    wanted = {relative.as_posix() for relative in relatives if relative.parts[:1] == ("src",)}
    if not wanted:
        return []
    if not _daemon_alive():
        _spawn_warm_up()
        return []
    try:
        if DMYPY_WARM.read_text().strip() != _daemon_pid():
            return []  # still on its first check
    except OSError:
        return []
    # The whole of src is rechecked (rechecking one file would reset the
    # daemon's source set), but only the changed files' findings are reported.
    findings = []
    for line in ANSI.sub("", _dmypy_check()).splitlines():
        path, colon, rest = line.partition(":")
        name = path.replace("\\", "/")
        if colon and name in wanted:
            findings.append(f"{name}:{rest}")
    return findings


# --- suppressions (S07) -------------------------------------------------------


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
    # An editor that rewrites the file with CRLF endings has not added every
    # line in it.
    diff = _git(
        "diff", "--no-color", "--no-ext-diff", "--ignore-cr-at-eol", "-U0", "HEAD", "--",
        relative.as_posix(),
    )  # fmt: skip
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


# --- the shell snapshot -------------------------------------------------------
#
# Dirty source files by content hash, as of the last check. A file appears
# here once the hook has checked it in that state, so after a shell command
# only what changed since is checked again.
SNAPSHOT = STATE / "agent-lint-snapshot.json"
PORCELAIN_PREFIX = 3  # "XY " before each path in `git status --porcelain`


def _digest(path: Path) -> str:
    return hashlib.sha1(path.read_bytes(), usedforsecurity=False).hexdigest()


def _dirty_sources() -> dict[str, str]:
    """Every modified, staged or untracked source file, by content."""
    # Filtered here rather than with `-- '*.py'` pathspecs: a cygwin git
    # started from Windows Python expands those globs itself and lists nothing.
    fields = iter(_git("status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0"))
    dirty: dict[str, str] = {}
    for entry in fields:
        if entry[:1] in ("R", "C"):
            next(fields, None)  # a rename or copy names its source next
        path = ROOT / entry[PORCELAIN_PREFIX:]
        if path.suffix in SOURCE_SUFFIXES and path.is_file():
            dirty[entry[PORCELAIN_PREFIX:]] = _digest(path)
    return dirty


def _load_snapshot() -> dict[str, str]:
    try:
        snapshot: dict[str, str] = json.loads(SNAPSHOT.read_text())
    except (OSError, ValueError):
        return {}
    return snapshot


def _save_snapshot(snapshot: dict[str, str]) -> None:
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(snapshot))


def _remember(paths: list[Path]) -> None:
    """Record checked files as they now are, fixes included."""
    snapshot = _load_snapshot()
    for path in paths:
        relative = _inside_repo(path)
        if relative is not None and path.is_file():
            snapshot[relative.as_posix()] = _digest(path)
    _save_snapshot(snapshot)


# --- entry points -------------------------------------------------------------


def _report(findings: list[str]) -> None:
    shown = findings[:MAX_FINDINGS]
    omitted = len(findings) - len(shown)
    if omitted:
        shown.append(f"... {omitted} more findings omitted")
    print("\n".join(shown), file=sys.stderr)


def _check(paths: list[Path]) -> int:
    """Fix, then report, every lintable file among `paths`."""
    python, typescript = _lintable(paths)
    findings = [f for relative in typescript for f in _typescript_findings(relative, fix=True)]
    for relative in python:
        _fix_python(relative)
    findings += _python_findings(python)
    findings += [f for relative in python + typescript for f in _unexplained_suppressions(relative)]
    if not findings:
        return 0
    _report(findings)
    return FINDINGS


def edit(payload: dict[str, object]) -> int:
    paths = _edited_paths(payload)
    code = _check(paths)
    _remember(paths)
    return code


def shell() -> int:
    """After a shell command: check the source files it changed, whatever it was."""
    previous = _load_snapshot()
    changed = [
        ROOT / name for name, digest in _dirty_sources().items() if previous.get(name) != digest
    ]
    if not changed:
        return 0
    code = _check(changed)
    _save_snapshot(_dirty_sources())
    return code


def snapshot() -> int:
    """Take the working tree's dirty files as checked: earlier work, not this session's."""
    _save_snapshot(_dirty_sources())
    return 0


def session_start() -> int:
    snapshot()
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


def _staged() -> list[Path]:
    names = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [ROOT / name for name in names.split("\0") if name]


def pre_commit(paths: list[Path]) -> int:
    """The backstop for every commit, whatever wrote the files: report, fix nothing."""
    python, typescript = _lintable(paths or _staged())
    findings = [f for relative in typescript for f in _typescript_findings(relative, fix=False)]
    if python:
        findings += _ruff_findings(python) + _unformatted(python) + _complexity_findings(python)
    findings += [f for relative in python + typescript for f in _unexplained_suppressions(relative)]
    if not findings:
        return 0
    _report(findings)
    print(
        "pre-commit: fix these and commit again (`uv run poe fix` settles what ruff can).",
        file=sys.stderr,
    )
    return REFUSED


def run(mode: str, payload: dict[str, object]) -> int:
    """One hook event. The gates call this once they have read the payload."""
    if mode == "edit":
        return shell() if payload.get("tool_name") == "Bash" else edit(payload)
    handlers = {
        "shell": shell,
        "snapshot": snapshot,
        "session-start": session_start,
        "session-end": session_end,
    }
    handler = handlers.get(mode)
    return handler() if handler else 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "edit"
    if mode == "warm-dmypy":
        return warm_dmypy()
    if mode == "pre-commit":
        return pre_commit([Path(name).resolve() for name in sys.argv[2:]])
    # Hooks always send a payload; only edits and shell commands need it.
    return run(mode, json.loads(sys.stdin.read() or "{}"))


if __name__ == "__main__":
    sys.exit(main())
