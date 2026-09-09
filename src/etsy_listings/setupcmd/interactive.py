"""Sequencing the questions ``setup`` asks, and doing the I/O it decides on.

Every decision lives in :mod:`etsy_listings.setupcmd.logic`; this module only
orders the questions and writes files. Questions go through
:mod:`etsy_listings.prompts` rather than questionary directly, because
questionary cannot prompt at all under cygwin (see that module).

Two orderings matter and are not arbitrary:

- **The token is verified before anything is written.** A wizard that stores
  a bad credential and fails three steps later has produced a workspace that
  looks configured and is not, which is worse than failing at the question.
- **``shop.yaml`` is written last.** It is the file that makes a directory a
  workspace, so writing it means "this worked". A run cancelled halfway
  leaves directories and a ``.gitignore``, which are harmless, and no
  ``shop.yaml``, so nothing downstream mistakes the attempt for a workspace.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
import yaml

from etsy_listings import prompts
from etsy_listings.clients.printify import HttpPrintifyClient, PrintifyAuthError, Transport
from etsy_listings.clients.printify.models import Shop
from etsy_listings.clients.printify.protocol import PrintifyClient
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR, Secrets
from etsy_listings.setupcmd import logic
from etsy_listings.workspace import layout, scaffold

ClientFactory = Callable[[str], PrintifyClient]
"""Builds a client from a *candidate* token. Injected rather than imported so
the verification step -- the one thing `setup` exists to do that reading the
docs does not -- can be driven without a network."""

WHO_MADE = ["i_did", "someone_else", "collective"]
WHEN_MADE = ["made_to_order", "2020_2025", "2010_2019", "before_2004"]
RENEWAL = ["manual", "auto"]

POD_DEFAULTS = {
    "who_made": "i_did",
    "when_made": "made_to_order",
    "is_supply": False,
    "renewal": "manual",
}
"""What every print-on-demand t-shirt listing answers. Offered as one
confirmation rather than four questions, because getting four identical
answers out of the user teaches them the wizard is not worth reading."""


def _default_client_factory(token: str) -> PrintifyClient:
    return HttpPrintifyClient(Transport(token))


def _existing_token(root: Path) -> str | None:
    """A token this machine already has, from the environment or the
    workspace's ``.env`` -- the same precedence :class:`Secrets` uses, so
    ``setup`` cannot disagree with the rest of the tool about which token is
    in play."""
    from_env = os.environ.get(PRINTIFY_TOKEN_VAR)
    if from_env:
        return from_env
    return Secrets.load(root / layout.ENV_FILE).printify_api_token


def _verified_token(root: Path, factory: ClientFactory) -> tuple[str, list[Shop]]:
    """A token that has actually answered ``GET /v1/shops.json``, and what it
    answered.

    The shop list comes back from the same call rather than being fetched
    again: verifying the token *is* asking which shops it can reach (PRD 42),
    and a second call would only invite the two answers to disagree.
    """
    token = _existing_token(root)
    if token:
        typer.echo(f"Using the {PRINTIFY_TOKEN_VAR} this machine already has.")
    else:
        typer.echo("")
        typer.echo("A Printify personal access token is needed to read the catalog")
        typer.echo("and create products. Generate one at:")
        typer.echo("  https://printify.com/app/account/connections")
        typer.echo("It needs the catalog, shops and products scopes.")
        token = prompts.ask_text("Printify API token:")

    try:
        shops = factory(token).shops()
    except PrintifyAuthError as exc:
        typer.echo("", err=True)
        typer.echo(str(exc), err=True)
        typer.echo("Nothing was written -- re-run `setup` with a working token.", err=True)
        raise typer.Exit(code=1) from exc

    return token, shops


def _pick_shop(shops: list[Shop]) -> Shop:
    selection = logic.select_shop(shops)
    if selection.problem is not None:
        typer.echo(f"{selection.problem}", err=True)
        raise typer.Exit(code=1)
    if selection.shop is not None:
        typer.echo(f"Printify shop: {selection.shop.title} ({selection.shop.id})")
        return selection.shop

    return prompts.pick(
        "Which Printify shop?", shops, label=lambda shop: f"{shop.title}  ({shop.id})"
    )


def _ask_etsy_defaults() -> dict[str, Any]:
    summary = ", ".join(f"{key}: {value}" for key, value in POD_DEFAULTS.items())
    if prompts.ask_confirm(f"Use the print-on-demand defaults for Etsy? ({summary})", default=True):
        return dict(POD_DEFAULTS)

    return {
        "who_made": prompts.ask_choice("Who made the item?", WHO_MADE),
        "when_made": prompts.ask_choice("When was it made?", WHEN_MADE),
        "is_supply": prompts.ask_confirm("Is it a craft supply rather than a finished item?"),
        "renewal": prompts.ask_choice("Listing renewal policy?", RENEWAL),
    }


def _ask_etsy_shop_id(current: object) -> int | None:
    """Blank is a real answer: this project had no Etsy shop when `setup` was
    written, and a wizard that demands the id anyway gets a made-up one.

    Seeded with whatever the file already says, so a re-run keeps it without
    the user having to retype an eight-digit number they do not have to hand.
    """
    default = str(current) if isinstance(current, int) else ""
    while True:
        answer = prompts.ask_text(
            "Etsy shop id (blank if you do not have one yet):",
            default=default,
            allow_blank=True,
        )
        if not answer.strip():
            return None
        if answer.strip().isdigit():
            return int(answer.strip())
        typer.echo("  that is not a number -- it is the numeric id, not the shop's name")


def _existing_document(root: Path) -> dict[str, Any] | None:
    """The current ``shop.yaml`` as a raw mapping, or ``None``.

    Raw rather than a parsed :class:`Defaults`: a workspace whose file does not
    validate is exactly the one `setup` should be able to repair, and parsing
    it first would refuse the job.
    """
    path = root / layout.SHOP_FILE
    if not path.is_file():
        return None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def run_setup(root: Path, *, client_factory: ClientFactory | None = None) -> None:
    factory = client_factory or _default_client_factory
    root.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Setting up a workspace in {root}")

    created = logic.create_directories(root)
    typer.echo(
        f"  created {len(created)} directories" if created else "  directories already in place"
    )
    if scaffold.update_gitignore(root):
        typer.echo("  wrote .gitignore (.env, .auth/ and .cache/ stay out of git)")

    token, shops = _verified_token(root, factory)
    shop = _pick_shop(shops)

    # Every prompt is seeded from the file, which is what makes "the answer
    # wins" safe on a re-run: pressing enter through the whole wizard changes
    # nothing, and typing something different is taken at face value.
    existing = _existing_document(root) or {}
    existing_etsy = existing.get("etsy") or {}

    currency = prompts.ask_text(
        "Shop currency (ISO code, e.g. NOK):", default=str(existing.get("currency") or "NOK")
    )
    provider = prompts.ask_text(
        "Preferred print provider (blank for none):",
        default=str(existing.get("preferred_print_provider") or ""),
        allow_blank=True,
    )

    etsy_shop_id = _ask_etsy_shop_id(existing_etsy.get("shop_id"))
    etsy = _ask_etsy_defaults()

    answers = logic.SetupAnswers(
        printify_shop_id=shop.id,
        currency=currency.strip().upper(),
        preferred_print_provider=provider.strip() or None,
        etsy_shop_id=etsy_shop_id,
        **etsy,
    )

    # Every question is answered, so the credential is worth keeping: writing
    # it earlier would leave a token behind after a cancelled run.
    scaffold.write_env_value(root, PRINTIFY_TOKEN_VAR, token)

    document = logic.shop_yaml_document(answers, existing)
    (root / layout.SHOP_FILE).write_text(logic.render_shop_yaml(document), encoding="utf-8")

    _report_next_steps(root, shop)


def _report_next_steps(root: Path, shop: Shop) -> None:
    typer.echo("")
    typer.echo(f"Workspace ready at {root}")
    typer.echo(f"  Printify shop  {shop.title} ({shop.id})")
    typer.echo(f"  shop.yaml      {layout.SHOP_FILE}")
    typer.echo(f"  credentials    {layout.ENV_FILE} (gitignored)")
    typer.echo("")
    typer.echo("Next: drop a design in designs/, then run `etsy-listings new`.")
    typer.echo("")
    if not shop.is_connected:
        typer.echo(
            f"Note: this Printify shop is not connected to a sales channel "
            f"({shop.sales_channel or 'none'}), so nothing can be published to Etsy from it yet."
        )
    typer.echo(
        "Etsy sign-in is not part of setup: it arrives with `auth` in Phase 3, "
        "along with publishing. Everything up to that point works now."
    )
