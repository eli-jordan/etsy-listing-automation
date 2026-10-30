"""The Admin page's Shop tab: ``shop.yaml`` read and edited, and what it names.

Admin plan, PR 3, *Shop*. Three operations, each a caller's whole job:

- :func:`read_shop` and :func:`edit_shop` -- the file with a revision of its
  exact bytes, and a revision-checked edit of the keys the page offers. The
  candidate document is validated as a whole ``Defaults`` before anything is
  written; an edit that changes nothing leaves the file byte-identical
  (``workspace.revisions``, ADR-0055). A save adopts the new defaults in the
  running ``Workspace`` so the next plan or deploy reads them.
- :func:`shop_connections` -- the configured Etsy and Printify shops, and
  whether a live lookup agrees, without ever erasing a configured identity
  because a service could not be reached.
- :func:`shop_lookups` -- the shop's live lists for the defaults' selectors.
  Etsy's are fetched fresh on every call, never disk-cached (ADR-0033).

An edit copies nothing into listing files, lockfiles or remote state: those
inherit the defaults when a listing is next planned, and names still resolve
against the shop's live lists at deploy time (``EtsyShopCatalog``). A currency
edit converts no price: a saved explicit price keeps its own currency
(ADR-0006, ADR-0019) and may need a seller edit before the next deploy.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from etsy_listings.core import connections
from etsy_listings.core.application.refusals import (
    InvalidShopEdit,
    ShopRevisionConflict,
    field_errors_of,
)
from etsy_listings.core.application.shop_discovery import policy_terms
from etsy_listings.core.application.workspace_setup import POD_DEFAULTS
from etsy_listings.core.clients.etsy.listings import EtsyListingClient
from etsy_listings.core.clients.etsy.shopcatalog import EtsyShopCatalog
from etsy_listings.core.clients.etsy.shops import EtsyShopClient
from etsy_listings.core.clients.printify.protocol import CatalogClient, PrintifyClient
from etsy_listings.core.config.currencies import OFFERED_CURRENCIES
from etsy_listings.core.config.defaults import Defaults
from etsy_listings.core.config.errors import ConfigLoadError, parse_yaml
from etsy_listings.core.config.secrets import Secrets
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.revisions import (
    RevisionConflict,
    read_revisioned,
    replace_if_unchanged,
)
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.core.workspace.yaml_source import edit_yaml_bytes

EDITABLE_KEYS: tuple[str, ...] = (
    "etsy.currency",
    "etsy.listing_defaults.who_made",
    "etsy.listing_defaults.when_made",
    "etsy.listing_defaults.is_supply",
    "etsy.listing_defaults.production_partner",
    "etsy.listing_defaults.shipping_profile",
    "etsy.listing_defaults.return_policy",
    "etsy.listing_defaults.renewal",
    "printify.preferred_print_provider",
)
"""What the page edits. Shop identities are read-only here: they change
only through ``setup`` and ``auth`` (Admin plan, *Shop*)."""

PRINT_ON_DEMAND: dict[str, object] = {
    f"etsy.listing_defaults.{key}": POD_DEFAULTS[key]
    for key in ("who_made", "when_made", "is_supply")
}
"""The three values Print on demand is derived from and writes together.
There is no stored preset key; matching values *are* Print on demand."""

LookupFailure = (UserFacingError, httpx.HTTPError)
"""Every way a client reports that a service could not answer: API refusals,
missing or expired credentials, and the network itself."""


# ------------------------------------------------------------- the file


@dataclass(frozen=True)
class ShopView:
    revision: str
    """sha256 of ``shop.yaml``'s exact bytes; the next edit must name it."""
    defaults: Defaults


def read_shop(workspace: Workspace) -> ShopView:
    """``shop.yaml`` as it is now. A file that does not load raises
    ``ConfigLoadError`` naming it, like every other reader."""
    path = workspace.root / layout.SHOP_FILE
    data, revision = read_revisioned(path)
    raw = parse_yaml(path, data.decode("utf-8-sig")) or {}
    try:
        return ShopView(revision, Defaults.from_document(path, raw))
    except ValidationError as exc:
        raise ConfigLoadError(path, str(exc)) from exc


