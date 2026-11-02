"""The Claude Code CLI adapter behind `SeoProvider` (AI SEO implementation
plan, PR4, items 1-4): the corresponding `claude -p`, JSON schema,
no-session-persistence, and read-only non-interactive controls supported by
the installed version.

Every flag below was confirmed against the installed `claude -p --help`
(Claude Code 2.1.273) rather than guessed -- see this PR's own report for the
transcript. In particular:

- ``--no-session-persistence`` is the documented "sessions will not be saved
  to disk and cannot be resumed" flag -- this feature's own words for "no
  durable provider session", confirmed as a `--print`-only option.
- ``--tools Read,Grep,Glob`` is the read-only guarantee itself: Write, Edit,
  NotebookEdit and Bash are simply not in the allowed-tool set, so nothing
  the model does can write to the workspace regardless of permission mode --
  "the feature must not silently launch a writable process" is met by the
  tool never being offered, not by trusting a permission prompt to refuse it.
- ``--permission-mode dontAsk`` plus ``--permission-prompts none`` is
  defence in depth for "automatic tool approval inside read-only mode":
  since only read tools are offered, nothing should ever prompt, but if
  something unexpected tried to, this denies it automatically rather than
  hanging a non-interactive process waiting for a human.
- ``--json-schema <schema>`` takes the schema inline as a JSON string
  (confirmed live: `--json-schema '{"type":"object",...}'` produced a
  ``structured_output`` field alongside a ``result`` string matching it) --
  unlike Codex's ``--output-schema``, there is no file-based form.
- ``--output-format json`` wraps the run in one JSON envelope on stdout --
  confirmed live shape: ``{"type": "result", "is_error": bool, "result":
  "<final text>", ...}``. ``result`` is what this adapter treats as the raw
  provider output; ``is_error`` is checked before trusting it.
- No ``--add-dir`` is passed: the child's cwd is already ``workspace_root``,
  which is what a non-interactive `-p` session reads from by default.
- ADR-0056: explicit preferences use ``--model`` and ``--effort``; omitted
  preferences leave the account defaults in effect.
- Claude has no documented direct "attach an image" flag the way Codex's
  ``-i/--image`` is. The design image's absolute path is named in the prompt
  text instead, asking the model to open it with the (still available)
  ``Read`` tool, which supports image files.
- The prompt is sent over stdin, with no positional ``prompt`` argument on
  the argv (confirmed live: `echo '<prompt>' | claude -p ...` with no
  trailing prompt argument returns the same result a positional one would),
  mirroring `ai/codex.py`'s own reasoning -- so an unusually long prompt
  (Claude's especially, since `build_prompt` echoes the full response schema
  a second time on top of the already-inline ``--json-schema`` argument)
  never risks a platform argv-length limit (Windows' ~32K command-line
  limit).
"""

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
"""The complete allowed-tool set for a generation call. Write, Edit,
NotebookEdit and Bash are deliberately absent -- see this module's docstring
for why that, not a permission mode, is what makes the process read-only."""

_REQUIRED_HELP_FLAGS: tuple[str, ...] = (
    "--tools",
    "--no-session-persistence",
    "--permission-mode",
    "--permission-prompts",
    "--json-schema",
    "--output-format",
)
"""Confirmed-real `claude -p` flags this adapter depends on, checked against
the installed CLI's own `--help` text at readiness time -- an older `claude`
missing any of these cannot honour the read-only/no-session contract, so it
is reported unready rather than launched anyway."""


@dataclass
class ClaudeProvider(cli_support.LocalCliProvider):
    """The `AiProvider` adapter for the local Claude Code CLI.

    Same shape and reasoning as `ai/codex.py.CodexProvider`: a plain `Path`
    for the workspace root, not a `Workspace`, and no prompt file -- a task
    arrives with its prompt already assembled (`ai/models.py.ProviderTask`).
    """

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
        # A local help probe checks advertised flags without spending a generation call.
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
        envelope. Any shape this does not recognise -- not JSON, not an
        object, or no ``result`` string -- is a generation error, not an
        availability failure: the process itself exited 0, so
        `classify_process_failure` never runs on that path.

        An ``is_error: true`` envelope is different: the CLI can report an
        auth/quota/rate-limit failure this way, with exit code 0, so the raw
        envelope is routed through the same `classify_process_failure` an
        exit-code failure already goes through above. Passing the envelope
        rather than only its ``result`` string keeps ``api_error_status``
        visible -- an availability failure must be recognised as one
        regardless of which of the two shapes carried it."""
        envelope = cli_support.json_object(PROVIDER_NAME, stdout)
        if envelope.get("is_error"):
            # No sentence and no status: the old fixed line, so a bare
            # `is_error` doesn't surface the envelope. A status with no
            # sentence still goes through as the envelope, which is what
            # makes `api_error_status` 429 readable as "HTTP 429".
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
