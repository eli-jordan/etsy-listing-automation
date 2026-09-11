"""The ``etsy_listing`` stage: one ``PATCH updateListing`` carrying copy,
tags, materials, section, shipping profile, return policy, the `who_made`
trio, production partners and renewal (phase-3-etsy.md, decision 1).

Everything a name resolves to comes from :class:`EtsyShopCatalog` (A25),
built fresh each call to ``desired`` -- cheap, since the catalog itself
fetches each of its four lists at most once and this stage asks for at most
three of them. Every :class:`~etsy_listings.clients.etsy.shopcatalog.ShopCatalogError`
becomes a :class:`~etsy_listings.engine.stage.Blocked`: a name that will not
resolve is exactly the kind of refusal `desired()` exists to report, listing
every candidate the shop actually has rather than sending Etsy a PATCH that
would answer `400` and fail the whole thing (a stale `shop_section_id` fails
the entire request, measured).

``state`` is never sent -- Etsy's update enum is `active | inactive`, a draft
cannot be re-drafted, and the one thing this tool must never do by accident
is activate a listing (PRD non-goal 1).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from etsy_listings.clients.etsy.models import Listing as EtsyListing
from etsy_listings.clients.etsy.shopcatalog import (
    EtsyShopCatalog,
    ReturnPolicyTerms,
    ShopCatalogError,
)
from etsy_listings.config.defaults import EtsyReturnPolicyDefaults
from etsy_listings.config.listing import GENERATE
from etsy_listings.engine.change import (
    Change,
    Drift,
    FieldChange,
    Verdict,
    drift,
    scalar,
    sequence,
)
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stage import Blocked, StageApplyResult
from etsy_listings.engine.stages.etsy_target import (
    check_etsy_shop,
    etsy_listing_id,
    require_etsy_listing_id,
)
from etsy_listings.engine.stages.gates import check_copy_is_concrete

NO_SHOP_CONSEQUENCE = "this listing's copy and settings cannot be patched on Etsy"


class ReturnPolicyApplied(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    accepts_returns: bool
    accepts_exchanges: bool
    within_days: int | None = None


class AppliedEtsyListing(BaseModel):
    """The verbatim last-applied document (A2). Names sit beside their ids
    (decision 2): the id is what was sent, the name is what a human reading
    the plan or the lockfile can actually check."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    title: str
    description: str
    tags: tuple[str, ...]
    materials: tuple[str, ...]
    shop_section: str | None = None
    shop_section_id: int | None = None
    shipping_profile: str
    shipping_profile_id: int
    return_policy: ReturnPolicyApplied
    return_policy_id: int
    who_made: str
    when_made: str
    is_supply: bool
    production_partners: tuple[str, ...] = ()
    production_partner_ids: tuple[int, ...] = ()
    should_auto_renew: bool


@dataclass(frozen=True)
class EtsyListingDesired:
    title: str
    description: str
    tags: tuple[str, ...]
    materials: tuple[str, ...]
    shop_section: str | None
    shop_section_id: int | None
    shipping_profile: str
    shipping_profile_id: int
    return_policy: ReturnPolicyApplied
    return_policy_id: int
    who_made: str
    when_made: str
    is_supply: bool
    production_partners: tuple[str, ...]
    production_partner_ids: tuple[int, ...]
    should_auto_renew: bool

    def applied(self) -> AppliedEtsyListing:
        return AppliedEtsyListing(**self.__dict__)

    def patch_body(self) -> dict[str, object]:
        """The PATCH body -- every field this stage owns, always sent in
        full. `updateListing` honours a partial body, but there is no benefit
        to sending less: every field here is this stage's own, never shared
        with another writer, so there is nothing a partial PATCH would
        protect."""
        body: dict[str, object] = {
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "materials": list(self.materials),
            "shipping_profile_id": self.shipping_profile_id,
            "return_policy_id": self.return_policy_id,
            "who_made": self.who_made,
            "when_made": self.when_made,
            "is_supply": self.is_supply,
            "should_auto_renew": self.should_auto_renew,
        }
        if self.shop_section_id is not None:
            body["shop_section_id"] = self.shop_section_id
        if self.production_partner_ids:
            body["production_partner_ids"] = list(self.production_partner_ids)
        return body


