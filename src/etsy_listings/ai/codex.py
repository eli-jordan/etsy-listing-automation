"""The Codex CLI adapter behind `SeoProvider` (AI SEO implementation plan,
PR4, items 1-4): a non-interactive `codex exec` invocation with its
read-only sandbox, ephemeral/no-session mode, structured output schema, and
the design image.

Every flag below was confirmed against the installed `codex exec --help`
(codex-cli 0.155.0) rather than guessed -- see this PR's own report for the
transcript. In particular:

- ``-s, --sandbox read-only`` is the documented read-only sandbox policy.
- ``--ephemeral`` is the documented "run without persisting session files"
  flag -- this feature's "no durable provider session" requirement.
- ``codex exec`` has no ``-a/--ask-for-approval`` option at all (confirmed:
  passing one is a clap "unexpected argument" error); `codex exec --help`
  shows a live invocation prints ``approval: never``, so exec is
  unconditionally non-interactive already -- there is nothing to configure
  for "automatic tool approval inside read-only mode".
- ``--output-schema <FILE>`` takes a JSON Schema *file*, not inline JSON, and
  ``-o, --output-last-message <FILE>`` writes the final agent message to a
  file -- confirmed live, this is a clean, reliable way to capture the
  structured response text instead of scraping the human-readable transcript
  `codex exec` prints to stdout.
- The prompt is sent over stdin with ``-`` as the PROMPT argument (confirmed
  live) rather than as a trailing argv element, so an unusually long prompt
  (seller text plus delimited JSON context and schema) never risks a
  platform argv-length limit.
- No ``-m/--model`` is passed -- the settled "default configured CLI model"
  decision means the account's own configured model is used as-is.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.ai.errors import (
    ProviderCancelledError,
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

PROVIDER_NAME = "codex"

_READINESS_TIMEOUT_SECONDS = 15.0
"""A ceiling for the two readiness probes (`codex login status`, `codex exec
--help`) -- both are local, fast commands that talk to no remote quota
endpoint (implementation plan: "Readiness needs no speculative quota
check"), so this only guards against a genuinely hung executable."""

_REQUIRED_EXEC_HELP_FLAGS: tuple[str, ...] = (
    "--sandbox",
    "read-only",
    "--ephemeral",
    "--output-schema",
    "--output-last-message",
)
"""Confirmed-real `codex exec` flags this adapter depends on. Checked
against the installed CLI's own `--help` text at readiness time rather than
assumed from a version number, so an older `codex` that cannot honour the
read-only guarantee is reported unready rather than silently launched
writable (implementation plan, "Provider adapters")."""


@dataclass
class CodexProvider:
    """The `SeoProvider` adapter for the local Codex CLI.

    ``workspace_root`` is the real workspace directory `codex exec` is
    launched in (`-C`, and the child process's cwd) -- the plan's "agreed
    readable scope": full read access to the workspace tree, deliberately
    including readable secrets and caches (implementation plan, "Provider
    process"). ``prompt_file`` is the seller's `prompts/seo.md`, read fresh
    on every call. Both are plain `Path`s rather than a `Workspace`, mirroring
    `ai/prompt.py.seed_default_prompt`'s own rule: the caller already knows
    how to reach `Workspace.root` and `Workspace.seo_prompt_file()`.
    """

    workspace_root: Path
    prompt_file: Path
    binary: str = "codex"

    def _resolved_binary(self) -> str:
        """The executable path `shutil.which` resolved, not the bare
        ``self.binary`` name.

        On Windows, an npm-installed CLI like `codex` is a `.CMD` shim
        (confirmed live: `shutil.which("codex")` resolves to
        ``...\\codex.CMD``). `subprocess.run(["codex", ...])` with the bare
        name and no `shell=True` fails there with `WinError 2` -- Windows
        `CreateProcess` does not search `PATHEXT` the way a shell or
        `shutil.which` does. Every subprocess call below uses this resolved
        path so the adapter works identically on Windows (this project's
        primary development platform, per `AGENTS.md`) and POSIX.
        """
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
                [self._resolved_binary(), "login", "status"],
                capture_output=True,
                text=True,
                timeout=_READINESS_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ProviderReadiness(
                ready=False, reason=f"could not check `{self.binary} login status`: {exc}"
            )
        if result.returncode != 0:
            return ProviderReadiness(
                ready=False,
                reason=(
                    f"{self.binary} is not authenticated "
                    f"(`{self.binary} login status` exited {result.returncode})"
                ),
            )
        return None

    def _check_read_only_capability(self) -> ProviderReadiness | None:
        # Known limitation (docs/ai-seo-implementation-plan.md, PR4): this
        # only confirms `--help` advertises the required flags, not that a
        # live `exec` invocation actually honours them. Same "no speculative
        # quota check" tradeoff as the auth check above -- readiness stays a
        # local, static check rather than spending a real generation call.
        try:
            result = subprocess.run(
                [self._resolved_binary(), "exec", "--help"],
                capture_output=True,
                text=True,
                timeout=_READINESS_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ProviderReadiness(
                ready=False, reason=f"could not check `{self.binary} exec --help`: {exc}"
            )
        if result.returncode != 0:
            return ProviderReadiness(
                ready=False, reason=f"`{self.binary} exec --help` exited {result.returncode}"
            )
        missing = [flag for flag in _REQUIRED_EXEC_HELP_FLAGS if flag not in result.stdout]
        if missing:
            return ProviderReadiness(
                ready=False,
                reason=(
                    f"the installed {self.binary} CLI does not support the required "
                    f"read-only exec flags: {', '.join(missing)}"
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
        with tempfile.TemporaryDirectory(prefix="etsy-listings-ai-codex-") as tmp:
            tmp_path = Path(tmp)
            schema_path = tmp_path / "schema.json"
            schema_path.write_text(json.dumps(RESPONSE_SCHEMA), encoding="utf-8")
            last_message_path = tmp_path / "last-message.json"

            argv = [
                self._resolved_binary(),
                "exec",
                "-s",
                "read-only",
                "--ephemeral",
                "--skip-git-repo-check",
                "-C",
                str(self.workspace_root),
                "-i",
                str(request.design_image),
                "--output-schema",
                str(schema_path),
                "-o",
                str(last_message_path),
                "--color",
                "never",
                "-",
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
                raise classify_process_failure(
                    PROVIDER_NAME,
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            raw_output = (
                last_message_path.read_text(encoding="utf-8")
                if last_message_path.is_file()
                else result.stdout
            )

        return RawProviderResult(provider=PROVIDER_NAME, raw_output=raw_output)

    def _build_prompt_text(self, request: SeoRequest, repair: RepairContext | None) -> str:
        seller_prompt = self.prompt_file.read_text(encoding="utf-8")
        prompt_text = build_prompt(seller_prompt, request)
        if repair is not None:
            prompt_text = f"{prompt_text}\n\n{repair_prompt_suffix(repair)}"
        return prompt_text
