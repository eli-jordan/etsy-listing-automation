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
ETSY_KEYSTRING_VAR = "ETSY_KEYSTRING"
ETSY_SHARED_SECRET_VAR = "ETSY_SHARED_SECRET"
"""Etsy's app key is a *pair*, and both halves are required on every v3
request -- `x-api-key: <keystring>:<shared_secret>`. Two variables rather than
one pre-joined string, because they are two values on two lines of Etsy's app
page and a user pasting them should not have to assemble anything (PRD 49)."""


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
    etsy_keystring: str | None = None
    etsy_shared_secret: str | None = None


@dataclass(frozen=True)
class EtsyAppKey:
    """The two halves of Etsy's app key, and the one place they are joined.

    A pair rather than a pre-joined string because they are stored, asked for
    and verified separately; :meth:`header` is the only spelling of the colon,
    so a request that omits the shared secret cannot be written by accident.
    """

    keystring: str
    shared_secret: str

    def header(self) -> str:
        return f"{self.keystring}:{self.shared_secret}"


@dataclass(frozen=True)
class Secrets:
    env_file: Path
    printify_api_token: str | None = None
    anthropic_api_key: str | None = None
    etsy_keystring: str | None = None
    etsy_shared_secret: str | None = None

    @classmethod
    def load(cls, env_file: Path) -> Secrets:
        values = _EnvValues(_env_file=env_file if env_file.is_file() else None)
        return cls(
            env_file=env_file,
            printify_api_token=values.printify_api_token or None,
            anthropic_api_key=values.anthropic_api_key or None,
            etsy_keystring=values.etsy_keystring or None,
            etsy_shared_secret=values.etsy_shared_secret or None,
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

    def require_etsy_app_key(self) -> EtsyAppKey:
        """Both halves, or a message naming the half that is missing.

        Reported one variable at a time on purpose: "the Etsy app key is
        missing" sends a user who pasted the keystring back to a page where
        the keystring is plainly present, and the shared secret sits behind a
        visibility toggle they may never have clicked.
        """
        for variable, value in (
            (ETSY_KEYSTRING_VAR, self.etsy_keystring),
            (ETSY_SHARED_SECRET_VAR, self.etsy_shared_secret),
        ):
            if not value:
                raise MissingCredentialError(
                    variable,
                    self.env_file,
                    "identify this application to Etsy (every v3 request carries it)",
                    "Both halves are on your app's page at "
                    "etsy.com/developers/your-apps -- the shared secret behind the "
                    "visibility icon. `etsy-listings auth` captures and verifies them.",
                )
        # Narrowing for mypy: the loop above proved both are non-empty.
        assert self.etsy_keystring is not None
        assert self.etsy_shared_secret is not None
        return EtsyAppKey(self.etsy_keystring, self.etsy_shared_secret)

    def require_anthropic_api_key(self) -> str:
        if not self.anthropic_api_key:
            raise MissingCredentialError(
                ANTHROPIC_KEY_VAR,
                self.env_file,
                "generate listing copy",
                "Create a key at console.anthropic.com -- see docs/setup.md section 4.",
            )
        return self.anthropic_api_key
