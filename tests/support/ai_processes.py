"""Managed CLI process substitutes, without installed or signed-in providers."""

import json
import shlex
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from etsy_listings.core.ai.models import Deadline
from etsy_listings.core.ai.process import ProcessResult

from tests.support.cli_host import ScriptedCliHost

CODEX_MODELS = json.dumps(
    {
        "models": [
            {
                "slug": "sol",
                "display_name": "Sol",
                "supported_reasoning_levels": [{"effort": "high"}, {"effort": "ultra"}],
            },
            {"slug": "hidden", "visibility": "hide"},
        ]
    }
)
GROK_MODELS = (
    "You are logged in with grok.com.\n\nDefault model: grok-4.7\n\n"
    "Available models:\n  * grok-4.7 (default)\n  - grok-4.6\n"
)


@dataclass
class ModelCli:
    codex: str = CODEX_MODELS
    grok: str = GROK_MODELS
    failure: bool = False
    during: Callable[[Deadline, threading.Event], None] | None = None
    calls: list[list[str]] = field(default_factory=list)

    def __call__(
        self, argv: list[str], *, deadline: Deadline, cancel_event: threading.Event, **kwargs: Any
    ) -> ProcessResult:
        self.calls.append(argv)
        if self.during is not None:
            self.during(deadline, cancel_event)
        return ProcessResult(
            returncode=1 if self.failure else 0,
            stdout=self.codex if argv[0] == "codex" else self.grok,
            stderr="",
            timed_out=self.failure,
            cancelled=cancel_event.is_set(),
        )

    @property
    def host(self) -> ScriptedCliHost:
        """A machine with both catalog CLIs on PATH under their own names,
        every managed run answered by this catalog."""
        return ScriptedCliHost(installed={"codex": "codex", "grok": "grok"}, managed={(): self})


def local_cli(root: Path, script: str) -> Path:
    """An actual synthetic executable for the real process-owner boundary."""
    source = root / "cli.py"
    source.write_text(script, encoding="utf-8")
    arguments = [sys.executable, str(source)]
    if sys.platform == "win32":
        command = root / "cli.cmd"
        command.write_text("@" + subprocess.list2cmdline(arguments) + "\r\n", encoding="utf-8")
    else:
        command = root / "cli"
        command.write_text("#!/bin/sh\nexec " + shlex.join(arguments) + "\n", encoding="utf-8")
        command.chmod(0o755)
    return command
