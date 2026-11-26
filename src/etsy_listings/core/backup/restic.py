from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from etsy_listings.core.backup.repository import (
    BackupFigures,
    BackupListener,
    BackupSummary,
    RepositoryCheck,
    RepositoryLockedError,
    RepositoryNotFoundError,
    ResticCancelledError,
    ResticError,
    RestoreProgress,
    Snapshot,
    WrongPasswordError,
    workspace_tag,
)
from etsy_listings.core.config.settings import RetentionSettings

logger = logging.getLogger(__name__)

STOP_GRACE_SECONDS = 5.0
"""How long an interrupted restic gets to remove its lock before it is
killed. A killed restic leaves a lock behind, which restic itself treats as
stale once it sees the process is gone from this host."""
CANCEL_POLL_SECONDS = 0.1

PARTIAL_SNAPSHOT_EXIT = 3
"""``restic backup``: the snapshot was made, but some files could not be read."""

RETRY_LOCK = "1h"
"""A restore started while a weekly prune holds restic's exclusive lock
waits for it rather than failing. An hour is more than any prune here."""

_INHERITED_TO_DROP = (
    "RESTIC_PASSWORD_FILE",
    "RESTIC_PASSWORD_COMMAND",
    "RESTIC_REPOSITORY",
    "RESTIC_REPOSITORY_FILE",
)
"""Shell settings that would make restic refuse two password sources, or
open a different repository than the one named with ``--repo``."""


_ERRORS: Mapping[int, type[ResticError]] = {
    10: RepositoryNotFoundError,
    11: RepositoryLockedError,
    12: WrongPasswordError,
    130: ResticCancelledError,
}
"""restic's documented exit codes (restic 0.17 and later)."""


class ResticProcess(Protocol):
    @property
    def stdout(self) -> Iterable[str]: ...
    def wait(self) -> int: ...
    def stderr(self) -> str: ...
    def stop(self) -> None: ...


Launch = Callable[[Sequence[str], Mapping[str, str]], ResticProcess]
"""Start ``argv`` with exactly the environment ``env``."""


