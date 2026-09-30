"""The Grok CLI adapter behind `AiProvider`.

Same job as `ai/claude.py` and `ai/codex.py`: one non-interactive, read-only
generation call, no prompt of its own, and the raw response text handed back
for the shared orchestrator to validate. Flags below were confirmed against
`grok --help` and a live `--output-format json` run of Grok 1.0.41:

- ``--prompt-file`` carries the prompt. A seller prompt plus schema is too
  long for Windows' command-line limit, and ``-p`` wants the prompt on argv.
- ``--json-schema`` constrains the answer and implies ``--output-format
  json``. The schema-valid object is ``structuredOutput``. ``text`` is only
  the model's rendering of it, so the adapter returns the structured object.
- ``--tools read_file,grep,list_dir`` is the read-only set. Write, bash and
  web tools are simply not offered. ``--permission-mode dontAsk`` denies
  anything that still prompts. ``--no-subagents`` and
  ``--disable-web-search`` keep the call on that one job.
- ``--sandbox read-only`` is documented for Linux and macOS. This project's
  development machine is Windows, where that sandbox is not the guarantee,
  so the tool allowlist is what makes the process read-only.
- There is no ``--no-session-persistence``. Each call omits ``--resume`` and
  ``--session-id``, so it does not continue a previous conversation. Grok
  still writes a new session under its own home directory; that is the CLI's
  behaviour, not a session this adapter reads back.
- No ``--model``. The account's configured model is used as-is.
- The design image has no attach flag. Its path is named in the prompt and
  the model opens it with ``read_file``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etsy_listings.ai.errors import (
    ProviderCancelledError,
    ProviderGenerationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    classify_process_failure,
)
from etsy_listings.ai.models import (
    Deadline,
    ProviderReadiness,
    ProviderTask,
    RawProviderResult,
    RepairContext,
)
from etsy_listings.ai.process import run_managed
from etsy_listings.ai.repair import prompt_text_for

PROVIDER_NAME = "grok"

_READINESS_TIMEOUT_SECONDS = 15.0

_READ_ONLY_TOOLS = "read_file,grep,list_dir"
"""Allowlist passed to ``--tools``. Headless tool ids from Grok's own
readme: read, search, list. ``search_replace``, ``bash`` and the web tools
are absent, which is what keeps the process from writing."""

_REQUIRED_HELP_FLAGS: tuple[str, ...] = (
    "--json-schema",
    "--output-format",
    "--prompt-file",
    "--tools",
    "--permission-mode",
    "--no-subagents",
)

_MAX_TURNS = "8"
"""Enough to open the design image and answer. An unbounded turn count is
how a read-only call wanders until the shared deadline kills it."""


def auth_file() -> Path:
    """Where `grok login` stores the session. Readiness only checks that the
    file exists and is non-empty -- it does not parse the credential."""
    return Path.home() / ".grok" / "auth.json"


@dataclass
class GrokProvider:
    """The `AiProvider` adapter for the local Grok CLI."""

    workspace_root: Path
    binary: str = "grok"

    def _resolved_binary(self) -> str:
        """See `CodexProvider._resolved_binary`: on Windows the bare name is
        not launchable without ``shell=True``."""
        return shutil.which(self.binary) or self.binary

    def readiness(self) -> ProviderReadiness:
        if shutil.which(self.binary) is None:
            return ProviderReadiness(ready=False, reason=f"{self.binary} was not found on PATH")

        unavailable = self._check_authenticated()
        if unavailable is not None:
            return unavailable

        unavailable = self._check_headless_capability()
        if unavailable is not None:
            return unavailable

        return ProviderReadiness(ready=True)

    def _check_authenticated(self) -> ProviderReadiness | None:
        path = auth_file()
        try:
            present = path.is_file() and path.stat().st_size > 0
        except OSError as exc:
            return ProviderReadiness(
                ready=False, reason=f"could not check `{self.binary}` credentials: {exc}"
            )
        if not present:
            return ProviderReadiness(
                ready=False,
                reason=f"{self.binary} is not authenticated (run `{self.binary} login`)",
            )
        return None

    def _check_headless_capability(self) -> ProviderReadiness | None:
        try:
            result = subprocess.run(
                [self._resolved_binary(), "--help"],
                capture_output=True,
                text=True,
                timeout=_READINESS_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ProviderReadiness(
                ready=False, reason=f"could not check `{self.binary} --help`: {exc}"
            )
        if result.returncode != 0:
            return ProviderReadiness(
                ready=False, reason=f"`{self.binary} --help` exited {result.returncode}"
            )
        missing = [flag for flag in _REQUIRED_HELP_FLAGS if flag not in result.stdout]
        if missing:
            return ProviderReadiness(
                ready=False,
                reason=(
                    f"the installed {self.binary} CLI does not support the required "
                    f"headless flags: {', '.join(missing)}"
                ),
            )
        return None

    def generate(
        self,
        task: ProviderTask,
        deadline: Deadline,
        *,
        repair: RepairContext | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RawProviderResult:
        if shutil.which(self.binary) is None:
            raise ProviderUnavailableError(PROVIDER_NAME, f"{self.binary} was not found on PATH")
        prompt_text = self._prompt_text(task, repair)
        prompt_path = self._write_prompt(prompt_text)
        argv = [
            self._resolved_binary(),
            "--prompt-file",
            str(prompt_path),
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(dict(task.response_schema)),
            "--tools",
            _READ_ONLY_TOOLS,
            "--permission-mode",
            "dontAsk",
            "--no-subagents",
            "--disable-web-search",
            "--max-turns",
            _MAX_TURNS,
            "--verbatim",
            "--cwd",
            str(self.workspace_root),
        ]
        try:
            result = run_managed(
                argv,
                cwd=self.workspace_root,
                input_text="",
                deadline=deadline,
                cancel_event=cancel_event,
            )
        finally:
            prompt_path.unlink(missing_ok=True)

        if result.cancelled:
            raise ProviderCancelledError(PROVIDER_NAME)
        if result.timed_out:
            raise ProviderTimeoutError(PROVIDER_NAME)
        if result.returncode != 0:
            raise classify_process_failure(
                PROVIDER_NAME,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return RawProviderResult(
            provider=PROVIDER_NAME, raw_output=self._extract_result_text(result.stdout)
        )

    def _extract_result_text(self, stdout: str) -> str:
        """The proposal JSON from ``--output-format json``.

        ``--json-schema`` puts the schema-valid object in
        ``structuredOutput``. ``text`` is only the model's own rendering of
        that answer, and it is often prose or a fenced block rather than
        JSON. The structured object is what gets validated.
        """
        try:
            envelope: Any = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ProviderGenerationError(
                PROVIDER_NAME, 0, f"stdout was not valid JSON: {exc}"
            ) from exc
        if not isinstance(envelope, dict):
            raise ProviderGenerationError(PROVIDER_NAME, 0, "stdout was not a JSON object")
        if envelope.get("is_error") or envelope.get("error"):
            reported = stdout
            text = envelope.get("text")
            if isinstance(text, str) and text.strip():
                reported = text
            raise classify_process_failure(PROVIDER_NAME, returncode=0, stdout=reported, stderr="")
        structured = envelope.get("structuredOutput")
        if isinstance(structured, dict):
            return json.dumps(structured)
        text = envelope.get("text")
        if isinstance(text, str) and text.strip():
            return text
        raise ProviderGenerationError(PROVIDER_NAME, 0, "envelope had no structured output")

    def _prompt_text(self, task: ProviderTask, repair: RepairContext | None) -> str:
        with_image = ProviderTask(
            prompt_text=(
                f"{task.prompt_text}\n\n"
                f"The design image is at this absolute path: {task.design_image}\n"
                "Use the read_file tool to view it before answering.\n"
            ),
            response_schema=task.response_schema,
            design_image=task.design_image,
        )
        return prompt_text_for(with_image, repair)

    def _write_prompt(self, prompt_text: str) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".txt",
            prefix="etsy-listings-ai-grok-",
            delete=False,
        ) as handle:
            handle.write(prompt_text)
            return Path(handle.name)
