"""Capturing one credential: where it already is, how to ask, how to prove it.

``setup`` and ``auth`` both need a Printify token before they can do anything,
and both used to write the step out longhand -- the same four lines of blurb,
the same URL, the same ``prompts.ask_text`` label, the same ``.shops()``
verification, and a refusal differing from the other by one word. The Etsy key
pair and the Anthropic key are the same shape again, and Phase 4's generation
step will want the third of them.

A credential step is six things, and this module is all six of them:

1. **Where it already lives.** Environment first, then the workspace's
   ``.env`` -- the same precedence :class:`~etsy_listings.config.secrets.Secrets`
   uses, so a wizard cannot disagree with the rest of the tool about which
   credential is in play. A wizard that stores a token the next command then
   ignores is worse than one that never ran.
2. **What to say before asking.** Where to get one, and what it needs to be
   able to do.
3. **How to ask.** One prompt per variable; a key *pair* is two prompts and
   one step, because both halves ride on one header and a verification cannot
   say which of them was wrong.
4. **How to prove it.** Supplied by the caller, because the call that proves a
   credential is the call that wants it: ``setup`` verifies the Printify token
   by asking which shops it reaches, and then *needs that shop list* -- so
   verification hands back what it learned rather than a boolean.
5. **What to say when it works.** The proof, in one line.
6. **What to do when it does not.** Refuse, naming the command to re-run, and
   write nothing.

**Capturing is not storing**, and they are separate on purpose. ``auth``
writes each credential as it goes, because its parts are independent and a
working Printify token should survive abandoning the Etsy sign-in. ``setup``
writes at the very end, after every question is answered, because a token left
behind by a cancelled run is a workspace that looks configured and is not.
One order is right for each, and neither is right for both -- so this module
does not choose.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import typer

from etsy_listings import prompts
from etsy_listings.config.secrets import (
    ANTHROPIC_KEY_VAR,
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    PRINTIFY_TOKEN_VAR,
    Secrets,
)
from etsy_listings.workspace import layout, scaffold

__all__ = [
    "ANTHROPIC",
    "ETSY_APP_KEY",
    "PRINTIFY",
    "Capture",
    "Credential",
    "MissingProofError",
    "capture",
    "refuse",
    "stored",
    "store",
]


class MissingProofError(RuntimeError):
    """A caller asked for a verification's result where none was produced.

    A wiring defect rather than anything a user did: it means
    ``verify_reused=False`` was paired with a caller that needs the proof.
    """

    def __init__(self, values: tuple[str, ...]) -> None:
        super().__init__(
            f"this credential ({len(values)} value(s)) was captured without being verified, "
            f"so there is no result to hand back. Pass verify_reused=True if the caller needs one."
        )


@dataclass(frozen=True)
class Credential:
    """One credential a wizard can capture.

    ``variables`` and ``asks`` are parallel and the same length: one prompt
    per environment variable, in the order they are asked and written.
    """

    variables: tuple[str, ...]
    asks: tuple[str, ...]
    blurb: tuple[str, ...]
    allow_blank: bool = False
    """Whether an empty answer is a complete step rather than a skipped one.
    True only for a credential nothing needs yet."""


PRINTIFY = Credential(
    variables=(PRINTIFY_TOKEN_VAR,),
    asks=("Printify API token:",),
    blurb=(
        "A Printify personal access token is needed to read the catalog",
        "and create products. Generate one at:",
        "  https://printify.com/app/account/api",
        "It needs the catalog, shops and products scopes.",
    ),
)

ETSY_APP_KEY = Credential(
    variables=(ETSY_KEYSTRING_VAR, ETSY_SHARED_SECRET_VAR),
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

ANTHROPIC = Credential(
    variables=(ANTHROPIC_KEY_VAR,),
    asks=("Anthropic API key (blank to skip):",),
    blurb=(
        "An Anthropic API key generates listing copy (Phase 4; not needed yet).",
        "  https://console.anthropic.com/settings/keys",
    ),
    allow_blank=True,
)


@dataclass(frozen=True)
class Capture[T]:
    """A credential that has been answered for, and what proving it produced.

    ``values`` is parallel to the credential's ``variables``. ``proof`` is
    whatever the caller's verification handed back -- a shop list, an Etsy
    application id -- so the call that proves a credential is not a call whose
    answer is then thrown away and made again.
    """

    values: tuple[str, ...]
    proof: T | None
    """``None`` when nothing was proved -- a reused credential the caller
    chose not to re-verify, or a skipped optional one."""
    reused: bool
    """True when every value was already on this machine, so nothing was asked
    and nothing needs writing back."""

    @property
    def skipped(self) -> bool:
        """A blank answer to a credential that allows one."""
        return not any(value.strip() for value in self.values)

    def require_proof(self) -> T:
        """The proof, for a caller that asked for one and needs it typed.

        A caller passing ``verify_reused=True`` on a required credential
        always gets a proof, but the field is ``T | None`` for the callers
        that do not. This is where that narrowing happens once, rather than
        with an ``assert`` at each call site -- ``assert`` disappears under
        ``python -O``, and this must not.
        """
        if self.proof is None:
            raise MissingProofError(self.values)
        return self.proof


def stored(root: Path, variable: str) -> str | None:
    """A credential this machine already has, environment first.

    :class:`~etsy_listings.config.secrets.Secrets`' own precedence, read
    through the one accessor that knows the layout -- both wizards used to
    join ``root / layout.ENV_FILE`` for themselves.
    """
    from_env = os.environ.get(variable)
    if from_env:
        return from_env
    secrets = Secrets.load(root / layout.ENV_FILE)
    return {
        PRINTIFY_TOKEN_VAR: secrets.printify_api_token,
        ETSY_KEYSTRING_VAR: secrets.etsy_keystring,
        ETSY_SHARED_SECRET_VAR: secrets.etsy_shared_secret,
        ANTHROPIC_KEY_VAR: secrets.anthropic_api_key,
    }[variable]


def capture[T](
    root: Path,
    credential: Credential,
    *,
    verify: Callable[[tuple[str, ...]], tuple[T, str]],
    command: str,
    verify_reused: bool = True,
    reuse_message: str | None = None,
) -> Capture[T]:
    """Ask for ``credential`` unless this machine already has it, and prove it.

    ``verify`` receives the values and answers ``(proof, detail)``: whatever
    the caller wants back, and one line saying what was proved. It is the
    caller's because proving a credential means using it, and only the caller
    knows what it wanted to use it for.

    ``verify_reused`` decides whether a credential already on this machine is
    proved again, and the two commands genuinely differ. ``auth`` says no:
    "already set -- leaving it alone" is the whole of that step, and spending
    a network call to re-confirm what nobody asked about is not free. ``setup``
    says yes, because verifying the Printify token *is* asking which shops it
    reaches (PRD 42) and it needs that answer either way.

    A verification that raises is a refusal: ``command`` names what to re-run,
    and nothing is written by this function in any case -- see :func:`store`.
    """
    existing = tuple(stored(root, variable) for variable in credential.variables)
    if all(existing):
        values = tuple(value for value in existing if value is not None)
        typer.echo(reuse_message or _default_reuse_message(credential))
        proof = verify(values)[0] if verify_reused else None
        return Capture(values=values, proof=proof, reused=True)

    typer.echo("")
    for line in credential.blurb:
        typer.echo(line)

    answers: list[str] = []
    for variable, ask, already in zip(credential.variables, credential.asks, existing, strict=True):
        # A half-present pair keeps the half it has and asks only for the
        # rest, which is what makes re-running after one bad paste cheap.
        del variable
        answers.append(already or prompts.ask_text(ask, allow_blank=credential.allow_blank))

    values = tuple(answer.strip() for answer in answers)
    if credential.allow_blank and not any(values):
        typer.echo("  skipped.")
        return Capture(values=values, proof=None, reused=False)

    proof, detail = verify(values)
    typer.echo(f"  {detail}")
    return Capture(values=values, proof=proof, reused=False)


def store[T](root: Path, credential: Credential, capture: Capture[T]) -> None:
    """Write what was captured into the workspace's ``.env``.

    Separate from :func:`capture` because the two commands disagree about
    *when*, for reasons each is right about -- see this module's docstring.
    Reused and skipped captures write nothing: there is nothing new to write.
    """
    if capture.reused or capture.skipped:
        return
    for variable, value in zip(credential.variables, capture.values, strict=True):
        scaffold.write_env_value(root, variable, value)


def refuse(message: str, *, command: str) -> NoReturn:
    """Report a credential that did not verify, and stop having written nothing.

    The sentence differed by one word between the two commands, which is one
    word of difference and two places to update when the advice changes.
    """
    typer.echo("", err=True)
    typer.echo(message, err=True)
    typer.echo(f"Nothing was written -- re-run `{command}` with a working credential.", err=True)
    raise typer.Exit(code=1)


def announce_gitignore(root: Path) -> None:
    """Write the workspace's ``.gitignore`` if it needs one, and say so.

    Both wizards do this before the first secret, with the same message: a
    workspace inside an existing repository is one where a ``.env`` written a
    moment too early is already tracked (PRD 49).
    """
    if scaffold.update_gitignore(root):
        typer.echo("  wrote .gitignore (.env, .auth/ and .cache/ stay out of git)")


def _default_reuse_message(credential: Credential) -> str:
    named = " and ".join(credential.variables)
    return f"{named} already set -- leaving it alone."


def nothing_to_prove(values: Sequence[str]) -> tuple[None, str]:
    """A verification for a credential no endpoint can cheaply confirm.

    Anthropic has no free call that proves a key without spending on one, so
    the honest answer is to store it unverified rather than to invent a check.
    """
    del values
    return None, "stored unverified."
