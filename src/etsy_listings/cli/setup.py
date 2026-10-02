"""The ``setup`` wizard: an empty directory in, a workspace ``new`` can run
in out.

This module orders the questions and says what happened. What a workspace
needs and how ``shop.yaml`` is merged and written is
:mod:`etsy_listings.core.application.workspace_setup`'s; finding the shops is
:mod:`~etsy_listings.core.application.shop_discovery`'s; proving the token is
:mod:`~etsy_listings.core.application.credentials`'. Questions go through
:mod:`etsy_listings.cli.prompts` rather than questionary directly, because
questionary cannot prompt at all under cygwin (see that module).

The one rule that shapes it: **`setup` fills gaps, it does not correct
answers.** Re-running it on a configured workspace must be safe, so every
prompt is seeded from the file. Two orderings matter and are not arbitrary:

- **The token is verified before anything is written.** A wizard that stores
  a bad credential and fails three steps later has produced a workspace that
  looks configured and is not, which is worse than failing at the question.
- **The token and ``shop.yaml`` are written last.** ``shop.yaml`` is the file
  that makes a directory a workspace, so writing it means "this worked". A
  run cancelled halfway leaves directories, prompts and a ``.gitignore``,
  which are harmless, and no token or ``shop.yaml``, so nothing downstream
  mistakes the attempt for a workspace.

:func:`run_setup` is the interface.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from etsy_listings.cli import credentials, prompts
from etsy_listings.core import connections
from etsy_listings.core.application import credentials as core_credentials
from etsy_listings.core.application import shop_discovery, workspace_setup
from etsy_listings.core.application.shop_discovery import EtsyAccess
from etsy_listings.core.clients.etsy.models import ReturnPolicy
from etsy_listings.core.clients.etsy.models import Shop as EtsyShop
from etsy_listings.core.clients.etsy.tokens import EtsyAuthError
from etsy_listings.core.clients.etsy.transport import EtsyApiError
from etsy_listings.core.clients.printify import PrintifyAuthError
from etsy_listings.core.clients.printify.models import Shop
from etsy_listings.core.clients.printify.protocol import PrintifyClient
from etsy_listings.core.config.secrets import PRINTIFY_TOKEN_VAR
from etsy_listings.core.workspace import layout

ClientFactory = Callable[[str], PrintifyClient]
"""Builds a client from a *candidate* token. Injected rather than imported so
the verification step -- the one thing `setup` exists to do that reading the
docs does not -- can be driven without a network."""

EtsyAccessFactory = Callable[[Path], EtsyAccess | None]
"""Builds Etsy access from what the workspace has stored, or answers ``None``
when it has nothing. Injected for the same reason the Printify factory is: the
discovery is the part worth testing, and it should not need a network."""

WHO_MADE = ["someone_else", "i_did", "collective"]
WHEN_MADE = ["made_to_order", "2020_2025", "2010_2019", "before_2004"]
RENEWAL = ["manual", "auto"]


@dataclass(frozen=True)
class EtsyFindings:
    """What `setup` managed to learn about the Etsy side. Every field may be
    ``None``: a workspace is usable before Etsy is reachable at all.

    No shop section here -- Phase 3 drops it from `shop.yaml` entirely
    (decision 7): which section a listing files under is a fact about that
    listing, not the shop, so it is asked (optionally) in `new`/`listing.yaml`
    instead, never resolved by `setup`.
    """

    shop: EtsyShop | None = None
    return_policy: dict[str, Any] | None = None
    """The three terms a return policy is addressed by, not an id."""


def _sync_prompts(root: Path, *, replace: bool) -> None:
    """Say what seeding, checking or replacing each packaged prompt did."""
    for synced in workspace_setup.sync_packaged_prompts(root, replace=replace):
        where, label, backup = synced.where, synced.label, synced.backup
        if synced.outcome == "created":
            typer.echo(f"  seeded {where} with the default {label} prompt")
        elif synced.outcome == "current":
            typer.echo(f"  {where} is the packaged default")
        elif synced.outcome == "replaced":
            typer.echo(f"  replaced {where} with the default {label} prompt; yours is {backup}")
        else:
            typer.echo(
                f"  warning: {where} differs from the packaged default; "
                f"`etsy-listings setup --replace-prompts` replaces it and keeps yours as {backup}"
            )


def _verified_token(root: Path, factory: ClientFactory) -> tuple[str, list[Shop]]:
    """A token that has actually answered ``GET /v1/shops.json``, and what it
    answered.

    The shop list comes back from the same call rather than being fetched
    again: verifying the token *is* asking which shops it can reach,
    and a second call would only invite the two answers to disagree. That is
    also why this one verifies a *reused* token where ``auth`` does not --
    ``setup`` needs the answer either way, so there is no call to save.
    """

    def verify(values: tuple[str, ...]) -> tuple[list[Shop], str]:
        try:
            shops = core_credentials.verify_printify_token(values[0], client_for=factory)
        except PrintifyAuthError as exc:
            credentials.refuse(str(exc), command="setup")
        return shops, f"verified -- the token can reach {len(shops)} shop(s)."

    captured = credentials.capture(
        root,
        credentials.PRINTIFY,
        verify=verify,
        command="setup",
        reuse_message=f"Using the {PRINTIFY_TOKEN_VAR} this machine already has.",
    )
    return captured.values[0], captured.require_proof()


def _pick_shop(shops: list[Shop]) -> Shop:
    selection = shop_discovery.select_shop(shops)
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
    pod = workspace_setup.POD_DEFAULTS
    summary = ", ".join(f"{key}: {value}" for key, value in pod.items())
    if prompts.ask_confirm(f"Use the print-on-demand defaults for Etsy? ({summary})", default=True):
        return dict(pod)

    return {
        "who_made": prompts.ask_choice("Who made the item?", WHO_MADE),
        "when_made": prompts.ask_choice("When was it made?", WHEN_MADE),
        "is_supply": prompts.ask_confirm("Is it a craft supply rather than a finished item?"),
        "renewal": prompts.ask_choice("Listing renewal policy?", RENEWAL),
    }


def _discover_etsy(
    access: EtsyAccess | None,
    printify_shop: Shop,
    existing_etsy: dict[str, Any],
    existing_listing_defaults: dict[str, Any],
) -> EtsyFindings:
    """Find the Etsy shop and its return policy.

    Never fatal. `setup`'s job is to leave a usable workspace, and everything
    it learns here is optional to that: a failure reports what it could not
    reach and keeps whatever the file already said.
    """
    if access is None:
        typer.echo("")
        typer.echo("No Etsy credentials stored yet, so the Etsy shop cannot be looked up.")
        typer.echo("  Run `etsy-listings auth` first, then re-run `setup` to fill it in.")
        return EtsyFindings()

    try:
        shop = _find_etsy_shop(access, printify_shop, existing_etsy)
        if shop is None:
            return EtsyFindings()
        return EtsyFindings(
            shop=shop,
            return_policy=_pick_return_policy(
                access, shop, existing_listing_defaults.get("return_policy")
            ),
        )
    except (EtsyAuthError, EtsyApiError) as exc:
        typer.echo("")
        typer.echo(f"Could not read the Etsy shop: {exc}")
        typer.echo("  Keeping whatever shop.yaml already says. `auth` then `setup` fixes this.")
        return EtsyFindings()


def _find_etsy_shop(
    access: EtsyAccess, printify_shop: Shop, existing_etsy: dict[str, Any]
) -> EtsyShop | None:
    """Discovery's answer if it has a certain one, else a name to look up."""
    found = shop_discovery.find_etsy_shop(access, printify_shop)
    if found is None:
        return _ask_for_etsy_shop(access, existing_etsy)

    typer.echo("")
    typer.echo(f"Etsy shop: {found.shop.shop_name} ({found.shop.shop_id})")
    if found.route == "connected":
        typer.echo(f"  matched from the connected Printify shop {printify_shop.title!r}.")
    else:
        typer.echo("  the shop the signed-in Etsy account owns.")
    return found.shop


