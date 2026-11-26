"""Credentials from the workspace's gitignored ``.env`` (ADR-0025); the process
environment wins over the file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict

from etsy_listings.core.errors import UserFacingError

PRINTIFY_TOKEN_VAR = "PRINTIFY_API_TOKEN"
ETSY_KEYSTRING_VAR = "ETSY_KEYSTRING"
ETSY_SHARED_SECRET_VAR = "ETSY_SHARED_SECRET"
"""Etsy's app key is a *pair*, and both halves are required on every v3
request -- `x-api-key: <keystring>:<shared_secret>`. Two variables rather than
one pre-joined string, because they are two values on two lines of Etsy's app
page and a user pasting them should not have to assemble anything."""
BACKUP_PASSWORD_VAR = "ETSY_LISTINGS_BACKUP_PASSWORD"
"""The restic repository's password (workspace-backup spec, *Configuration*).
The workspace ``.env`` holds the only copy on this machine; the seller keeps
another in a password manager, because the ``.env`` inside a backup is
encrypted with it."""


class MissingCredentialError(UserFacingError):
    """A credential this run needs is not set anywhere.

    A :class:`~etsy_listings.core.errors.UserFacingError`, because the message
    below *is* the whole useful output -- it names the variable, the file and
    the way to get one. Typed as anything else it reaches ``--all`` as a
    traceback that ends the batch on its first unconfigured listing, which is
    the outcome continue-on-error exists to prevent.
    """

    def __init__(self, variable: str, env_file: Path, needed_for: str, how_to_get: str) -> None:
        self.variable = variable
        super().__init__(
            f"{variable} is not set, and is required to {needed_for}.\n"
            f"  Put it in {env_file} as `{variable}=...`, or export it in your shell.\n"
            f"  {how_to_get}"
        )


class _EnvValues(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    printify_api_token: str | None = None
    etsy_keystring: str | None = None
    etsy_shared_secret: str | None = None


def _backup_password(env_file: Path) -> str | None:
    override = os.environ.get(BACKUP_PASSWORD_VAR)
    if override or not env_file.is_file():
        return override or None
    # dotenv would expand a literal ${...} in the password.
    values = dotenv_values(env_file, interpolate=False, encoding="utf-8")
    folded = {key.upper(): value for key, value in values.items()}
    return folded.get(BACKUP_PASSWORD_VAR) or None


@dataclass(frozen=True)
class EtsyAppKey:
    keystring: str
    shared_secret: str

    def header(self) -> str:
        return f"{self.keystring}:{self.shared_secret}"


@dataclass(frozen=True)
class Secrets:
    env_file: Path
    printify_api_token: str | None = None
    etsy_keystring: str | None = None
    etsy_shared_secret: str | None = None
    backup_password: str | None = field(default=None, repr=False)
    """Kept out of ``repr`` so a logged or traced ``Secrets`` never shows it."""

    @classmethod
    def load(cls, env_file: Path) -> Secrets:
        values = _EnvValues(_env_file=env_file if env_file.is_file() else None)
        return cls(
            env_file=env_file,
            printify_api_token=values.printify_api_token or None,
            etsy_keystring=values.etsy_keystring or None,
            etsy_shared_secret=values.etsy_shared_secret or None,
            backup_password=_backup_password(env_file),
        )

    def require_printify_api_token(self) -> str:
        if not self.printify_api_token:
            raise MissingCredentialError(
                PRINTIFY_TOKEN_VAR,
                self.env_file,
                "read Printify's catalog (blueprints, print providers, variants)",
                "Generate a personal access token at printify.com/app/account/connections "
                "with the `catalog.read` scope -- see docs/guides/setup.md.",
            )
        return self.printify_api_token

    def require_etsy_app_key(self) -> EtsyAppKey:
        keystring = self._require_etsy_half(ETSY_KEYSTRING_VAR, self.etsy_keystring)
        shared_secret = self._require_etsy_half(ETSY_SHARED_SECRET_VAR, self.etsy_shared_secret)
        return EtsyAppKey(keystring, shared_secret)

    def _require_etsy_half(self, variable: str, value: str | None) -> str:
        if not value:
            raise MissingCredentialError(
                variable,
                self.env_file,
                "identify this application to Etsy (every v3 request carries it)",
                "Both halves are on your app's page at "
                "etsy.com/developers/your-apps -- the shared secret behind the "
                "visibility icon. `etsy-listings auth` captures and verifies them.",
            )
        return value

    def require_backup_password(self) -> str:
        if not self.backup_password:
            raise MissingCredentialError(
                BACKUP_PASSWORD_VAR,
                self.env_file,
                "open the backup repository",
                "`etsy-listings backup init` asks for one and stores it; keep a copy in "
                "a password manager.",
            )
        return self.backup_password
