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

    def which(self, name: str) -> str | None: ...

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
    def run_managed(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        input_text: str,
        deadline: Deadline,
        cancel_event: threading.Event | None = None,
    ) -> ProcessResult: ...


class LocalCliHost:
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
