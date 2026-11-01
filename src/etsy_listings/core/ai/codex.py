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
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.ai import cli_support
from etsy_listings.core.ai.errors import (
    ProviderUnavailableError,
)
from etsy_listings.core.ai.models import (
    Deadline,
    ProviderReadiness,
    ProviderTask,
    RawProviderResult,
    RepairContext,
)
from etsy_listings.core.ai.process import run_managed
from etsy_listings.core.ai.repair import prompt_text_for

PROVIDER_NAME = "codex"

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
    process"). A plain `Path` rather than a `Workspace`, mirroring
    `ai/prompt.py.seed_default_prompt`'s own rule: the caller already knows
    how to reach `Workspace.root`.

    No prompt file: which prose a request is built from, and whether that
    file exists at all, is the *request's* business (`ai/models.py.ProviderTask`,
    ADR-0003). This adapter is only ever told "run the CLI on this text", so a
    missing `prompts/seo.md` is reported by the endpoint that needed it
    rather than as this CLI being unready.
    """

    workspace_root: Path
    binary: str = "codex"

    def _resolved_binary(self) -> str:
        """The executable path `shutil.which` resolved, not the bare
        ``self.binary`` name.

        On Windows, an npm-installed CLI like `codex` is a `.CMD` shim
        (confirmed live: `shutil.which("codex")` resolves to
        ``...\\codex.CMD``). `subprocess.run(["codex",...])` with the bare
        name and no `shell=True` fails there with `WinError 2` -- Windows
        `CreateProcess` does not search `PATHEXT` the way a shell or
        `shutil.which` does. Every subprocess call below uses this resolved
        path so the adapter works identically on Windows (this project's
        primary development platform, per `AGENTS.md`) and POSIX.
        """
        return shutil.which(self.binary) or self.binary

    def readiness(self) -> ProviderReadiness:
        return cli_support.readiness(
            self.binary, self._check_authenticated, self._check_read_only_capability
        )

    def _check_authenticated(self) -> ProviderReadiness | None:
        result = cli_support.probe(self.binary, ("login", "status"))
        if isinstance(result, ProviderReadiness):
            return result
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
        # A local help probe checks advertised flags without spending a generation call.
        return cli_support.check_capability(
            self.binary, ("exec", "--help"), _REQUIRED_EXEC_HELP_FLAGS, "read-only exec"
        )

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
        prompt_text = prompt_text_for(task, repair)
        with tempfile.TemporaryDirectory(prefix="etsy-listings-ai-codex-") as tmp:
            tmp_path = Path(tmp)
            schema_path = tmp_path / "schema.json"
            schema_path.write_text(json.dumps(dict(task.response_schema)), encoding="utf-8")
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
                str(task.design_image),
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

            cli_support.check_result(PROVIDER_NAME, result)
            raw_output = (
                last_message_path.read_text(encoding="utf-8")
                if last_message_path.is_file()
                else result.stdout
            )

        return RawProviderResult(provider=PROVIDER_NAME, raw_output=raw_output)
