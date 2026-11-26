"""The Grok CLI adapter behind `AiProvider`: one non-interactive, read-only
generation call. Grok 1.0.41's flags, as measured:

- ``--prompt-file``: the prompt is too long for Windows' command line.
- ``--json-schema`` implies JSON output; the schema-valid object is
  ``structuredOutput`` (``text`` is only a rendering of it).
- ``--sandbox read-only`` is documented for Linux and macOS only, so on
  Windows the read-only ``--tools`` allowlist is the guarantee.
- No ``--no-session-persistence`` exists: Grok writes a session under its
  home directory even though no call resumes one.
- No image-attach flag: the prompt names the design's path for ``read_file``.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import override

# jscpd:ignore-start -- S05/S07: sharing these imports would add a re-export facade.
from etsy_listings.core.ai import cli_support
from etsy_listings.core.ai.errors import (
    ProviderGenerationError,
    classify_process_failure,
)
from etsy_listings.core.ai.models import (
    ProviderReadiness,
    RawProviderResult,
)

# jscpd:ignore-end -- dependencies stay explicit in each adapter.

PROVIDER_NAME = "grok"

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
how a read-only call wanders until its step deadline kills it."""


def auth_file() -> Path:
    """Where `grok login` stores the session; readiness only checks it is non-empty."""
    return Path.home() / ".grok" / "auth.json"


@dataclass
class GrokProvider(cli_support.LocalCliProvider):
    binary: str = "grok"
    credentials: Path | None = None
    """The session file readiness checks; ``None`` is `auth_file`'s."""
    provider_name = PROVIDER_NAME
    image_tool = "read_file"

    @override
    def _check_authenticated(self) -> ProviderReadiness | None:
        path = self.credentials or auth_file()
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

    @override
    def _check_capability(self) -> ProviderReadiness | None:
        return cli_support.check_capability(
            self.host, self.binary, ("--help",), _REQUIRED_HELP_FLAGS, "headless"
        )

    @override
    def _generate(self, invocation: cli_support.Invocation) -> RawProviderResult:
        task, prompt_text = invocation.task, invocation.prompt_text
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
        if self.model is not None:
            argv += ["--model", self.model]
        if self.effort is not None:
            argv += ["--reasoning-effort", self.effort]
        try:
            result = self.host.run_managed(
                argv,
                cwd=self.workspace_root,
                input_text="",
                deadline=invocation.deadline,
                cancel_event=invocation.cancel_event,
            )
        finally:
            prompt_path.unlink(missing_ok=True)

        cli_support.check_result(PROVIDER_NAME, result)
        return RawProviderResult(
            provider=PROVIDER_NAME, raw_output=self._extract_result_text(result.stdout)
        )

    def _extract_result_text(self, stdout: str) -> str:
        envelope = cli_support.json_object(PROVIDER_NAME, stdout)
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
