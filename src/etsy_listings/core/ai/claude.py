"""The Claude Code CLI adapter behind ``AiProvider``; docs/architecture.md, *AI
provider CLI flags*, gives each flag's reason."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, override

from etsy_listings.core.ai import cli_support
from etsy_listings.core.ai.errors import (
    ProviderGenerationError,
    classify_process_failure,
)
from etsy_listings.core.ai.models import (
    ProviderReadiness,
    RawProviderResult,
)

PROVIDER_NAME = "claude"

_READ_ONLY_TOOLS = "Read,Grep,Glob"
"""The complete allowed-tool set for a generation call: no write tool and no
Bash, which, not a permission mode, is what makes the process read-only."""

_REQUIRED_HELP_FLAGS: tuple[str, ...] = (
    "--tools",
    "--no-session-persistence",
    "--permission-mode",
    "--permission-prompts",
    "--json-schema",
    "--output-format",
)
"""The `claude -p` flags this adapter depends on, checked against the
installed CLI's `--help` at readiness time: an older `claude` missing one is
reported unready rather than launched."""


@dataclass
class ClaudeProvider(cli_support.LocalCliProvider):
    binary: str = "claude"
    provider_name = PROVIDER_NAME
    image_tool = "Read"

    @override
    def _check_authenticated(self) -> ProviderReadiness | None:
        result = cli_support.auth_probe(self.host, self.binary, "auth")
        if isinstance(result, ProviderReadiness):
            return result
        try:
            status: Any = json.loads(result.stdout)
        except json.JSONDecodeError:
            return ProviderReadiness(
                ready=False,
                reason=f"`{self.binary} auth status` did not return valid JSON",
            )
        if not isinstance(status, dict) or not status.get("loggedIn"):
            return ProviderReadiness(ready=False, reason=f"{self.binary} is not authenticated")
        return None

    @override
    def _check_capability(self) -> ProviderReadiness | None:
        return cli_support.check_capability(
            self.host, self.binary, ("-p", "--help"), _REQUIRED_HELP_FLAGS, "read-only/no-session"
        )

    @override
    def _generate(self, invocation: cli_support.Invocation) -> RawProviderResult:
        task, prompt_text = invocation.task, invocation.prompt_text
        argv = [
            self._resolved_binary(),
            "-p",
            "--output-format",
            "json",
            "--no-session-persistence",
            "--tools",
            _READ_ONLY_TOOLS,
            "--permission-mode",
            "dontAsk",
            "--permission-prompts",
            "none",
            "--json-schema",
            json.dumps(dict(task.response_schema)),
        ]

        if self.model is not None:
            argv += ["--model", self.model]
        if self.effort is not None:
            argv += ["--effort", self.effort]

        result = self.host.run_managed(
            argv,
            cwd=self.workspace_root,
            input_text=prompt_text,
            deadline=invocation.deadline,
            cancel_event=invocation.cancel_event,
        )

        cli_support.check_result(PROVIDER_NAME, result)
        return RawProviderResult(
            provider=PROVIDER_NAME, raw_output=self._extract_result_text(result.stdout)
        )

    def _extract_result_text(self, stdout: str) -> str:
        """Pull the final response text out of `--output-format json`'s one
        envelope; an unrecognised shape is a generation error. Claude reports
        auth and quota failures as ``is_error: true`` with exit code 0, so that
        whole envelope is classified like a failed exit."""
        envelope = cli_support.json_object(PROVIDER_NAME, stdout)
        if envelope.get("is_error"):
            has_sentence = any(
                isinstance(envelope.get(key), str) and envelope[key].strip()
                for key in ("result", "message")
            )
            reported = (
                stdout
                if has_sentence or "api_error_status" in envelope or "error" in envelope
                else "claude reported is_error"
            )
            raise classify_process_failure(PROVIDER_NAME, returncode=0, stdout=reported, stderr="")
        result_text = envelope.get("result")
        if not isinstance(result_text, str):
            raise ProviderGenerationError(PROVIDER_NAME, 0, "envelope had no `result` string")
        return result_text
