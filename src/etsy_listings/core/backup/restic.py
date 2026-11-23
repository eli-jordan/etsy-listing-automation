"""One restic repository's commands, streamed (workspace-backup plan, P6).

Not ``core/ai/process.py``'s ``run_managed``: that takes no environment,
buffers stdout until exit and needs input text. restic needs the password in
its environment, reports progress as ``--json`` lines while it runs, and
reads nothing from stdin. So this launches restic with ``subprocess.Popen``
and line-buffered stdout, as ``preparation/worker_client.py`` does, and
yields each parsed line as it arrives.

The password goes only into the child's environment as ``RESTIC_PASSWORD``,
never onto the command line or into a log (spec, *Configuration*). restic's
exit codes become typed errors: 10 for a missing repository or a folder that
is not one, 11 for a lock held elsewhere, 12 for a wrong password. Their
message is restic's own, from the ``exit_error`` line ``--json`` writes to
stderr.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from etsy_listings.core.errors import UserFacingError

logger = logging.getLogger(__name__)

STOP_GRACE_SECONDS = 5.0
"""How long an interrupted restic gets to remove its lock before it is
killed. A killed restic leaves a lock behind, which restic itself treats as
stale once it sees the process is gone from this host."""
CANCEL_POLL_SECONDS = 0.1

_INHERITED_TO_DROP = (
    "RESTIC_PASSWORD_FILE",
    "RESTIC_PASSWORD_COMMAND",
    "RESTIC_REPOSITORY",
    "RESTIC_REPOSITORY_FILE",
)
"""Shell settings that would make restic refuse two password sources, or
open a different repository than the one named with ``--repo``."""


class ResticError(UserFacingError):
    """A restic command failed; the message is restic's own."""

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class RepositoryNotFoundError(ResticError):
    """The repository folder is missing or is not a restic repository (exit 10)."""


class RepositoryLockedError(ResticError):
    """Another restic holds a lock that this command cannot share (exit 11)."""


class WrongPasswordError(ResticError):
    """No key in the repository opens with the password (exit 12)."""


class ResticCancelledError(ResticError):
    """The command was stopped before it finished."""


_ERRORS: Mapping[int, type[ResticError]] = {
    10: RepositoryNotFoundError,
    11: RepositoryLockedError,
    12: WrongPasswordError,
    130: ResticCancelledError,
}
"""restic's documented exit codes (restic 0.17 and later)."""


class ResticProcess(Protocol):
    """A running restic: its stdout lines, then its exit code and stderr."""

    @property
    def stdout(self) -> Iterable[str]: ...
    def wait(self) -> int: ...
    def stderr(self) -> str: ...
    def stop(self) -> None: ...


Launch = Callable[[Sequence[str], Mapping[str, str]], ResticProcess]
"""Start ``argv`` with exactly the environment ``env``."""


@dataclass(frozen=True)
class Snapshot:
    id: str
    short_id: str
    time: datetime
    paths: tuple[str, ...]
    hostname: str
    files: int | None = None
    """Files the backup read, from the snapshot's summary (restic 0.17+)."""
    size: int | None = None
    """Bytes the backup read, from the snapshot's summary."""

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> Snapshot:
        summary = raw.get("summary") or {}
        return cls(
            id=raw["id"],
            short_id=raw["short_id"],
            time=datetime.fromisoformat(raw["time"]),
            paths=tuple(raw.get("paths") or ()),
            hostname=raw.get("hostname", ""),
            files=summary.get("total_files_processed"),
            size=summary.get("total_bytes_processed"),
        )


class Restic:
    """The commands of the repository at ``repository``."""

    def __init__(
        self, binary: Path, repository: Path, password: str, *, launch: Launch | None = None
    ) -> None:
        self.binary = binary
        self.repository = repository
        self._password = password
        self._launch = launch or launch_process

    def __repr__(self) -> str:
        return f"Restic({str(self.binary)!r}, {str(self.repository)!r})"

    def stream(self, *args: str, cancel: threading.Event | None = None) -> Iterator[Any]:
        """Run ``restic <args> --json`` and yield each JSON line as it comes.

        Raises a :class:`ResticError` once restic exits unsuccessfully, and
        :class:`ResticCancelledError` when ``cancel`` was set while it ran.
        Closing the iterator early stops restic.
        """
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
            if code is None:  # abandoned or failed part way: restic must not outlive us
                process.stop()
        if watch.cancelled.is_set():
            raise ResticCancelledError(f"restic {args[0] if args else ''} was stopped")
        if code != 0:
            raise self._failure(code, process.stderr())

    def run(self, *args: str, cancel: threading.Event | None = None) -> list[Any]:
        """:meth:`stream`, collected."""
        return list(self.stream(*args, cancel=cancel))

    def init(self) -> str:
        """Create the repository; its id."""
        for message in self.run("init"):
            if isinstance(message, dict) and message.get("message_type") == "initialized":
                return str(message["id"])
        raise ResticError("restic init reported no repository id")

    def snapshots(self, *, lock: bool = True) -> tuple[Snapshot, ...]:
        """Every snapshot, oldest first. ``lock=False`` reads without taking
        restic's shared lock, for a status check that must not wait."""
        args = ("snapshots",) if lock else ("--no-lock", "snapshots")
        found = [
            Snapshot.from_json(raw)
            for line in self.run(*args)
            if isinstance(line, list)
            for raw in line
        ]
        return tuple(sorted(found, key=lambda snapshot: snapshot.time))

    def _environment(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in _INHERITED_TO_DROP}
        env["RESTIC_PASSWORD"] = self._password
        return env

    def _failure(self, code: int, stderr: str) -> ResticError:
        message = _exit_message(stderr) or stderr.strip()[-2000:] or f"exit code {code}"
        message = message.replace(self._password, "***")
        error = _ERRORS.get(code, ResticError)
        return error(f"restic: {message}", exit_code=code)


def _json_lines(lines: Iterable[str]) -> Iterator[Any]:
    for line in lines:
        try:
            yield json.loads(line)
        except ValueError:
            continue


def _exit_message(stderr: str) -> str | None:
    """The message of restic's ``exit_error`` line, its last on stderr."""
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
    """Stop ``process`` when ``cancel`` is set before it finishes."""
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


# ------------------------------------------------------------- the launcher


class _PopenProcess:
    """restic as a child process in its own process group, so stopping it
    reaches anything it started too."""

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
        """Interrupt, so restic can remove its lock, then kill the group."""
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
    """Start ``argv`` as restic's real launcher does."""
    return _PopenProcess(argv, env)
