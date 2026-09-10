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

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
import yaml

from etsy_listings import credentials, prompts
from etsy_listings.clients.etsy.models import ReturnPolicy
from etsy_listings.clients.etsy.models import Shop as EtsyShop
from etsy_listings.clients.etsy.shops import EtsyShopClient, HttpEtsyShopClient
from etsy_listings.clients.etsy.tokens import EtsyAuthError, TokenStore
from etsy_listings.clients.etsy.transport import EtsyApiError, OAuthClient
from etsy_listings.clients.etsy.transport import Transport as EtsyTransport
from etsy_listings.clients.printify import HttpPrintifyClient, PrintifyAuthError, Transport
from etsy_listings.clients.printify.models import Shop
from etsy_listings.clients.printify.protocol import PrintifyClient
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR, EtsyAppKey, Secrets
from etsy_listings.setupcmd import logic
from etsy_listings.workspace import layout, scaffold

ClientFactory = Callable[[str], PrintifyClient]
"""Builds a client from a *candidate* token. Injected rather than imported so
the verification step -- the one thing `setup` exists to do that reading the
docs does not -- can be driven without a network."""

WHO_MADE = ["someone_else", "i_did", "collective"]
WHEN_MADE = ["made_to_order", "2020_2025", "2010_2019", "before_2004"]
RENEWAL = ["manual", "auto"]

POD_DEFAULTS = {
    "who_made": "someone_else",
    "when_made": "made_to_order",
    "is_supply": False,
    "renewal": "manual",
}
"""What every print-on-demand t-shirt listing answers (PRD 52: the shirt
genuinely was made by another company). Offered as one confirmation rather
than four questions, because getting four identical answers out of the user
teaches them the wizard is not worth reading.

``who_made: someone_else`` requires a production partner attached to the
listing (decision 3) -- not enforced here, since resolving a *name* to a
partner needs the shop's live list, which `setup` may not be able to reach.
`plan` is where an unresolvable or missing partner blocks."""


def _default_client_factory(token: str) -> PrintifyClient:
    return HttpPrintifyClient(Transport(token))


def _verified_token(root: Path, factory: ClientFactory) -> tuple[str, list[Shop]]:
    """A token that has actually answered ``GET /v1/shops.json``, and what it
    answered.

    The shop list comes back from the same call rather than being fetched
    again: verifying the token *is* asking which shops it can reach (PRD 42),
    and a second call would only invite the two answers to disagree. That is
    also why this one verifies a *reused* token where ``auth`` does not --
    ``setup`` needs the answer either way, so there is no call to save.
    """

    def verify(values: tuple[str, ...]) -> tuple[list[Shop], str]:
        try:
            shops = factory(values[0]).shops()
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


@dataclass(frozen=True)
class EtsyAccess:
    """A client that can read Etsy, and who it is reading as.

    ``user_id`` is ``None`` when the app key pair is stored but nobody has
    signed in: the searches still work -- they are unscoped -- but "which shop
    does the signed-in seller own?" has no answer, so discovery falls back to
    asking for a name.
    """

    client: EtsyShopClient
    user_id: int | None


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
    """The three terms a return policy is addressed by (PRD 59), not an id."""


EtsyAccessFactory = Callable[[Path], EtsyAccess | None]
"""Builds Etsy access from what the workspace has stored, or answers ``None``
when it has nothing. Injected for the same reason the Printify factory is: the
discovery is the part worth testing, and it should not need a network."""


def _default_etsy_access(root: Path) -> EtsyAccess | None:
    secrets = Secrets.load(root / layout.ENV_FILE)
    if not (secrets.etsy_keystring and secrets.etsy_shared_secret):
        return None
    app_key = EtsyAppKey(secrets.etsy_keystring, secrets.etsy_shared_secret)

    store = TokenStore(
        root / layout.AUTH_DIR / layout.ETSY_TOKENS_FILE,
        refresh=lambda token: OAuthClient(app_key.keystring).refresh(token),
    )
    tokens = store.load()
    # Every call `setup` makes is unscoped, so a bearer is a bonus rather than
    # a requirement -- it is what makes `shop_by_owner` possible, nothing more.
    bearer = store.access_token if tokens is not None else None
    transport = EtsyTransport(app_key, bearer=bearer)
    return EtsyAccess(HttpEtsyShopClient(transport), tokens.user_id if tokens else None)