class Restic:
    def __init__(
        self, binary: Path, repository: Path, password: str, *, launch: Launch | None = None
    ) -> None:
        self.binary = binary
        self.repository = repository
        self._password = password
        self._launch = launch or launch_process

    def __repr__(self) -> str:
        return f"Restic({str(self.binary)!r}, {str(self.repository)!r})"

    @property
    def path(self) -> Path:
        return self.repository

    def init(self) -> str:
        for message in self.run("init"):
            if isinstance(message, dict) and message.get("message_type") == "initialized":
                return str(message["id"])
        raise ResticError("restic init reported no repository id")

    def snapshots(self, *, lock: bool = True) -> tuple[Snapshot, ...]:
        args = ("snapshots",) if lock else ("--no-lock", "snapshots")
        found = [
            _snapshot(raw) for line in self.run(*args) if isinstance(line, list) for raw in line
        ]
        return tuple(sorted(found, key=lambda snapshot: snapshot.time))

    def back_up(
        self,
        folder: Path,
        *,
        workspace_id: str,
        excludes: Sequence[str] = (),
        progress: BackupListener | None = None,
        cancel: threading.Event | None = None,
    ) -> BackupSummary:
        arguments = ["backup", str(folder), "--tag", workspace_tag(workspace_id)]
        for pattern in excludes:
            arguments += ["--exclude", pattern]
        heard = _BackupLines(progress or (lambda _: None))
        try:
            for line in self.stream(*arguments, cancel=cancel):
                heard.hear(line)
        except ResticError as exc:
            if exc.exit_code != PARTIAL_SNAPSHOT_EXIT or heard.snapshot_id is None:
                raise
        return BackupSummary(heard.snapshot_id, heard.data_added, tuple(heard.warnings))

    def forget(
        self,
        retention: RetentionSettings,
        *,
        workspace_id: str,
        cancel: threading.Event | None = None,
    ) -> None:
        self.run(*forget_arguments(retention, workspace_id), cancel=cancel)

    def prune(self, *, cancel: threading.Event | None = None) -> None:
        self.run("prune", cancel=cancel)

    def check(self, *, cancel: threading.Event | None = None) -> RepositoryCheck:
        try:
            self.run("check", cancel=cancel)
        except ResticCancelledError:
            raise
        except ResticError as exc:
            return RepositoryCheck(ok=False, message=str(exc))
        return RepositoryCheck(ok=True)

    def restore(
        self,
        snapshot: Snapshot,
        target: Path,
        *,
        progress: Callable[[RestoreProgress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> RestoreProgress:
        figures = RestoreProgress()
        for line in self.stream(*restore_arguments(snapshot, target), cancel=cancel):
            heard = _restore_figures(figures, line)
            if heard is not None:
                figures = heard
                if progress is not None:
                    progress(figures)
        return figures

    def verify_password(self) -> None:
        self.run("--no-lock", "cat", "config")

    def stream(self, *args: str, cancel: threading.Event | None = None) -> Iterator[Any]:
        if cancel is not None and cancel.is_set():
            raise ResticCancelledError(f"restic {args[0] if args else ''} was stopped")
        argv = [str(self.binary), "--repo", str(self.repository), "--json", *args]
        logger.debug("running restic: %s", argv)
        try:
            process = self._launch(argv, self._environment())
        except OSError as exc:
            raise ResticError(f"Could not run restic at {self.binary}: {exc}") from exc
        watch = _stop_on_cancel(process, cancel)
        code: int | None = None
        try:
            yield from _json_lines(process.stdout)
            code = process.wait()
        finally:
            watch.done.set()
            if code is None:
                process.stop()
        if watch.cancelled.is_set():
            raise ResticCancelledError(f"restic {args[0] if args else ''} was stopped")
        if code != 0:
            raise self._failure(code, process.stderr())

    def run(self, *args: str, cancel: threading.Event | None = None) -> list[Any]:
        return list(self.stream(*args, cancel=cancel))

    def _environment(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in _INHERITED_TO_DROP}
        env["RESTIC_PASSWORD"] = self._password
        return env

    def _failure(self, code: int, stderr: str) -> ResticError:
        message = _exit_message(stderr) or stderr.strip()[-2000:] or f"exit code {code}"
        message = message.replace(self._password, "***")
        error = _ERRORS.get(code, ResticError)
        return error(f"restic: {message}", exit_code=code)


def forget_arguments(retention: RetentionSettings, workspace_id: str) -> tuple[str, ...]:
    # restic counts the current week and month, so N past ones keep N + 1.
    return (
        "forget",
        "--tag",
        workspace_tag(workspace_id),
        "--group-by",
        "tags",
        "--keep-within",
        f"{retention.keep_within_days}d",
        "--keep-weekly",
        str(retention.weekly + 1),
        "--keep-monthly",
        str(retention.monthly + 1),
    )


_DRIVE = re.compile(r"^([A-Za-z]):[\\/]?(.*)$")


def tree_path(path: str) -> str:
    drive = _DRIVE.match(path)
    if drive is None:
        return path
    return f"/{drive.group(1)}/{drive.group(2)}".replace("\\", "/").rstrip("/")


def restore_arguments(snapshot: Snapshot, target: Path) -> tuple[str, ...]:
    ref = (
        snapshot.id if len(snapshot.paths) != 1 else f"{snapshot.id}:{tree_path(snapshot.paths[0])}"
    )
    return (
        "restore",
        ref,
        "--target",
        str(target),
        "--overwrite",  # never: a file that reached the target after its check stays
        "never",
        "--retry-lock",
        RETRY_LOCK,
    )


def _snapshot(raw: Mapping[str, Any]) -> Snapshot:
    summary = raw.get("summary") or {}
    return Snapshot(
        id=raw["id"],
        short_id=raw["short_id"],
        time=datetime.fromisoformat(raw["time"]),
        paths=tuple(raw.get("paths") or ()),
        hostname=raw.get("hostname", ""),
        files=summary.get("total_files_processed"),
        size=summary.get("total_bytes_processed"),
        tags=tuple(raw.get("tags") or ()),
    )


@dataclass
class _BackupLines:
    progress: BackupListener
    snapshot_id: str | None = None
    data_added: int | None = None
    warnings: list[str] = field(default_factory=list)

    def hear(self, line: object) -> None:
        if not isinstance(line, dict):
            return
        kind = line.get("message_type")
        if kind == "status":
            self.progress(BackupFigures(line.get("files_done", 0), line.get("total_files")))
        elif kind == "summary":
            self.snapshot_id = line.get("snapshot_id")
            self.data_added = line.get("data_added")
        elif kind == "error":
            error = line.get("error") or {}
            self.warnings.append(f"{line.get('item', '')}: {error.get('message', '')}")


def _restore_figures(figures: RestoreProgress, line: object) -> RestoreProgress | None:
    if not isinstance(line, dict) or line.get("message_type") not in ("status", "summary"):
        return None
    summary = line["message_type"] == "summary"
    fraction = 1.0 if summary else float(line.get("percent_done", figures.fraction))
    return RestoreProgress(
        fraction=fraction,
        bytes_done=line.get("bytes_restored", figures.bytes_done),
        bytes_total=line.get("total_bytes", figures.bytes_total),
        files_done=line.get("files_restored", figures.files_done),
        files_total=line.get("total_files", figures.files_total),
        seconds_left=0 if summary else _seconds_left(line, fraction),
    )


def _seconds_left(line: Mapping[str, object], fraction: float) -> int | None:
    elapsed = line.get("seconds_elapsed")
    if not isinstance(elapsed, int | float) or fraction <= 0:
        return None
    return round(elapsed * (1 - fraction) / fraction)


def _json_lines(lines: Iterable[str]) -> Iterator[Any]:
    for line in lines:
        try:
            yield json.loads(line)
        except ValueError:
            continue


def _exit_message(stderr: str) -> str | None:
    for line in reversed(stderr.splitlines()):
        with contextlib.suppress(ValueError):
            parsed = json.loads(line)
            if isinstance(parsed, dict) and parsed.get("message_type") == "exit_error":
                return str(parsed.get("message", ""))
    return None


@dataclass(frozen=True)
class _Watch:
    done: threading.Event
    cancelled: threading.Event


def _stop_on_cancel(process: ResticProcess, cancel: threading.Event | None) -> _Watch:
    watch = _Watch(threading.Event(), threading.Event())
    if cancel is None:
        return watch

    def watcher() -> None:
        while not watch.done.is_set():
            if cancel.wait(CANCEL_POLL_SECONDS):
                if not watch.done.is_set():
                    watch.cancelled.set()
                    process.stop()
                return

    threading.Thread(target=watcher, name="restic-cancel", daemon=True).start()
    return watch


class _PopenProcess:
    """restic in its own process group, so stopping it reaches its children."""

    def __init__(self, argv: Sequence[str], env: Mapping[str, str]) -> None:
        options: dict[str, Any] = {}
        if sys.platform == "win32":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        self._process = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env),
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **options,
        )
        self._stderr: deque[str] = deque(maxlen=256)
        self._reader = threading.Thread(target=self._read_stderr, name="restic-stderr", daemon=True)
        self._reader.start()

    @property
    def stdout(self) -> Iterator[str]:
        assert self._process.stdout is not None
        yield from self._process.stdout

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        with contextlib.suppress(OSError, ValueError):
            for line in self._process.stderr:
                self._stderr.append(line)

    def wait(self) -> int:
        code = self._process.wait()
        self._reader.join(timeout=5)
        return code

    def stderr(self) -> str:
        return "".join(self._stderr)

    def stop(self) -> None:
        # Interrupt first: restic removes its lock on SIGINT/CTRL_BREAK, not on a kill.
        if self._process.poll() is not None:
            return
        with contextlib.suppress(OSError):
            self._interrupt()
        try:
            self._process.wait(timeout=STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._kill()
            self._process.wait()

    def _interrupt(self) -> None:
        if sys.platform == "win32":
            self._process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(self._process.pid, signal.SIGINT)

    def _kill(self) -> None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self._process.pid)],
                capture_output=True,
                check=False,
            )
            self._process.kill()
        else:
            with contextlib.suppress(OSError):
                os.killpg(self._process.pid, signal.SIGKILL)


def launch_process(argv: Sequence[str], env: Mapping[str, str]) -> ResticProcess:
    return _PopenProcess(argv, env)
