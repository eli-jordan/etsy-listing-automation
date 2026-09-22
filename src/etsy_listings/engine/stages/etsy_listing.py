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

``state`` is omitted on a ``draft`` -- Etsy's update enum is
`active | inactive`, a draft cannot be re-drafted, and first publish stays
Shop Manager (PRD non-goal 1). Pause and resume of something a human already
published is the exception: ``lifecycle: retired`` sends ``inactive``;
Un-retire (last applied was retired, now omitted) and ``renew`` send
``active``. A remote pause with the field omitted does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from etsy_listings.clients.etsy.models import Listing as EtsyListing
from etsy_listings.clients.etsy.shopcatalog import (
    EtsyShopCatalog,
    ReturnPolicyTerms,
    ShopCatalogError,
)
from etsy_listings.config.defaults import EtsyReturnPolicyDefaults
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
from etsy_listings.engine.stages.gates import check_copy_is_concrete, check_garment_profile_chosen
from etsy_listings.workspace.common_copy import CommonCopyError

NO_SHOP_CONSEQUENCE = "this listing's copy and settings cannot be patched on Etsy"


class ReturnPolicyApplied(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    accepts_returns: bool
    accepts_exchanges: bool
    within_days: int | None = None

    def describe(self) -> str:
        """Mirrors :meth:`~etsy_listings.clients.etsy.models.ReturnPolicy.describe`
        -- a return policy has no title of its own (PRD 59), so this is the
        same human sentence, built from the same three fields this stage
        already carries, used as a drift label (A30) where the live side has
        only an id to compare with."""
        accepted = [
            name
            for name, allowed in (
                ("returns", self.accepts_returns),
                ("exchanges", self.accepts_exchanges),
            )
            if allowed
        ]
        if not accepted:
            return "no returns or exchanges"
        within = f" within {self.within_days} days" if self.within_days else ""
        return f"{' and '.join(accepted)}{within}"


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
    state: Literal["active", "inactive"] | None = None
    """What this stage last sent, when it sent ``state`` at all. ``None``
    means it has never paused or resumed this listing -- first publish does
    not, and a remote pause is not adopted into the applied document."""


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
    state: Literal["active", "inactive"] | None = None
    catalog: EtsyShopCatalog | None = None
    """This run's already-built :class:`EtsyShopCatalog` (A25), carried
    only so :func:`_drift` can label a *live* id it did not itself resolve a
    name for -- through lookups (``shop_section_title`` and its siblings)
    that read whatever ``desired()`` already fetched and issue no request of
    their own. ``plan()`` stays pure in effect: nothing here can reach the
    network. ``None`` only for a dataclass built by hand outside ``desired()``
    (as every current test does), where there is no drift to label."""

    def applied(self) -> AppliedEtsyListing:
        return AppliedEtsyListing(**{k: v for k, v in self.__dict__.items() if k != "catalog"})

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
        if self.state is not None:
            body["state"] = self.state
        return body


class EtsyListingFacts(BaseModel):
    """One side of the review (A30): the fields the mock shows unchanged
    context for, named rather than left as an id."""

    model_config = ConfigDict(frozen=True)

    title: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    materials: tuple[str, ...] = ()
    shop_section: str | None = None
    shipping_profile: str | None = None


class EtsyListingSnapshot(BaseModel):
    """Both sides, in full -- the ``Plan`` this stage also returns carries
    only what changed."""

    model_config = ConfigDict(frozen=True)

    desired: EtsyListingFacts
    live: EtsyListingFacts | None
    """``None`` for a listing with no Etsy id at all -- the mock's single
    "Not on Etsy yet" column (decision 3), not an empty one."""


class EtsyListingStage:
    name = "etsy_listing"
    local = False
    applied_model = AppliedEtsyListing

    def desired(
        self, ctx: RunContext, listing: str, applied: AppliedEtsyListing | None
    ) -> EtsyListingDesired | Blocked:
        workspace = ctx.workspace
        blocked = check_etsy_shop(ctx, consequence=NO_SHOP_CONSEQUENCE)
        if blocked is not None:
            return blocked

        config = workspace.load_listing(listing)
        blocked = check_garment_profile_chosen(config.garment_profile)
        if blocked is not None:
            return blocked
        profile = workspace.load_garment_profile(config.garment_profile)
        blocked = check_copy_is_concrete(title=config.etsy.title, lead=config.etsy.description.lead)
        if blocked is not None:
            return blocked
        try:
            description = workspace.compose_description(config.etsy.description)
        except CommonCopyError as exc:
            return Blocked(str(exc))

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
        tags = tuple(config.etsy.tags)

        return EtsyListingDesired(
            title=config.etsy.title,
            description=description,
            tags=tags,
            materials=tuple(profile.materials),
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
            state=_desired_state(config.lifecycle, applied),
            catalog=catalog,
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
        drift_found = _drift(applied, live, desired.catalog)

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
        return Verdict.no_work(drift=drift_found)

    def snapshot(
        self, desired: EtsyListingDesired, live: EtsyListing | None
    ) -> EtsyListingSnapshot:
        """Both sides, named (A30). The desired side already has names for
        its section and shipping profile -- resolving them is what
        ``desired()`` does -- so only the live side needs the catalog's
        reverse lookup, and only when this run built one."""
        desired_facts = EtsyListingFacts(
            title=desired.title,
            description=desired.description,
            tags=desired.tags,
            materials=desired.materials,
            shop_section=desired.shop_section,
            shipping_profile=desired.shipping_profile,
        )
        live_facts = None
        if live is not None:
            catalog = desired.catalog
            live_facts = EtsyListingFacts(
                title=live.title,
                description=live.description,
                tags=live.tags,
                materials=live.materials,
                shop_section=catalog.shop_section_title(live.shop_section_id) if catalog else None,
                shipping_profile=(
                    catalog.shipping_profile_title(live.shipping_profile_id) if catalog else None
                ),
            )
        return EtsyListingSnapshot(desired=desired_facts, live=live_facts)

    def apply(
        self,
        ctx: RunContext,
        desired: EtsyListingDesired,
        applied: AppliedEtsyListing | None,
        live: EtsyListing | None,
        lock: Lockfile,
    ) -> StageApplyResult:
        del applied
        listing_id = require_etsy_listing_id(lock, to="patch the listing")

        shop_id = ctx.workspace.defaults.etsy.require_shop_id()
        ctx.emit(f"patching Etsy listing {listing_id}")
        body = desired.patch_body()
        # Birth-only: Etsy will not re-draft, and activating a draft is
        # Shop Manager's (PRD non-goal 1). A desired state computed from
        # yaml must not ride along on a listing that is still a draft.
        if live is not None and live.state == "draft":
            body.pop("state", None)
        ctx.require_etsy().update_listing(shop_id, listing_id, body)

        return StageApplyResult(applied=desired.applied().model_dump(mode="json"))


def _desired_state(
    lifecycle: str | None, applied: AppliedEtsyListing | None
) -> Literal["active", "inactive"] | None:
    if lifecycle == "retired":
        return "inactive"
    if lifecycle == "renew":
        return "active"
    if lifecycle is None and applied is not None and applied.state == "inactive":
        return "active"
    return None


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
    "state",
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


def _drift(
    was: AppliedEtsyListing | None, live: EtsyListing | None, catalog: EtsyShopCatalog | None
) -> tuple[Drift, ...]:
    """What changed on Etsy since the last apply -- includes Printify
    re-attaching its own shipping profile after a republish (risk 13,
    decision 7).

    ``catalog`` names a drifted id's *live* side (A30): the *last-applied*
    side already has a name on ``was`` (``shop_section``, ``shipping_profile``,
    or ``return_policy``'s own fields), since this stage stores the name
    beside the id it resolved from. Only the id a fresh ``GET`` returned has
    none, and naming it costs the lookup nothing the catalog had not already
    fetched resolving ``desired()`` (see the three ``EtsyShopCatalog`` methods
    this calls).
    """
    if was is None or live is None:
        return ()

    found: list[Drift] = []
    for path, ours, theirs in (
        ("title", was.title, live.title),
        ("who_made", was.who_made, live.who_made),
        ("when_made", was.when_made, live.when_made),
        ("is_supply", was.is_supply, live.is_supply),
        ("should_auto_renew", was.should_auto_renew, live.should_auto_renew),
    ):
        change = drift(path, ours, theirs)
        if change is not None:
            found.append(change)

    # `description` kept out of the loop above only because it is long
    # enough that a label would be redundant with the value itself -- unlike
    # the three below, whose live side is otherwise a bare id.
    description_drift = drift("description", was.description, live.description)
    if description_drift is not None:
        found.append(description_drift)

    for id_path, our_id, their_id, last_label, live_label in (
        (
            "shop_section_id",
            was.shop_section_id,
            live.shop_section_id,
            was.shop_section,
            catalog.shop_section_title(live.shop_section_id) if catalog else None,
        ),
        (
            "shipping_profile_id",
            was.shipping_profile_id,
            live.shipping_profile_id,
            was.shipping_profile,
            catalog.shipping_profile_title(live.shipping_profile_id) if catalog else None,
        ),
        (
            "return_policy_id",
            was.return_policy_id,
            live.return_policy_id,
            was.return_policy.describe(),
            catalog.return_policy_label(live.return_policy_id) if catalog else None,
        ),
    ):
        change = drift(
            id_path, our_id, their_id, last_applied_label=last_label, live_label=live_label
        )
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
                last_applied_label=", ".join(sorted(was.production_partners)) or None,
                live_label=", ".join(
                    sorted(
                        partner.partner_name or str(partner.production_partner_id)
                        for partner in live.production_partners
                    )
                )
                or None,
            )
        )

    return tuple(found)