def _discover_etsy(
    access: EtsyAccess | None,
    printify_shop: Shop,
    existing_etsy: dict[str, Any],
    existing_listing_defaults: dict[str, Any],
) -> EtsyFindings:
    """Find the Etsy shop and its return policy (PRD 51, PRD 59).

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
                access.client, shop, existing_listing_defaults.get("return_policy")
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
    """Three routes to the shop, cheapest and most certain first.

    A connected Printify shop is the best evidence available: Printify names
    the shop after the Etsy shop it publishes to, so the selection the user
    just made *is* the answer. Failing that, an Etsy account owns exactly one
    shop, and the stored consent says which account. Only if both are silent
    does anyone get asked to type a name.
    """
    if printify_shop.is_connected:
        matches = access.client.find_shops(printify_shop.title)
        found = logic.exact_shop_match(matches, printify_shop.title)
        if found is not None:
            typer.echo("")
            typer.echo(f"Etsy shop: {found.shop_name} ({found.shop_id})")
            typer.echo(f"  matched from the connected Printify shop {printify_shop.title!r}.")
            return found

    if access.user_id is not None:
        owned = access.client.shop_by_owner(access.user_id)
        if owned is not None:
            typer.echo("")
            typer.echo(f"Etsy shop: {owned.shop_name} ({owned.shop_id})")
            typer.echo("  the shop the signed-in Etsy account owns.")
            return owned

    return _ask_for_etsy_shop(access, existing_etsy)


def _ask_for_etsy_shop(access: EtsyAccess, existing_etsy: dict[str, Any]) -> EtsyShop | None:
    """The fallback: a name, resolved to an id by searching for it.

    Blank is a real answer -- a workspace with no Etsy shop yet is a workspace
    that can still render and create products -- and the id is never asked
    for, because a number typed by hand is the thing this whole path exists to
    avoid.
    """
    default = str(existing_etsy.get("shop_name") or "")
    answer = prompts.ask_text("Etsy shop name (blank to skip):", default=default, allow_blank=True)
    name = answer.strip()
    if not name:
        return None

    matches = access.client.find_shops(name)
    exact = logic.exact_shop_match(matches, name)
    if exact is not None:
        typer.echo(f"  found {exact.shop_name} ({exact.shop_id})")
        return exact
    if not matches:
        typer.echo(f"  Etsy has no shop called {name!r}. Leaving the Etsy ids unset.")
        return None
    return prompts.pick(
        "Which Etsy shop?",
        matches,
        label=lambda shop: f"{shop.shop_name}  ({shop.shop_id})",
    )


def _policy_terms(policy: ReturnPolicy) -> dict[str, Any]:
    return {
        "accepts_returns": bool(policy.accepts_returns),
        "accepts_exchanges": bool(policy.accepts_exchanges),
        "within_days": policy.return_deadline,
    }


def _pick_return_policy(
    client: EtsyShopClient, shop: EtsyShop, current: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Zero-config when the shop has exactly one (PRD 59): most shops do, and
    a shop with one return policy needs no reference to it at all -- the
    stages resolve it live the same way. Only two or more make it a question,
    and the answer is the policy's *terms*, not an id Etsy gives no title."""
    policies = client.return_policies(shop.shop_id)
    if not policies:
        typer.echo("  no return policies on Etsy yet -- listings can be drafted without one.")
        return None
    if len(policies) == 1:
        typer.echo(f"  return policy: {policies[0].describe()} (the shop's only one)")
        return None

    def _is_current(policy: ReturnPolicy) -> bool:
        return current is not None and _policy_terms(policy) == current

    ordered = sorted(policies, key=lambda policy: not _is_current(policy))
    chosen = prompts.pick(
        "Which return policy should listings carry?",
        [*ordered, None],
        label=lambda policy: (
            "(none)"
            if policy is None
            else policy.describe() + ("  -- current" if _is_current(policy) else "")
        ),
    )
    return None if chosen is None else _policy_terms(chosen)


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


def run_setup(
    root: Path,
    *,
    client_factory: ClientFactory | None = None,
    etsy_access: EtsyAccessFactory | None = None,
) -> None:
    factory = client_factory or _default_client_factory
    access_factory = etsy_access or _default_etsy_access
    root.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Setting up a workspace in {root}")

    created = logic.create_directories(root)
    typer.echo(
        f"  created {len(created)} directories" if created else "  directories already in place"
    )
    credentials.announce_gitignore(root)

    token, shops = _verified_token(root, factory)
    shop = _pick_shop(shops)

    # Every prompt is seeded from the file, which is what makes "the answer
    # wins" safe on a re-run: pressing enter through the whole wizard changes
    # nothing, and typing something different is taken at face value.
    existing = _existing_document(root) or {}
    existing_etsy = existing.get("etsy") or {}
    existing_printify = existing.get("printify") or {}
    existing_listing_defaults = existing_etsy.get("listing_defaults") or {}

    findings = _discover_etsy(access_factory(root), shop, existing_etsy, existing_listing_defaults)

    currency = prompts.ask_text(
        "Shop currency (ISO code):",
        default=_currency_default(findings, existing_etsy),
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

    answers = logic.SetupAnswers(
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
    scaffold.write_env_value(root, PRINTIFY_TOKEN_VAR, token)

    document = logic.shop_yaml_document(answers, existing)
    (root / layout.SHOP_FILE).write_text(logic.render_shop_yaml(document), encoding="utf-8")

    _report_next_steps(root, shop, findings)


def _currency_default(findings: EtsyFindings, existing_etsy: dict[str, Any]) -> str:
    """The Etsy shop's own currency wins, then the file, then NOK.

    The shop's answer goes first because it is the only one that cannot be
    wrong: a workspace configured in a currency the shop does not sell in is a
    disagreement nothing surfaces until a price lands wrong (PRD 51). It is
    still offered as a default rather than imposed -- it is a prompt, and the
    user can say otherwise.
    """
    if findings.shop is not None and findings.shop.currency_code:
        return findings.shop.currency_code
    return str(existing_etsy.get("currency") or "NOK")


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
