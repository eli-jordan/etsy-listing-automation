"""Managed CLI process substitutes, without installed or signed-in providers."""

import json
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from etsy_listings.core.ai.models import Deadline
from etsy_listings.core.ai.process import ProcessResult

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


def redirect_local_cli(monkeypatch: Any, name: str, script: str) -> None:
    """Replace only this external executable with real local Python children.

    taskkill and all other subprocesses still use the operating system.
    """
    real_popen = subprocess.Popen

    def launch(argv: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        return real_popen([sys.executable, "-c", script] if argv[0] == name else argv, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", launch)