def edit_shop(
    workspace: Workspace, *, expected_revision: str, changes: Mapping[str, object]
) -> ShopView:
    """Apply ``changes`` (dotted key to value; ``None`` removes an optional
    key) if ``shop.yaml`` is still at ``expected_revision``.

    Refuses with :class:`ShopRevisionConflict` or :class:`InvalidShopEdit`,
    writing nothing either way.
    """
    refused = {
        key: "not editable from the Admin page" for key in changes if key not in EDITABLE_KEYS
    }
    currency = changes.get("etsy.currency")
    if "etsy.currency" in changes and currency not in OFFERED_CURRENCIES:
        refused["etsy.currency"] = (
            f"{currency!r} is not a currency this workspace can be set to: Etsy Payments "
            "must support it and its prices must have two decimals (ADR-0019)"
        )
    if refused:
        raise InvalidShopEdit(refused)

    path = workspace.root / layout.SHOP_FILE
    adopted: list[Defaults] = []

    def change(source: bytes) -> bytes:
        raw = parse_yaml(path, source.decode("utf-8-sig")) or {}
        if not isinstance(raw, dict):
            raise InvalidShopEdit({"__root__": "shop.yaml is not a mapping"})
        candidate: dict[str, Any] = copy.deepcopy(raw)
        for key, value in changes.items():
            _assign(candidate, key.split("."), value)
        try:
            adopted.append(Defaults.from_document(path, candidate))
        except ValidationError as exc:
            raise InvalidShopEdit(field_errors_of(exc)) from exc
        except ConfigLoadError as exc:
            raise InvalidShopEdit({"__root__": str(exc)}) from exc
        return edit_yaml_bytes(source, candidate)

    try:
        revised = replace_if_unchanged(path, expected_revision, change)
    except RevisionConflict as exc:
        raise ShopRevisionConflict() from exc
    (defaults,) = adopted
    workspace.defaults = defaults
    return ShopView(revised.revision, defaults)


def _assign(document: dict[str, Any], path: list[str], value: object) -> None:
    *parents, leaf = path
    node = document
    for part in parents:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    if value is None:
        node.pop(leaf, None)
    else:
        node[leaf] = value


# ------------------------------------------------------------- connections

ConnectionState = Literal["connected", "not_connected", "lookup_failed"]


@dataclass(frozen=True)
class ConnectionRow:
    state: ConnectionState
    shop_name: str | None
    """As configured; kept whatever a lookup says, so a service that is down
    never makes a configured shop look absent."""
    shop_id: int | None
    commands: tuple[str, ...] = ()
    """What to run when ``not_connected``, in order. The page shows them;
    it never runs them."""
    problem: str | None = None
    """Why a lookup failed or disagreed."""
    signed_in_user_id: int | None = None
    """Etsy only: whose consent the tokens carry."""
    sales_channel: str | None = None
    """Printify only: where the shop publishes, as Printify reports it."""
    shop_currency: str | None = None
    """Etsy only: the currency the live shop sells in, so the page can warn
    when ``etsy.currency`` is changed away from it."""


@dataclass(frozen=True)
class ShopConnections:
    etsy: ConnectionRow
    printify: ConnectionRow


SETUP = "etsy-listings setup"


def shop_connections(
    workspace: Workspace, *, etsy: EtsyShopClient, printify: PrintifyClient
) -> ShopConnections:
    """Both rows. Credentials are checked on disk without reading their
    values out; only a fully configured service is looked up live."""
    return ShopConnections(_etsy_row(workspace, etsy), _printify_row(workspace, printify))


def _etsy_row(workspace: Workspace, client: EtsyShopClient) -> ConnectionRow:
    configured = workspace.defaults.etsy
    tokens = connections.etsy_token_store(workspace.root).load()
    commands: list[str] = []
    if connections.etsy_app_key(workspace.root) is None or tokens is None:
        commands.append("etsy-listings auth etsy")
    if configured.shop_id is None:
        commands.append(SETUP)
    user_id = tokens.user_id if tokens is not None else None
    if commands or tokens is None or configured.shop_id is None:
        return ConnectionRow(
            "not_connected",
            configured.shop_name,
            configured.shop_id,
            tuple(commands),
            signed_in_user_id=user_id,
        )
    row = ConnectionRow(
        "connected", configured.shop_name, configured.shop_id, signed_in_user_id=user_id
    )
    try:
        owned = client.shop_by_owner(tokens.user_id)
    except LookupFailure as exc:
        return _failed(row, f"Could not reach Etsy: {exc}")
    if owned is None or owned.shop_id != configured.shop_id:
        owner = f"shop #{owned.shop_id} ({owned.shop_name})" if owned else "no shop"
        return _failed(row, f"The signed-in Etsy account owns {owner}, not #{configured.shop_id}.")
    return replace(row, shop_currency=owned.currency_code)