class EtsyListingStage:
    name = "etsy_listing"
    local = False
    applied_model = AppliedEtsyListing

    def desired(
        self, ctx: RunContext, listing: str, applied: AppliedEtsyListing | None
    ) -> EtsyListingDesired | Blocked:
        del applied
        workspace = ctx.workspace
        blocked = check_etsy_shop(ctx, consequence=NO_SHOP_CONSEQUENCE)
        if blocked is not None:
            return blocked

        config = workspace.load_listing(listing)
        blocked = check_copy_is_concrete(
            title=config.etsy.title, description=config.etsy.description
        )
        if blocked is not None:
            return blocked

        shop_id = workspace.defaults.etsy.require_shop_id()
        catalog = EtsyShopCatalog(ctx.require_etsy(), shop_id)
        listing_defaults = workspace.defaults.etsy.listing_defaults

        try:
            section = (
                catalog.shop_section(config.etsy.section)
                if config.etsy.section is not None
                else None
            )

            shipping_profile_name = (
                config.etsy.shipping_profile or listing_defaults.shipping_profile
            )
            if shipping_profile_name is None:
                return Blocked(
                    "no shipping_profile is configured for this listing, and "
                    "shop.yaml's etsy.listing_defaults.shipping_profile is unset.\n"
                    "Set one of the two -- by name, from the shop's shipping profiles."
                )
            shipping_profile = catalog.shipping_profile(shipping_profile_name)

            return_policy = catalog.return_policy(_terms(listing_defaults.return_policy))

            partner_names: tuple[str, ...] = ()
            partner_ids: tuple[int, ...] = ()
            if listing_defaults.who_made == "someone_else":
                partner = catalog.production_partner(listing_defaults.production_partner)
                partner_names = (partner.partner_name or "",)
                partner_ids = (partner.production_partner_id,)
        except ShopCatalogError as exc:
            return Blocked(str(exc))

        renewal = config.etsy.renewal or listing_defaults.renewal
        tags = () if config.etsy.tags == GENERATE else tuple(config.etsy.tags)

        return EtsyListingDesired(
            title=config.etsy.title,
            description=config.etsy.description,
            tags=tags,
            materials=tuple(config.etsy.materials),
            shop_section=section.title if section is not None else None,
            shop_section_id=section.shop_section_id if section is not None else None,
            shipping_profile=shipping_profile.title,
            shipping_profile_id=shipping_profile.shipping_profile_id,
            return_policy=ReturnPolicyApplied(
                accepts_returns=bool(return_policy.accepts_returns),
                accepts_exchanges=bool(return_policy.accepts_exchanges),
                within_days=return_policy.return_deadline,
            ),
            return_policy_id=return_policy.return_policy_id,
            who_made=listing_defaults.who_made,
            when_made=listing_defaults.when_made,
            is_supply=listing_defaults.is_supply,
            production_partners=partner_names,
            production_partner_ids=partner_ids,
            should_auto_renew=renewal == "auto",
        )

    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: AppliedEtsyListing | None
    ) -> EtsyListing | None:
        """``None`` without a request when there is no listing id yet -- read
        with `GET /v3/application/listings/{id}`, the *unscoped* path: the
        shop-scoped one exists for `PATCH`/`DELETE` and 404s on `GET`
        (measured)."""
        del applied
        listing_id = etsy_listing_id(lock)
        if listing_id is None:
            return None
        return ctx.require_etsy().get_listing(listing_id)

    def plan(
        self,
        desired: EtsyListingDesired,
        applied: AppliedEtsyListing | None,
        live: EtsyListing | None,
    ) -> Verdict:
        wanted = desired.applied()
        drift_found = _drift(applied, live)

        if applied is None:
            return Verdict.work(
                "this listing has never been patched -- writing its copy and settings",
                drift=drift_found,
            )
        changes = _changes(wanted, applied)
        if changes:
            return Verdict.work(
                "the listing's copy or settings changed", changes=changes, drift=drift_found
            )
        if drift_found:
            return Verdict.work(
                "Etsy disagrees with what was last applied -- re-asserting", drift=drift_found
            )
        return Verdict(will_run=False, drift=drift_found)

    def apply(
        self,
        ctx: RunContext,
        desired: EtsyListingDesired,
        applied: AppliedEtsyListing | None,
        live: EtsyListing | None,
        lock: Lockfile,
    ) -> StageApplyResult:
        del applied, live
        listing_id = require_etsy_listing_id(lock, to="patch the listing")

        shop_id = ctx.workspace.defaults.etsy.require_shop_id()
        ctx.emit(f"patching Etsy listing {listing_id}")
        ctx.require_etsy().update_listing(shop_id, listing_id, desired.patch_body())

        return StageApplyResult(applied=desired.applied().model_dump(mode="json"))


