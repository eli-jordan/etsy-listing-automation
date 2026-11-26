"""The Codex CLI adapter behind ``AiProvider``; docs/architecture.md, *AI provider
CLI flags*, gives each flag's reason."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import override

from etsy_listings.core.ai import cli_support
from etsy_listings.core.ai.models import (
    ProviderReadiness,
    RawProviderResult,
)

PROVIDER_NAME = "codex"

_REQUIRED_EXEC_HELP_FLAGS: tuple[str, ...] = (
    "--sandbox",
    "read-only",
    "--ephemeral",
    "--output-schema",
    "--output-last-message",
)
"""The `codex exec` flags this adapter depends on, checked against the
installed CLI's `--help` at readiness time: an older `codex` that cannot honour
the read-only guarantee is reported unready rather than launched writable."""


@dataclass
class CodexProvider(cli_support.LocalCliProvider):
    """``workspace_root`` is the real workspace directory `codex exec` is
    launched in (`-C`, and the child process's cwd): full read access to the
    workspace tree, deliberately including readable secrets and caches.
    """

    binary: str = "codex"
    provider_name = PROVIDER_NAME

    @override
    def _check_authenticated(self) -> ProviderReadiness | None:
        result = cli_support.auth_probe(self.host, self.binary, "login")
        if isinstance(result, ProviderReadiness):
            return result
        return None

    @override
    def _check_capability(self) -> ProviderReadiness | None:
        return cli_support.check_capability(
            self.host, self.binary, ("exec", "--help"), _REQUIRED_EXEC_HELP_FLAGS, "read-only exec"
        )

    @override
    def _generate(self, invocation: cli_support.Invocation) -> RawProviderResult:
        task, prompt_text = invocation.task, invocation.prompt_text
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

            if self.model is not None:
                argv += ["--model", self.model]
            if self.effort is not None:
                argv += ["-c", f"model_reasoning_effort={json.dumps(self.effort)}"]

            result = self.host.run_managed(
                argv,
                cwd=self.workspace_root,
                input_text=prompt_text,
                deadline=invocation.deadline,
                cancel_event=invocation.cancel_event,
            )

            cli_support.check_result(PROVIDER_NAME, result)
            raw_output = (
                last_message_path.read_text(encoding="utf-8")
                if last_message_path.is_file()
                else result.stdout
            )

        return RawProviderResult(provider=PROVIDER_NAME, raw_output=raw_output)
