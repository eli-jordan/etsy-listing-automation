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
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


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


@dataclass
class Launch:
    argv: list[str]
    env: dict[str, str]


@dataclass
class _Process:
    reply: Reply
    stopped: threading.Event = field(default_factory=threading.Event)

    @property
    def stdout(self) -> Iterator[str]:
        for line in self.reply.stdout:
            yield (line if isinstance(line, str) else json.dumps(line)) + "\n"
        if self.reply.hang:
            self.stopped.wait(timeout=10)

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

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> _Process:
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
