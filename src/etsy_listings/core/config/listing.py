"""``listings/{name}/listing.yaml``: everything commercial and creative, configuration layering."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    ValidationError,
    ValidationInfo,
    model_validator,
)

from etsy_listings.core.config.description import DescriptionConfig
from etsy_listings.core.config.errors import ConfigLoadError, format_validation_error
from etsy_listings.core.config.media import (
    MAX_IMAGES,
    MAX_VIDEOS,
    MediaKind,
    UnknownMediaTypeError,
    media_kind,
)
from etsy_listings.core.config.media import MediaEntry as MediaEntry
from etsy_listings.core.config.media import TemplateMediaEntry as TemplateMediaEntry
from etsy_listings.core.config.money import Money, PriceField, require_currency
from etsy_listings.core.config.pricing_plan import PricingPlan

EMPTY_DRAFT: Final[dict[str, Any]] = {
    "garment_profile": "",
    "design": {},
    "colors": [],
    "brief": "",
    "prices": {},
    "pricing_plan": None,
    "price_overrides": {},
    "artwork": {},
    "etsy": {},
    "media": [],
}
"""A new listing before anything has been chosen: nothing set, nothing invented.

Deliberately *not* ``newcmd.logic.build_listing_stub``, which fills in a design,
a garment profile and a pricing plan. The CLI's ``new`` picker can, because it
asked the questions first; the editor opens before any of them have been asked,
and inventing an answer there would show the user a value they never picked.
"""

MAX_TAGS = 13
MAX_TAG_LENGTH = 20
MAX_TITLE_LENGTH = 140


def _coerce_design(raw: Any) -> dict[str, str]:  # noqa: ANN401 - pydantic validator boundary
    """A bare path is shorthand for the common single-artwork case -- it
    normalises to one entry, so the artwork resolver's "sole key" rule
    picks it with no other machinery involved."""
    if isinstance(raw, str):
        return {"default": raw}
    result: dict[str, str] = raw
    return result


DesignField = Annotated[dict[str, str], BeforeValidator(_coerce_design)]
"""Artwork key -> workspace-relative design path. A design needing different
ink for light vs dark shirts carries more than one entry, conventionally keyed
``on-light``/``on-dark``; resolution order lives in the render stage
(engine/stages/render.py), since it needs the garment profile and template
too."""


def _check_gallery(media: list[MediaEntry]) -> None:
    """`media:` is the gallery in order, and these are the layouts
    Etsy cannot show at all -- malformed rather than incomplete, so
    they refuse the write instead of waiting in the issues banner.

    Position 1 is the thumbnail and Etsy only ever puts an image there. Etsy
    pins the featured video at position 2 (decision 9), so a listing with any
    video has one there; the second may sit anywhere after it. Images and
    videos have separate caps because Etsy counts them apart.
    """
    try:
        kinds: list[MediaKind] = [media_kind(entry) for entry in media]
    except UnknownMediaTypeError as exc:
        raise ValueError(str(exc)) from exc

    images = kinds.count("image")
    if images > MAX_IMAGES:
        raise ValueError(f"media has {images} images, over Etsy's {MAX_IMAGES}-image limit")
    videos = [entry for entry, kind in zip(media, kinds, strict=True) if kind == "video"]
    if len(videos) > MAX_VIDEOS:
        raise ValueError(
            f"media has {len(videos)} videos, over Etsy's {MAX_VIDEOS}-video limit: "
            f"{', '.join(map(str, videos))}"
        )
    if not videos:
        return
    if kinds[0] == "video":
        raise ValueError(
            f"media position 1 is the thumbnail and must be an image, not the video "
            f"{media[0]!s}; put an image first and the video at position 2"
        )
    if kinds[1] != "video":
        raise ValueError(
            f"media has a video ({videos[0]!s}) but position 2 is not one; Etsy shows the "
            f"featured video at position 2, so move a video there"
        )


def check_production_fields(
    *,
    colors: list[str],
    prices: Mapping[str, Money],
    price_overrides: Mapping[str, Mapping[str, Money]],
    media: list[MediaEntry],
    currency: str | None,
) -> None:
    """The structural rules over the fields a listing and a listing template
    both carry: prices in the workspace's currency, a gallery Etsy can
    show, and no override or media entry for a colour that is not on sale.

    One function rather than a copy in each model, because a listing template
    is instantiated *into* a listing: a rule stated twice here is a template
    that saves and then makes listings that will not load."""
    if currency:
        for size, price in prices.items():
            require_currency(price, currency, f"prices.{size}")
        for color, overrides in price_overrides.items():
            for size, price in overrides.items():
                require_currency(price, currency, f"price_overrides.{color}.{size}")

    _check_gallery(media)

    for color in price_overrides:
        if color not in colors:
            raise ValueError(f"price_overrides has an entry for {color!r}, which is not in colors")

    for entry in media:
        if (
            isinstance(entry, TemplateMediaEntry)
            and entry.colour is not None
            and entry.colour not in colors
        ):
            raise ValueError(f"media references colour {entry.colour!r}, which is not in colors")


class EtsyListingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    description: DescriptionConfig = DescriptionConfig()
    tags: list[str] = []
    renewal: Literal["manual", "auto"] | None = None
    section: str | None = None
    """Which shop section this listing files under, by name. Listing
    only -- there is no shop-wide default, unlike `shipping_profile` below:
    a section is a fact about this listing, and a shop-wide default would be
    right for the first listing and wrong from the second onwards."""
    shipping_profile: str | None = None
    """Overrides `shop.yaml`'s `etsy.listing_defaults.shipping_profile`, by
    name."""
    variation_images: str | None = None
    """The `colour-matrix` template whose renders become this listing's
    per-colour swatches. Names the template rather than a bare
    `true`, because media order would otherwise silently decide which
    template supplies them when a listing carries more than one. Absent
    means the feature is off for this listing."""

    @model_validator(mode="before")
    @classmethod
    def _reject_listing_materials(cls, value: Any) -> Any:
        """Composition is shared by a garment, not independently owned by
        each listing. Name the migration rather than presenting the generic
        ``extra_forbidden`` error to an existing workspace."""
        if isinstance(value, Mapping) and "materials" in value:
            raise ValueError(
                "etsy.materials has moved to the garment profile; remove it from this "
                "listing and set garment-profiles/<name>.yaml's materials instead"
            )
        return value

    @model_validator(mode="after")
    def _validate_concrete_values(self) -> EtsyListingConfig:
        if len(self.title) > MAX_TITLE_LENGTH:
            raise ValueError(
                f"etsy.title is {len(self.title)} characters, over Etsy's "
                f"{MAX_TITLE_LENGTH}-character limit"
            )
        if len(self.tags) > MAX_TAGS:
            raise ValueError(
                f"etsy.tags has {len(self.tags)} tags, over Etsy's {MAX_TAGS}-tag limit"
            )
        for tag in self.tags:
            if len(tag) > MAX_TAG_LENGTH:
                raise ValueError(
                    f"etsy.tags: {tag!r} is {len(tag)} characters, over Etsy's "
                    f"{MAX_TAG_LENGTH}-character-per-tag limit"
                )
        return self


class Listing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    garment_profile: str
    design: DesignField
    colors: list[str]
    brief: str
    prices: dict[str, PriceField] = {}
    """Per-size overrides on top of ``pricing_plan`` -- optional and partial.
    A listing with no ``pricing_plan`` must cover every size it needs here,
    exactly as before this field became optional."""
    pricing_plan: str | None = None
    """Workspace-relative path to a ``pricing-plans/*.yaml`` file, resolved
    the same way ``design`` is (not a bare name against a fixed directory,
    unlike ``garment_profile``/``media[].template``) -- see docs/reference/listing-configuration.md.
    Resolution and
    loading are the caller's job; ``Listing`` never touches ``Workspace``."""
    price_overrides: dict[str, dict[str, PriceField]] = {}
    artwork: dict[str, str] = {}
    """Explicit per-design artwork override, colour -> artwork key. Wins over
    everything else in the artwork resolution order -- the thing a human is most
    likely to actually revisit per design."""
    etsy: EtsyListingConfig = EtsyListingConfig()
    media: list[MediaEntry]
    lifecycle: Literal["retired", "deleted", "renew"] | None = None
    """Desired end-of-life. Omitted on a working listing, including
    after Un-retire. ``plan`` never writes this key; wrong verb is ``Blocked``,
    never rewritten as the right one. Named ``lifecycle``, not ``status``,
    because the listings table already has a Status column."""

    @model_validator(mode="after")
    def _validate(self, info: ValidationInfo) -> Listing:
        check_production_fields(
            colors=self.colors,
            prices=self.prices,
            price_overrides=self.price_overrides,
            media=self.media,
            currency=(info.context or {}).get("currency"),
        )
        for color in self.artwork:
            if color not in self.colors:
                raise ValueError(f"artwork has an entry for {color!r}, which is not in colors")
        return self

    @classmethod
    def empty_draft(cls, *, currency: str) -> Self:
        """:data:`EMPTY_DRAFT` as a ``Listing``: what `+ New listing` opens on.

        Answers ``Self`` rather than ``Listing`` because the UI's
        ``ListingDetail`` *is* a ``Listing`` with display fields hung off it.

        There is no ``draft()`` beside this one any more. This model used to
        hold one rule an unsaved draft was allowed to fail -- "set
        ``pricing_plan`` or ``prices``" -- which made a document that merely
        had nothing chosen yet indistinguishable from one that was malformed.
        ADR-0043 moved that refusal to where the other seven incompletenesses
        already lived: `config/listing_validation.py` explains it in the
        banner, and `engine/stages/gates.py` turns it into the `Blocked` that
        stops a deploy. What this model still refuses is a document that
        contradicts itself -- a ``media[].colour`` naming a colour the listing
        does not sell, a price in the wrong currency, a title over Etsy's
        limit -- and those are failures about a field somebody filled in, not
        about one they have not reached.
        """
        return cls.model_validate(dict(EMPTY_DRAFT), context={"currency": currency})

    @classmethod
    def load(cls, path: Path, *, currency: str) -> Listing:
        if not path.is_file():
            raise ConfigLoadError(path, "listing file not found")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        try:
            return cls.model_validate(raw, context={"currency": currency})
        except ValidationError as exc:
            raise format_validation_error(path, exc) from exc

    def resolved_price(
        self, color: str, size: str, *, pricing_plan: PricingPlan | None = None
    ) -> Money:
        """``price_overrides`` > ``prices`` > the referenced pricing plan's own
        (override-then-flat) resolution. ``pricing_plan`` is an already-loaded
        object, not the ``str`` ref -- loading it is the caller's job, the same
        point ``design`` refs get resolved (see the ``pricing_plan`` field's
        docstring)."""
        return resolve_price(
            self.prices, self.price_overrides, color, size, pricing_plan=pricing_plan
        )


def resolve_price(
    prices: Mapping[str, Money],
    price_overrides: Mapping[str, Mapping[str, Money]],
    color: str,
    size: str,
    *,
    pricing_plan: PricingPlan | None = None,
) -> Money:
    """The one precedence rule for a price, for a listing and for a listing
    template alike (ADR-0047 reuses the price models, so it reuses their
    resolution): ``price_overrides`` > ``prices`` > the plan's own."""
    override = price_overrides.get(color, {}).get(size)
    if override is not None:
        return override
    direct = prices.get(size)
    if direct is not None:
        return direct
    if pricing_plan is not None:
        plan_price = pricing_plan.resolved_price(color, size)
        if plan_price is not None:
            return plan_price
    raise KeyError(
        f"no price for size {size!r} (colour {color!r}): not in price_overrides, "
        f"prices, or the referenced pricing plan"
    )
