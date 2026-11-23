"""A restic launcher that replays recorded ``--json`` output (workspace-backup
plan, P3).

Pass ``ScriptedRestic`` as ``Restic(launch=...)``. Each command it is asked to
run takes the next :class:`Reply`, and every launch is recorded with its argv
and environment, so a test can check what restic would have been given.
Lines in the replies are copied from restic 0.19.1's real output.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePath
from typing import Any

from etsy_listings.core.backup.restic import ResticProcess


def exit_error(code: int, message: str) -> str:
    """restic's last stderr line when a command fails under ``--json``."""
    return json.dumps({"message_type": "exit_error", "code": code, "message": message})


@dataclass
class Reply:
    stdout: Sequence[Any] = ()
    """Each item is one stdout line: a string as is, anything else as JSON."""
    stderr: str = ""
    exit_code: int = 0
    hang: bool = False
    """Keep running after the last line until stopped, like a long backup."""
    release: threading.Event | None = None
    """Ends a hang without a stop; ``after`` is written then."""
    after: Sequence[Any] = ()


@dataclass
class Launch:
    argv: list[str]
    env: dict[str, str]


def _lines(lines: Sequence[Any]) -> Iterator[str]:
    for line in lines:
        yield (line if isinstance(line, str) else json.dumps(line)) + "\n"


@dataclass
class _Process:
    reply: Reply
    stopped: threading.Event = field(default_factory=threading.Event)

    @property
    def stdout(self) -> Iterator[str]:
        yield from _lines(self.reply.stdout)
        if self.reply.hang:
            release = self.reply.release or threading.Event()
            deadline = time.monotonic() + 10
            while not (self.stopped.wait(0.01) or release.is_set()):
                if time.monotonic() > deadline:
                    return
            if release.is_set():
                yield from _lines(self.reply.after)

    def wait(self) -> int:
        if self.stopped.is_set():
            return 1
        return self.reply.exit_code

    def stderr(self) -> str:
        return self.reply.stderr

    def stop(self) -> None:
        self.stopped.set()


class ScriptedRestic:
    """The launcher: answers launches in order with ``replies``."""

    def __init__(self, *replies: Reply) -> None:
        self._replies = list(replies)
        self.launches: list[Launch] = []
        self.processes: list[_Process] = []

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> ResticProcess:
        if not self._replies:
            raise AssertionError(f"restic was run more times than scripted: {list(argv)}")
        self.launches.append(Launch(list(argv), dict(env)))
        process = _Process(self._replies.pop(0))
        self.processes.append(process)
        return process

    @property
    def commands(self) -> list[list[str]]:
        """Each launch's argv after the binary and the global flags."""
        return [launch.argv[launch.argv.index("--json") + 1 :] for launch in self.launches]


def snapshot_json(time: datetime, number: int) -> dict[str, Any]:
    """One entry of ``restic snapshots --json``, trimmed to what is read."""
    snapshot_id = f"{number:064x}"
    return {
        "time": time.isoformat(),
        "paths": ["/workspace"],
        "hostname": "pc",
        "id": snapshot_id,
        "short_id": snapshot_id[:8],
    }


RESTORE_STATUS = {
    "message_type": "status",
    "seconds_elapsed": 60,
    "percent_done": 0.25,
    "total_files": 400,
    "files_restored": 100,
    "total_bytes": 8_000_000,
    "bytes_restored": 2_000_000,
}
"""A ``restic restore --json`` status line, a quarter of the way."""
RESTORE_SUMMARY = {
    "message_type": "summary",
    "total_files": 400,
    "files_restored": 400,
    "total_bytes": 8_000_000,
    "bytes_restored": 8_000_000,
}


class RepositoryRestic:
    """A launcher that answers by subcommand and keeps snapshots as a
    repository would, for callers whose commands interleave, such as a
    server whose scheduler and requests both read snapshots.

    ``init`` writes ``config`` into ``repository``; ``backup`` adds a
    snapshot at ``now()``, or keeps running until stopped while ``hang`` is
    set; ``restore`` reports a quarter done, then, while ``restore_hang`` is
    set, keeps running until stopped or ``restore_release`` is set;
    ``failing`` maps a subcommand to the reply that fails it.
    """

    def __init__(self, repository: Path, now: Callable[[], datetime]) -> None:
        self.repository = repository
        self.now = now
        self.snapshots: list[datetime] = []
        self.hang = False
        self.restore_hang = False
        self.restore_release = threading.Event()
        self.failing: dict[str, Reply] = {}
        self.commands: list[list[str]] = []
        self._processes: list[tuple[str, _Process]] = []
        self._lock = threading.Lock()

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> ResticProcess:
        command = [arg for arg in argv[list(argv).index("--json") + 1 :] if arg != "--no-lock"]
        with self._lock:
            self.commands.append(command)
            process = _Process(self._reply(command[0]))
            self._processes.append((command[0], process))
            return process

    def stopped(self, subcommand: str) -> int:
        """How many of ``subcommand``'s runs were stopped."""
        with self._lock:
            return sum(name == subcommand and p.stopped.is_set() for name, p in self._processes)

    def ran(self, subcommand: str) -> int:
        with self._lock:
            return sum(command[0] == subcommand for command in self.commands)

    def _reply(self, subcommand: str) -> Reply:
        if subcommand in self.failing:
            return self.failing[subcommand]
        answer = {
            "init": self._init,
            "snapshots": self._snapshots,
            "backup": self._backup,
            "restore": self._restore,
        }.get(subcommand)
        return Reply() if answer is None else answer()

    def _init(self) -> Reply:
        self.repository.mkdir(parents=True, exist_ok=True)
        (self.repository / "config").write_bytes(b"{}")
        return Reply(stdout=[{"message_type": "initialized", "id": "f00d"}])

    def _snapshots(self) -> Reply:
        listed = [snapshot_json(time, n) for n, time in enumerate(self.snapshots, 1)]
        return Reply(stdout=[listed])

    def _backup(self) -> Reply:
        if self.hang:
            return Reply(hang=True)
        self.snapshots.append(self.now())
        summary = snapshot_json(self.now(), len(self.snapshots))
        return Reply(stdout=[{"message_type": "summary", "snapshot_id": summary["id"]}])

    def _restore(self) -> Reply:
        if self.restore_hang:
            return Reply(
                stdout=[RESTORE_STATUS],
                hang=True,
                release=self.restore_release,
                after=[RESTORE_SUMMARY],
            )
        return Reply(stdout=[RESTORE_STATUS, RESTORE_SUMMARY])


def snapshot_path(path: PurePath) -> str:
    """How restic names a local folder inside a snapshot: a Windows drive
    becomes a top folder (``/C/Users/...``); a POSIX path is itself."""
    posix = path.as_posix()
    return posix if not path.drive else "/" + posix.replace(":", "", 1)