def _terms(config: EtsyReturnPolicyDefaults | None) -> ReturnPolicyTerms | None:
    if config is None:
        return None
    return ReturnPolicyTerms(
        accepts_returns=config.accepts_returns,
        accepts_exchanges=config.accepts_exchanges,
        within_days=config.within_days,
    )


_FIELDS: tuple[str, ...] = (
    "title",
    "description",
    "shop_section_id",
    "shipping_profile_id",
    "return_policy_id",
    "who_made",
    "when_made",
    "is_supply",
    "should_auto_renew",
)


def _changes(wanted: AppliedEtsyListing, was: AppliedEtsyListing) -> tuple[Change, ...]:
    changes: list[Change] = []
    for path in _FIELDS:
        change = scalar(path, getattr(wanted, path), getattr(was, path))
        if change is not None:
            changes.append(change)
    for path in ("tags", "materials"):
        list_change = sequence(path, list(getattr(wanted, path)), list(getattr(was, path)))
        if list_change is not None:
            changes.append(list_change)
    if set(wanted.production_partner_ids) != set(was.production_partner_ids):
        changes.append(
            FieldChange(
                path="production_partner_ids",
                before=sorted(was.production_partner_ids),
                after=sorted(wanted.production_partner_ids),
            )
        )
    return tuple(changes)


def _drift(was: AppliedEtsyListing | None, live: EtsyListing | None) -> tuple[Drift, ...]:
    """What changed on Etsy since the last apply -- includes Printify
    re-attaching its own shipping profile after a republish (risk 13,
    decision 7)."""
    if was is None or live is None:
        return ()

    found: list[Drift] = []
    for path, ours, theirs in (
        ("title", was.title, live.title),
        ("description", was.description, live.description),
        ("shop_section_id", was.shop_section_id, live.shop_section_id),
        ("shipping_profile_id", was.shipping_profile_id, live.shipping_profile_id),
        ("return_policy_id", was.return_policy_id, live.return_policy_id),
        ("who_made", was.who_made, live.who_made),
        ("when_made", was.when_made, live.when_made),
        ("is_supply", was.is_supply, live.is_supply),
        ("should_auto_renew", was.should_auto_renew, live.should_auto_renew),
    ):
        change = drift(path, ours, theirs)
        if change is not None:
            found.append(change)

    live_partner_ids = {p.production_partner_id for p in live.production_partners}
    if set(was.production_partner_ids) != live_partner_ids and live.production_partners:
        # An empty `production_partners` on a draft this tool has already
        # patched reads as "not returned by this call" rather than "cleared"
        # -- Etsy gives no way to tell the two apart, so only a live set that
        # actually names something is trusted to disagree.
        found.append(
            Drift(
                path="production_partner_ids",
                last_applied=sorted(was.production_partner_ids),
                live=sorted(live_partner_ids),
            )
        )

    return tuple(found)