def _printify_row(workspace: Workspace, client: PrintifyClient) -> ConnectionRow:
    configured = workspace.defaults.printify
    commands: list[str] = []
    if not Secrets.load(workspace.root / layout.ENV_FILE).printify_api_token:
        commands.append("etsy-listings auth printify")
    if configured.shop_id is None:
        commands.append(SETUP)
    if commands:
        return ConnectionRow(
            "not_connected", configured.shop_name, configured.shop_id, tuple(commands)
        )
    row = ConnectionRow("connected", configured.shop_name, configured.shop_id)
    try:
        shops = client.shops()
    except LookupFailure as exc:
        return _failed(row, f"Could not reach Printify: {exc}")
    shop = next((s for s in shops if s.id == configured.shop_id), None)
    if shop is None:
        return _failed(row, f"Printify does not list shop #{configured.shop_id} for this token.")
    return ConnectionRow(
        "connected",
        configured.shop_name or shop.title,
        configured.shop_id,
        sales_channel=shop.sales_channel,
    )


def _failed(row: ConnectionRow, problem: str) -> ConnectionRow:
    return ConnectionRow(
        "lookup_failed",
        row.shop_name,
        row.shop_id,
        problem=problem,
        signed_in_user_id=row.signed_in_user_id,
    )


# ----------------------------------------------------------------- lookups


@dataclass(frozen=True)
class ReturnPolicyChoice:
    terms: dict[str, Any]
    """What ``etsy.listing_defaults.return_policy`` stores."""
    label: str
    """``ReturnPolicy.describe()``: Etsy gives a policy no title."""


@dataclass(frozen=True)
class EtsyLookups:
    available: bool
    problem: str | None = None
    production_partners: tuple[str, ...] = ()
    shipping_profiles: tuple[str, ...] = ()
    return_policies: tuple[ReturnPolicyChoice, ...] = ()


@dataclass(frozen=True)
class PrintifyLookups:
    available: bool
    problem: str | None = None
    print_providers: tuple[str, ...] = ()
    """Every provider by name, the saved preference first."""


@dataclass(frozen=True)
class ShopLookups:
    etsy: EtsyLookups
    printify: PrintifyLookups


def shop_lookups(
    workspace: Workspace, *, etsy: EtsyListingClient, catalog: CatalogClient
) -> ShopLookups:
    """The selectors' choices, each service failing on its own. A failure
    reports a problem and no choices; it never touches ``shop.yaml``, and
    the page keeps showing the saved value."""
    return ShopLookups(_etsy_lookups(workspace, etsy), _printify_lookups(workspace, catalog))


def _etsy_lookups(workspace: Workspace, client: EtsyListingClient) -> EtsyLookups:
    shop_id = workspace.defaults.etsy.shop_id
    if shop_id is None:
        return EtsyLookups(False, f"No Etsy shop is configured yet. Run `{SETUP}`.")
    # A fresh catalog per call: one in-memory fetch of each list (ADR-0033).
    shop = EtsyShopCatalog(client, shop_id)
    try:
        partners = shop.production_partners()
        profiles = shop.shipping_profiles()
        policies = shop.return_policies()
    except LookupFailure as exc:
        return EtsyLookups(False, f"Could not reach Etsy: {exc}")
    return EtsyLookups(
        True,
        production_partners=_unique(p.partner_name for p in partners if p.partner_name),
        shipping_profiles=_unique(p.title for p in profiles),
        return_policies=tuple(ReturnPolicyChoice(policy_terms(p), p.describe()) for p in policies),
    )


def _printify_lookups(workspace: Workspace, catalog: CatalogClient) -> PrintifyLookups:
    try:
        providers = catalog.all_print_providers()
    except LookupFailure as exc:
        return PrintifyLookups(False, f"Could not reach Printify: {exc}")
    preferred = workspace.defaults.printify.preferred_print_provider
    names = sorted(_unique(p.title for p in providers), key=lambda name: name != preferred)
    return PrintifyLookups(True, print_providers=tuple(names))


def _unique(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))
