"""A scripted machine for everything that finds or runs a local command.

`ScriptedCliHost` is the one `CliHost` double: the provider adapters'
readiness probes and generation calls, model discovery, and the prompt
backends' fzf lookup and picker all ask it instead of ``shutil.which`` and
``subprocess``. A test says what is installed and how each command answers;
the double records every call.

Answers are keyed by an argv prefix *after* the program, so ``("login",
"status")`` answers ``/usr/bin/codex login status`` wherever ``codex`` was
found. The longest matching key wins and ``()`` matches anything, which makes
it the default. An unscripted command fails the test rather than inventing an
answer.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from etsy_listings.core.ai.models import Deadline
from etsy_listings.core.ai.process import ProcessResult

type RunAnswer = subprocess.CompletedProcess[str] | Exception
"""A completed run, or what ``subprocess.run`` raises instead."""


class ManagedResponder(Protocol):
    """Answers a managed run while it is happening: what a test needs when
    the command's files exist only for the call (Codex's ``-o`` file, Grok's
    prompt file), or when the call must block, or to reach a real runner."""

    def __call__(
        self,
        argv: list[str],
        *,
        cwd: Path,
        input_text: str,
        deadline: Deadline,
        cancel_event: threading.Event | None,
    ) -> ProcessResult: ...


type ManagedAnswer = ProcessResult | ManagedResponder


def completed(stdout: str = "", *, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    """A finished probe, for a ``runs`` table."""
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def finished(stdout: str = "", stderr: str = "", *, returncode: int | None = 0) -> ProcessResult:
    """A managed run that ran to its end, for a ``managed`` table."""
    return ProcessResult(returncode, stdout, stderr, timed_out=False, cancelled=False)


@dataclass(frozen=True)
class Run:
    argv: list[str]
    input_text: str | None
    timeout: float | None
    capture_stderr: bool
    encoding: str | None


@dataclass(frozen=True)
class ManagedRun:
    argv: list[str]
    cwd: Path
    input_text: str
    deadline: Deadline
    cancel_event: threading.Event | None


@dataclass(eq=False)
class ScriptedCliHost:
    """``installed`` maps a command name to the path ``which`` reports;
    anything else is not on PATH. ``runs`` and ``managed`` answer by argv
    prefix (see the module docstring). Calls land in ``run_calls`` and
    ``managed_calls``."""

    installed: Mapping[str, str] = field(default_factory=dict)
    runs: Mapping[tuple[str, ...], RunAnswer] = field(default_factory=dict)
    managed: Mapping[tuple[str, ...], ManagedAnswer] = field(default_factory=dict)
    run_calls: list[Run] = field(default_factory=list)
    managed_calls: list[ManagedRun] = field(default_factory=list)

    def which(self, name: str) -> str | None:
        return self.installed.get(name)

    def run(
        self,
        argv: Sequence[str],
        *,
        input_text: str | None = None,
        timeout: float | None = None,
        capture_stderr: bool = True,
        encoding: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.run_calls.append(Run(list(argv), input_text, timeout, capture_stderr, encoding))
        answer = _answer(self.runs, argv, "run")
        if isinstance(answer, Exception):
            raise answer
        return answer

    def run_managed(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        input_text: str,
        deadline: Deadline,
        cancel_event: threading.Event | None = None,
    ) -> ProcessResult:
        self.managed_calls.append(ManagedRun(list(argv), cwd, input_text, deadline, cancel_event))
        answer = _answer(self.managed, argv, "run_managed")
        if isinstance(answer, ProcessResult):
            return answer
        return answer(
            list(argv),
            cwd=cwd,
            input_text=input_text,
            deadline=deadline,
            cancel_event=cancel_event,
        )

    @property
    def ran(self) -> list[list[str]]:
        """Every ``run`` argv, in order."""
        return [call.argv for call in self.run_calls]

    @property
    def last_managed(self) -> ManagedRun:
        return self.managed_calls[-1]


def _answer[T](table: Mapping[tuple[str, ...], T], argv: Sequence[str], kind: str) -> T:
    args = tuple(argv[1:])
    keys = [key for key in table if args[: len(key)] == key]
    if not keys:
        raise AssertionError(f"unscripted {kind}: {list(argv)!r}")
    return table[max(keys, key=len)]


def never_launched(argv: list[str], **_: object) -> ProcessResult:
    """A ``managed`` answer for a command the code must refuse to start."""
    raise AssertionError(f"{argv[0]} must not be launched")
