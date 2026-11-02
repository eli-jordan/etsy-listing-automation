"""What a local CLI caller asks of the machine: find a command, run it.

Three questions cover every caller: the provider adapters' readiness probes
and generation calls, model discovery, and the CLI's prompt backends. Asking
them through one injected object rather than ``shutil``/``subprocess``
directly is what lets a test describe a machine (this CLI is installed, its
``--help`` says this) instead of patching module globals.

``LOCAL_CLI_HOST`` is the real machine. It adds no policy: a lookup is
``shutil.which``, so a cygwin-only binary stays invisible to it exactly as
before, and callers that need cygwin's own shell (``cli/prompts.py``) still
do that second step themselves.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from etsy_listings.core.ai.models import Deadline
from etsy_listings.core.ai.process import ProcessResult, run_managed


class CommandHost(Protocol):
    """Find and briefly run a command: probes and the CLI's fzf picker."""

    def which(self, name: str) -> str | None:
        """``name``'s executable path, or ``None`` when it is not on PATH."""
        ...

    def run(
        self,
        argv: Sequence[str],
        *,
        input_text: str | None = None,
        timeout: float | None = None,
        capture_stderr: bool = True,
        encoding: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run to completion as text with stdout captured, never checking the
        exit status. ``capture_stderr=False`` leaves stderr on the terminal.
        Raises ``OSError`` or ``subprocess.SubprocessError`` as
        ``subprocess.run`` does."""
        ...


class CliHost(CommandHost, Protocol):
    """A `CommandHost` that can also own a long-running provider process."""

    def run_managed(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        input_text: str,
        deadline: Deadline,
        cancel_event: threading.Event | None = None,
    ) -> ProcessResult:
        """`ai/process.py.run_managed`: deadline, cancellation, tree cleanup."""
        ...


class LocalCliHost:
    """This machine, through ``shutil``, ``subprocess`` and `run_managed`."""

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    # jscpd:ignore-start -- S05/S07: a protocol and its adapter state one signature twice.
    def run(
        self,
        argv: Sequence[str],
        *,
        input_text: str | None = None,
        timeout: float | None = None,
        capture_stderr: bool = True,
        encoding: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        # jscpd:ignore-end -- the body below is this adapter's own.
        return subprocess.run(
            list(argv),
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if capture_stderr else None,
            text=True,
            encoding=encoding,
            timeout=timeout,
            check=False,
        )

    def run_managed(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        input_text: str,
        deadline: Deadline,
        cancel_event: threading.Event | None = None,
    ) -> ProcessResult:
        return run_managed(
            argv, cwd=cwd, input_text=input_text, deadline=deadline, cancel_event=cancel_event
        )


LOCAL_CLI_HOST: CliHost = LocalCliHost()
