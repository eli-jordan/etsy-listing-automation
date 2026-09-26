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
- No ``--model`` is passed -- the settled "default configured CLI model"
  decision means the account's own configured model is used as-is.
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
import shutil
import subprocess
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

PROVIDER_NAME = "claude"

_READINESS_TIMEOUT_SECONDS = 15.0
"""Mirrors `ai/codex.py`'s own readiness timeout -- both probes below are
local and fast (`claude auth status`, `claude -p --help`), never a
speculative quota check."""

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
class ClaudeProvider:
    """The `AiProvider` adapter for the local Claude Code CLI.

    Same shape and reasoning as `ai/codex.py.CodexProvider`: a plain `Path`
    for the workspace root, not a `Workspace`, and no prompt file -- a task
    arrives with its prompt already assembled (`ai/models.py.ProviderTask`).
    """

    workspace_root: Path
    binary: str = "claude"

    def _resolved_binary(self) -> str:
        """The executable path `shutil.which` resolved, not the bare
        ``self.binary`` name -- see `ai/codex.py.CodexProvider._resolved_binary`
        for why: an npm-installed CLI on Windows is a shim (`claude.EXE` here,
        but a `.CMD` for other CLIs -- either way, `shutil.which`'s own
        `PATHEXT` search is what finds it, and every subprocess call needs
        that same resolved path rather than assuming the bare name is
        directly launchable without `shell=True`."""
        return shutil.which(self.binary) or self.binary

    def readiness(self) -> ProviderReadiness:
        if shutil.which(self.binary) is None:
            return ProviderReadiness(ready=False, reason=f"{self.binary} was not found on PATH")

        unavailable = self._check_authenticated()
        if unavailable is not None:
            return unavailable

        unavailable = self._check_read_only_capability()
        if unavailable is not None:
            return unavailable

        return ProviderReadiness(ready=True)

    def _check_authenticated(self) -> ProviderReadiness | None:
        try:
            result = subprocess.run(
                [self._resolved_binary(), "auth", "status"],
                capture_output=True,
                text=True,
                timeout=_READINESS_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ProviderReadiness(
                ready=False, reason=f"could not check `{self.binary} auth status`: {exc}"
            )
        if result.returncode != 0:
            return ProviderReadiness(
                ready=False,
                reason=(
                    f"{self.binary} is not authenticated "
                    f"(`{self.binary} auth status` exited {result.returncode})"
                ),
            )
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

    def _check_read_only_capability(self) -> ProviderReadiness | None:
        # Known limitation (docs/ai-seo-implementation-plan.md, PR4): this
        # only confirms `--help` advertises the required flags, not that a
        # live `-p` invocation actually honours them. Same "no speculative
        # quota check" tradeoff as the auth check above -- readiness stays a
        # local, static check rather than spending a real generation call.
        try:
            result = subprocess.run(
                [self._resolved_binary(), "-p", "--help"],
                capture_output=True,
                text=True,
                timeout=_READINESS_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ProviderReadiness(
                ready=False, reason=f"could not check `{self.binary} -p --help`: {exc}"
            )
        if result.returncode != 0:
            return ProviderReadiness(
                ready=False, reason=f"`{self.binary} -p --help` exited {result.returncode}"
            )
        missing = [flag for flag in _REQUIRED_HELP_FLAGS if flag not in result.stdout]
        if missing:
            return ProviderReadiness(
                ready=False,
                reason=(
                    f"the installed {self.binary} CLI does not support the required "
                    f"read-only/no-session flags: {', '.join(missing)}"
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
            # Recognised-unavailable, so the orchestrator moves on to the next
            # provider. Launching the bare name would fail with WinError 2 --
            # a process error, which ends the run instead -- and readiness
            # only needs *one* provider to be ready, so on a machine with
            # just the other CLI this is the ordinary case, not an edge.
            raise ProviderUnavailableError(PROVIDER_NAME, f"{self.binary} was not found on PATH")
        prompt_text = self._prompt_text(task, repair)
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

        result = run_managed(
            argv,
            cwd=self.workspace_root,
            input_text=prompt_text,
            deadline=deadline,
            cancel_event=cancel_event,
        )

        if result.cancelled:
            raise ProviderCancelledError(PROVIDER_NAME)
        if result.timed_out:
            raise ProviderTimeoutError(PROVIDER_NAME)
        if result.returncode != 0:
            # stdout may be the `--output-format json` envelope. Classification
            # reads its `result` sentence; the rest is telemetry.
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
        try:
            envelope: Any = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ProviderGenerationError(
                PROVIDER_NAME, 0, f"stdout was not valid JSON: {exc}"
            ) from exc
        if not isinstance(envelope, dict):
            raise ProviderGenerationError(PROVIDER_NAME, 0, "stdout was not a JSON object")
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
                if has_sentence or "api_error_status" in envelope
                else "claude reported is_error"
            )
            raise classify_process_failure(PROVIDER_NAME, returncode=0, stdout=reported, stderr="")
        result_text = envelope.get("result")
        if not isinstance(result_text, str):
            raise ProviderGenerationError(PROVIDER_NAME, 0, "envelope had no `result` string")
        return result_text

    def _prompt_text(self, task: ProviderTask, repair: RepairContext | None) -> str:
        """The task's prompt, plus how *this* CLI is told to look at the design.

        Codex takes the image as an argument (`-i`); `claude -p` has no
        equivalent, so the path is named in the prompt and the model reads it
        with its own read-only Read tool. That difference is the adapter's to
        know -- everything after it, including what a repair attempt resends,
        is the shared `ai/repair.py` rule.
        """
        with_image = ProviderTask(
            prompt_text=(
                f"{task.prompt_text}\n\n"
                f"The design image is at this absolute path: {task.design_image}\n"
                "Use the Read tool to view it before answering.\n"
            ),
            response_schema=task.response_schema,
            design_image=task.design_image,
        )
        return prompt_text_for(with_image, repair)
