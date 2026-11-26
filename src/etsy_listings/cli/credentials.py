"""Capturing one credential at the terminal: what to say, how to ask, and how
to refuse. Where a credential lives, how it is proved and how it is stored are
core's (:mod:`etsy_listings.core.application.credentials`).

:func:`capture` never writes; :func:`store` is the separate call each wizard
makes when it is right to.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import typer

from etsy_listings.cli import prompts
from etsy_listings.core.application import credentials
from etsy_listings.core.workspace import scaffold

__all__ = [
    "ANTHROPIC",
    "ETSY_APP_KEY",
    "PRINTIFY",
    "Capture",
    "CredentialPrompt",
    "VerifiedCapture",
    "announce_gitignore",
    "capture",
    "capture_verified",
    "nothing_to_prove",
    "refuse",
    "store",
]


@dataclass(frozen=True)
class CredentialPrompt:
    """How a wizard asks for one core credential: one prompt per variable."""

    credential: credentials.Credential
    asks: tuple[str, ...]
    blurb: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.asks) != len(self.variables):
            raise ValueError(f"{self.variables} needs one prompt each, got {self.asks}")

    @property
    def variables(self) -> tuple[str, ...]:
        return self.credential.variables


PRINTIFY = CredentialPrompt(
    credential=credentials.PRINTIFY,
    asks=("Printify API token:",),
    blurb=(
        "A Printify personal access token is needed to read the catalog",
        "and create products. Generate one at:",
        "  https://printify.com/app/account/api",
        "It needs the catalog, shops and products scopes.",
    ),
)

ETSY_APP_KEY = CredentialPrompt(
    credential=credentials.ETSY_APP_KEY,
    asks=("Etsy keystring:", "Etsy shared secret:"),
    blurb=(
        "Etsy identifies this application by a key *pair*, both on:",
        "  https://www.etsy.com/developers/your-apps",
        "The shared secret is hidden behind the visibility icon beside it.",
    ),
)
"""Both halves, one step. ``x-api-key`` carries them joined, so a ping cannot
say which was wrong, and asking for them separately with a verification
between would promise a precision Etsy does not offer."""

ANTHROPIC = CredentialPrompt(
    credential=credentials.ANTHROPIC,
    asks=("Anthropic API key (blank to skip):",),
    blurb=(
        "An Anthropic API key is optional; no command uses it.",
        "  https://console.anthropic.com/settings/keys",
    ),
)


@dataclass(frozen=True)
class Capture:
    values: tuple[str, ...]
    reused: bool
    """True when every value was already on this machine, so nothing was asked
    and nothing needs writing back."""

    @property
    def skipped(self) -> bool:
        return not any(value.strip() for value in self.values)


@dataclass(frozen=True)
class VerifiedCapture[T](Capture):
    proof: T


type Verify[T] = Callable[[tuple[str, ...]], tuple[T, str]]
"""Receives the values and answers ``(proof, detail)``: whatever the caller
wants back, and one line saying what was proved. A refusal goes through
:func:`refuse`."""


def capture(
    root: Path,
    prompt: CredentialPrompt,
    *,
    verify: Verify[object],
    reuse_message: str | None = None,
) -> Capture:
    """Ask for ``prompt``'s credential unless this machine already has it, and
    prove what was asked. A credential already here is left alone, unproved."""
    existing = credentials.stored_values(root, prompt.credential)
    if all(existing):
        typer.echo(reuse_message or _default_reuse_message(prompt))
        return Capture(values=_present(existing), reused=True)

    values = _ask(prompt, existing, allow_blank=prompt.credential.optional)
    if prompt.credential.optional and not any(values):
        typer.echo("  skipped.")
        return Capture(values=values, reused=False)

    _proof, detail = verify(values)
    typer.echo(f"  {detail}")
    return Capture(values=values, reused=False)


def capture_verified[T](
    root: Path,
    prompt: CredentialPrompt,
    *,
    verify: Verify[T],
    reuse_message: str | None = None,
) -> VerifiedCapture[T]:
    """:func:`capture` for a caller that needs the proof, so a credential
    already here is proved too. Blank answers are not accepted."""
    existing = credentials.stored_values(root, prompt.credential)
    if all(existing):
        typer.echo(reuse_message or _default_reuse_message(prompt))
        values = _present(existing)
        return VerifiedCapture(values=values, reused=True, proof=verify(values)[0])

    values = _ask(prompt, existing, allow_blank=False)
    proof, detail = verify(values)
    typer.echo(f"  {detail}")
    return VerifiedCapture(values=values, reused=False, proof=proof)


def _present(existing: Sequence[str | None]) -> tuple[str, ...]:
    return tuple(value for value in existing if value is not None)


def _ask(
    prompt: CredentialPrompt, existing: Sequence[str | None], *, allow_blank: bool
) -> tuple[str, ...]:
    typer.echo("")
    for line in prompt.blurb:
        typer.echo(line)

    answers: list[str] = []
    for ask, already in zip(prompt.asks, existing, strict=True):
        answers.append(already or prompts.ask_text(ask, allow_blank=allow_blank))
    return tuple(answer.strip() for answer in answers)


def store(root: Path, prompt: CredentialPrompt, capture: Capture) -> None:
    if capture.reused or capture.skipped:
        return
    credentials.store(root, prompt.credential, capture.values)


def refuse(message: str, *, command: str) -> NoReturn:
    """Report a credential that did not verify, and stop having written nothing."""
    typer.echo("", err=True)
    typer.echo(message, err=True)
    typer.echo(f"Nothing was written -- re-run `{command}` with a working credential.", err=True)
    raise typer.Exit(code=1)


def announce_gitignore(root: Path) -> None:
    if scaffold.update_gitignore(root):
        typer.echo("  wrote .gitignore (.env, .auth/ and .cache/ stay out of git)")


def _default_reuse_message(prompt: CredentialPrompt) -> str:
    named = " and ".join(prompt.variables)
    return f"{named} already set -- leaving it alone."


def nothing_to_prove(values: Sequence[str]) -> tuple[None, str]:
    """Store unverified: Anthropic has no free call that proves a key."""
    del values
    return None, "stored unverified."