def _ask_for_etsy_shop(access: EtsyAccess, existing_etsy: dict[str, Any]) -> EtsyShop | None:
    """The fallback: a name, resolved to an id by searching for it.

    Blank is a real answer -- a workspace with no Etsy shop yet is a workspace
    that can still render and create products.
    """
    default = str(existing_etsy.get("shop_name") or "")
    answer = prompts.ask_text("Etsy shop name (blank to skip):", default=default, allow_blank=True)
    name = answer.strip()
    if not name:
        return None

    lookup = shop_discovery.lookup_etsy_shop(access.client, name)
    if lookup.exact is not None:
        typer.echo(f"  found {lookup.exact.shop_name} ({lookup.exact.shop_id})")
        return lookup.exact
    if not lookup.candidates:
        typer.echo(f"  Etsy has no shop called {name!r}. Leaving the Etsy ids unset.")
        return None
    return prompts.pick(
        "Which Etsy shop?",
        list(lookup.candidates),
        label=lambda shop: f"{shop.shop_name}  ({shop.shop_id})",
    )


def _pick_return_policy(
    access: EtsyAccess, shop: EtsyShop, current: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Zero-config when the shop has exactly one; a question for two or more."""
    options = shop_discovery.return_policy_options(access.client, shop, current)
    policies = options.policies
    if not policies:
        typer.echo("  no return policies on Etsy yet -- listings can be drafted without one.")
        return None
    if len(policies) == 1:
        typer.echo(f"  return policy: {policies[0].describe()} (the shop's only one)")
        return None

    def label(policy: ReturnPolicy | None) -> str:
        if policy is None:
            return "(none)"
        return policy.describe() + ("  -- current" if options.is_current(policy) else "")

    chosen = prompts.pick(
        "Which return policy should listings carry?", [*policies, None], label=label
    )
    return None if chosen is None else shop_discovery.policy_terms(chosen)


def run_setup(
    root: Path,
    *,
    client_factory: ClientFactory | None = None,
    etsy_access: EtsyAccessFactory | None = None,
    replace_prompts: bool = False,
) -> None:
    factory = client_factory or connections.printify_client_for
    access_factory = etsy_access or shop_discovery.etsy_access
    root.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Setting up a workspace in {root}")

    created = workspace_setup.create_directories(root)
    typer.echo(
        f"  created {len(created)} directories" if created else "  directories already in place"
    )
    credentials.announce_gitignore(root)

    _sync_prompts(root, replace=replace_prompts)

    token, shops = _verified_token(root, factory)
    shop = _pick_shop(shops)

    # Every prompt is seeded from the file, which is what makes "the answer
    # wins" safe on a re-run: pressing enter through the whole wizard changes
    # nothing, and typing something different is taken at face value.
    existing = workspace_setup.read_shop_document(root) or {}
    existing_etsy = existing.get("etsy") or {}
    existing_printify = existing.get("printify") or {}
    existing_listing_defaults = existing_etsy.get("listing_defaults") or {}

    findings = _discover_etsy(access_factory(root), shop, existing_etsy, existing_listing_defaults)

    currency = prompts.ask_text(
        "Shop currency (ISO code):",
        default=shop_discovery.currency_default(findings.shop, existing_etsy),
    )
    provider = prompts.ask_text(
        "Preferred print provider (blank for none):",
        default=str(existing_printify.get("preferred_print_provider") or ""),
        allow_blank=True,
    )
    etsy_defaults = _ask_etsy_defaults()
    shipping_profile = prompts.ask_text(
        "Shipping profile name for listings (blank to skip; matched against "
        "Etsy's shipping profiles when a listing is planned):",
        default=str(existing_listing_defaults.get("shipping_profile") or ""),
        allow_blank=True,
    )
    production_partner = prompts.ask_text(
        "Production partner name (blank if the shop has exactly one -- it is used automatically):",
        default=str(existing_listing_defaults.get("production_partner") or ""),
        allow_blank=True,
    )

    answers = workspace_setup.SetupAnswers(
        printify_shop_id=shop.id,
        printify_shop_name=shop.title,
        preferred_print_provider=provider.strip() or None,
        currency=currency.strip().upper(),
        etsy_shop_name=findings.shop.shop_name if findings.shop else None,
        etsy_shop_id=findings.shop.shop_id if findings.shop else None,
        etsy_shipping_profile=shipping_profile.strip() or None,
        etsy_return_policy=findings.return_policy,
        etsy_production_partner=production_partner.strip() or None,
        **etsy_defaults,
    )

    # Every question is answered, so the credential is worth keeping: writing
    # it earlier would leave a token behind after a cancelled run.
    workspace_setup.save_setup(root, printify_token=token, answers=answers, existing=existing)

    _report_next_steps(root, shop, findings)


def _report_next_steps(root: Path, shop: Shop, findings: EtsyFindings) -> None:
    typer.echo("")
    typer.echo(f"Workspace ready at {root}")
    typer.echo(f"  Printify shop  {shop.title} ({shop.id})")
    if findings.shop is not None:
        typer.echo(f"  Etsy shop      {findings.shop.shop_name} ({findings.shop.shop_id})")
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
