"""Credentials, read from the *workspace's* gitignored ``.env`` -- never from
this repository (PRD: "Secrets never enter the repo"; docs/setup.md §4).

Process environment wins over the file, which is what makes a one-off
``PRINTIFY_API_TOKEN=... etsy-listings new ...`` work without editing
anything. Values are read lazily by whoever needs them, and a missing one is
reported by :class:`MissingCredentialError` naming the exact file it should be
in -- the alternative was a bare ``401 Unauthorized`` traceback out of httpx,
which tells the user nothing about what to do next.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PRINTIFY_TOKEN_VAR = "PRINTIFY_API_TOKEN"
ANTHROPIC_KEY_VAR = "ANTHROPIC_API_KEY"


class MissingCredentialError(RuntimeError):
    def __init__(self, variable: str, env_file: Path, needed_for: str, how_to_get: str) -> None:
        self.variable = variable
        super().__init__(
            f"{variable} is not set, and is required to {needed_for}.\n"
            f"  Put it in {env_file} as `{variable}=...`, or export it in your shell.\n"
            f"  {how_to_get}"
        )


class _EnvValues(BaseSettings):
    """The raw read. Separate from :class:`Secrets` so the public type stays a
    plain frozen dataclass that also remembers *which* file it read."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    printify_api_token: str | None = None
    anthropic_api_key: str | None = None


@dataclass(frozen=True)
class Secrets:
    env_file: Path
    printify_api_token: str | None = None
    anthropic_api_key: str | None = None

    @classmethod
    def load(cls, env_file: Path) -> Secrets:
        values = _EnvValues(_env_file=env_file if env_file.is_file() else None)
        return cls(
            env_file=env_file,
            printify_api_token=values.printify_api_token or None,
            anthropic_api_key=values.anthropic_api_key or None,
        )

    def require_printify_api_token(self) -> str:
        if not self.printify_api_token:
            raise MissingCredentialError(
                PRINTIFY_TOKEN_VAR,
                self.env_file,
                "read Printify's catalog (blueprints, print providers, variants)",
                "Generate a personal access token at printify.com/app/account/connections "
                "with the `catalog.read` scope -- see docs/setup.md section 1.3.",
            )
        return self.printify_api_token

    def require_anthropic_api_key(self) -> str:
        if not self.anthropic_api_key:
            raise MissingCredentialError(
                ANTHROPIC_KEY_VAR,
                self.env_file,
                "generate listing copy",
                "Create a key at console.anthropic.com -- see docs/setup.md section 4.",
            )
        return self.anthropic_api_key
