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
    classify_process_failure,
)
from etsy_listings.ai.models import (
    Deadline,
    ProviderReadiness,
    RawProviderResult,
    RepairContext,
    SeoRequest,
)
from etsy_listings.ai.process import run_managed
from etsy_listings.ai.prompt import RESPONSE_SCHEMA, build_prompt
from etsy_listings.ai.repair import repair_prompt_suffix

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
    """The `SeoProvider` adapter for the local Claude Code CLI.

    Same shape and reasoning as `ai/codex.py.CodexProvider`: plain `Path`s
    for the workspace root and the seller's prompt file, not a `Workspace`.
    """

    workspace_root: Path
    prompt_file: Path
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

        if not self.prompt_file.is_file():
            return ProviderReadiness(
                ready=False,
                reason=f"{self.prompt_file} is missing; run `etsy-listings setup` to seed it",
            )

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
        request: SeoRequest,
        deadline: Deadline,
        *,
        repair: RepairContext | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RawProviderResult:
        prompt_text = self._build_prompt_text(request, repair)
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
            json.dumps(RESPONSE_SCHEMA),
            prompt_text,
        ]

        result = run_managed(
            argv,
            cwd=self.workspace_root,
            input_text="",
            deadline=deadline,
            cancel_event=cancel_event,
        )

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
        """Pull the final response text out of `--output-format json`'s one
        envelope. Any shape this does not recognise -- not JSON, not an
        object, ``is_error`` true, or no ``result`` string -- is a generation
        error, not an availability failure: the process itself exited 0, so
        `classify_process_failure` never runs on this path."""
        try:
            envelope: Any = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ProviderGenerationError(
                PROVIDER_NAME, 0, f"stdout was not valid JSON: {exc}"
            ) from exc
        if not isinstance(envelope, dict):
            raise ProviderGenerationError(PROVIDER_NAME, 0, "stdout was not a JSON object")
        if envelope.get("is_error"):
            raise ProviderGenerationError(
                PROVIDER_NAME, 0, str(envelope.get("result") or "claude reported is_error")
            )
        result_text = envelope.get("result")
        if not isinstance(result_text, str):
            raise ProviderGenerationError(PROVIDER_NAME, 0, "envelope had no `result` string")
        return result_text

    def _build_prompt_text(self, request: SeoRequest, repair: RepairContext | None) -> str:
        seller_prompt = self.prompt_file.read_text(encoding="utf-8")
        prompt_text = build_prompt(seller_prompt, request)
        prompt_text += (
            f"\n\nThe design image is at this absolute path: {request.design_image}\n"
            "Use the Read tool to view it before writing copy.\n"
        )
        if repair is not None:
            prompt_text = f"{prompt_text}\n\n{repair_prompt_suffix(repair)}"
        return prompt_text
