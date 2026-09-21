"""``listings/{name}/listing.yaml``: everything commercial and creative, PRD 8a."""

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

from etsy_listings.config.errors import ConfigLoadError, format_validation_error
from etsy_listings.config.money import Money, PriceField, require_currency
from etsy_listings.config.pricing_plan import PricingPlan

GENERATE: Final = "<generate>"

_DRAFT: Final = "unsaved_draft"
"""Validation-context key set by :meth:`Listing.draft` and by nothing else.

It waives exactly one rule -- "set ``pricing_plan`` or ``prices``" -- for a
candidate the editor is still assembling, and it is private so that waiving it
stays a decision made here. ``Listing.load``, the UI's autosave PATCH and its
create POST all go through a plain ``model_validate``, so nothing incomplete can
reach disk; ``tests/unit/test_draft_context_is_private.py`` keeps the key from
being spelled anywhere else, the same way ``test_no_bare_cv2.py`` keeps a
default-argument ``cv2`` call from creeping back in.
"""

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

MAX_MEDIA_ENTRIES = 20
MAX_TAGS = 13
MAX_TAG_LENGTH = 20
MAX_TITLE_LENGTH = 140


def _coerce_design(raw: Any) -> dict[str, str]:  # noqa: ANN401 - pydantic validator boundary
    """A bare path is shorthand for the common single-artwork case -- it
    normalises to one entry, so artwork resolution's "sole key" rule (item 2)
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


class TemplateMediaEntry(BaseModel):
    """Always-explicit template reference -- there is no bare-colour
    shorthand. ``colour`` is required when the referenced template is
    ``colour-matrix`` kind (which colour's photo) and must be omitted for
    ``multiple``/``single`` kind (exactly one output each, nothing to
    disambiguate)."""

    model_config = ConfigDict(extra="forbid")

    template: str
    colour: str | None = None


MediaEntry = TemplateMediaEntry | str
"""Either an explicit template reference, or a bare path string to a shared
asset under ``common-media/``."""


class EtsyListingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    description: str = ""
    tags: list[str] | Literal["<generate>"] = GENERATE
    renewal: Literal["manual", "auto"] | None = None
    section: str | None = None
    """Which shop section this listing files under, by name (PRD 53). Listing
    only -- there is no shop-wide default, unlike `shipping_profile` below:
    a section is a fact about this listing, and a shop-wide default would be
    right for the first listing and wrong from the second onwards."""
    shipping_profile: str | None = None
    """Overrides `shop.yaml`'s `etsy.listing_defaults.shipping_profile`, by
    name (PRD 54)."""
    variation_images: str | None = None
    """The `colour-matrix` template whose renders become this listing's
    per-colour swatches (PRD 56). Names the template rather than a bare
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
        if self.title != GENERATE and len(self.title) > MAX_TITLE_LENGTH:
            raise ValueError(
                f"etsy.title is {len(self.title)} characters, over Etsy's "
                f"{MAX_TITLE_LENGTH}-character limit"
            )
        if isinstance(self.tags, list):
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
    unlike ``garment_profile``/``media[].template``) -- see PRD 34. Resolution and
    loading are the caller's job; ``Listing`` never touches ``Workspace``."""
    price_overrides: dict[str, dict[str, PriceField]] = {}
    artwork: dict[str, str] = {}
    """Explicit per-design artwork override, colour -> artwork key. Wins over
    everything else in resolution order (item 2) -- the thing a human is most
    likely to actually revisit per design."""
    etsy: EtsyListingConfig = EtsyListingConfig()
    media: list[MediaEntry]
    lifecycle: Literal["retired", "deleted", "renew"] | None = None
    """Desired end-of-life (PRD 62). Omitted on a working listing, including
    after Un-retire. ``plan`` never writes this key; wrong verb is ``Blocked``,
    never rewritten as the right one. Named ``lifecycle``, not ``status``,
    because the listings table already has a Status column."""

    @model_validator(mode="after")
    def _validate(self, info: ValidationInfo) -> Listing:
        context = info.context or {}
        expected_currency = context.get("currency")
        if expected_currency:
            for size, price in self.prices.items():
                require_currency(price, expected_currency, f"prices.{size}")
            for color, overrides in self.price_overrides.items():
                for size, price in overrides.items():
                    require_currency(price, expected_currency, f"price_overrides.{color}.{size}")

        if len(self.media) > MAX_MEDIA_ENTRIES:
            raise ValueError(
                f"media has {len(self.media)} entries, over Etsy's {MAX_MEDIA_ENTRIES}-image limit"
            )

        for color in self.price_overrides:
            if color not in self.colors:
                raise ValueError(
                    f"price_overrides has an entry for {color!r}, which is not in colors"
                )

        for color in self.artwork:
            if color not in self.colors:
                raise ValueError(f"artwork has an entry for {color!r}, which is not in colors")

        for entry in self.media:
            if (
                isinstance(entry, TemplateMediaEntry)
                and entry.colour is not None
                and entry.colour not in self.colors
            ):
                raise ValueError(
                    f"media references colour {entry.colour!r}, which is not in colors"
                )

        return self

    @model_validator(mode="after")
    def _require_a_price_source(self, info: ValidationInfo) -> Listing:
        """A listing has to be priced somehow -- unless it is a draft.

        Its own rule rather than a clause in :meth:`_validate` because it is the
        one rule an unsaved draft is allowed to fail: everything else in this
        model is either satisfied by an empty value or is a statement about
        fields that *are* filled in, so this is the only thing standing between
        "nothing chosen yet" and a document that parses.
        `config/listing_validation.py` reports the same gap as a block issue --
        this model owns the refusal, that module owns the explanation.
        """
        if (info.context or {}).get(_DRAFT):
            return self
        if self.pricing_plan is None and not self.prices:
            raise ValueError("listing has no pricing_plan and no prices -- set at least one")
        return self

    @classmethod
    def draft(cls, raw: Mapping[str, Any], *, currency: str) -> Self:
        """A candidate the listings editor is still assembling.

        Structurally a real ``Listing`` -- ``media[].colour`` must still name a
        colour the listing sells, ``price_overrides``/``artwork`` keys must
        still be colours, a concrete title must still fit Etsy's limit, prices
        must still carry the shop's currency -- because those are exactly the
        failures the editor shows inline while the listing is unnamed. Only the
        price-source rule is waived, and only here.

        Answers ``Self`` rather than ``Listing`` because the UI's
        ``ListingDetail`` *is* a ``Listing`` with display fields hung off it,
        and re-deciding this rule while merely describing a listing would refuse
        to render the one state the rule was waived for.
        """
        return cls.model_validate(dict(raw), context={"currency": currency, _DRAFT: True})

    @classmethod
    def empty_draft(cls, *, currency: str) -> Self:
        """:data:`EMPTY_DRAFT` as a ``Listing``: what `+ New listing` opens on."""
        return cls.draft(EMPTY_DRAFT, currency=currency)

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
        override = self.price_overrides.get(color, {}).get(size)
        if override is not None:
            return override
        direct = self.prices.get(size)
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
