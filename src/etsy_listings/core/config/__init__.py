"""The models for the workspace's commercial and creative files, and the value
types they are built from.

``shop.yaml`` ( :class:`Defaults`), ``garment-profiles/*.yaml``
( :class:`GarmentProfile`), ``listings/*/listing.yaml`` ( :class:`Listing`),
``listing-templates/*/template.yaml`` ( :class:`ListingTemplate`, ADR-0047),
``pricing-plans/**.yaml``
( :class:`PricingPlan`) and ``exceptions.yaml``. Every one of them is loaded
*by path* -- this module has no idea where any of those files live, which is
``workspace``'s job, and it knows nothing about ``render`` or ``catalog``.

A *mockup* template's ``template.yaml`` is deliberately not here: it is render
geometry, so its models live in:mod:`etsy_listings.core.render`.
"""

from etsy_listings.core.config.defaults import Defaults
from etsy_listings.core.config.description import DescriptionConfig, compose_description
from etsy_listings.core.config.errors import ConfigLoadError, format_validation_error
from etsy_listings.core.config.exceptions import load_exceptions
from etsy_listings.core.config.garment_profile import GarmentProfile, PrintArea
from etsy_listings.core.config.listing import EtsyListingConfig, Listing
from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.config.market_weights import MarketWeights
from etsy_listings.core.config.media import (
    MAX_IMAGES,
    MAX_VIDEOS,
    MediaEntry,
    MediaKind,
    ProbeFailure,
    TemplateMediaEntry,
    UnknownMediaTypeError,
    VideoFacts,
    media_kind,
)
from etsy_listings.core.config.money import Money, PriceField, require_currency
from etsy_listings.core.config.pricing_plan import PricingPlan
from etsy_listings.core.config.secrets import (
    ANTHROPIC_KEY_VAR,
    PRINTIFY_TOKEN_VAR,
    MissingCredentialError,
    Secrets,
)
from etsy_listings.core.config.slug import ColourExceptions, SlugCollisionError, slug_map, slugify

__all__ = [
    # One class per config file.
    "Defaults",
    "Listing",
    "ListingTemplate",
    "MarketWeights",
    "PricingPlan",
    "GarmentProfile",
    "EtsyListingConfig",
    "MediaEntry",
    "TemplateMediaEntry",
    "PrintArea",
    # What a media: entry is, and the gallery's caps.
    "MediaKind",
    "media_kind",
    "UnknownMediaTypeError",
    "MAX_IMAGES",
    "MAX_VIDEOS",
    "VideoFacts",
    "ProbeFailure",
    # The description model and its one shared join rule (AI SEO plan PR2).
    "DescriptionConfig",
    "compose_description",
    # Money. Every price carries an explicit currency.
    "Money",
    "PriceField",
    "require_currency",
    # Colour slugification, and the sparse exceptions file behind it.
    "ColourExceptions",
    "SlugCollisionError",
    "slug_map",
    "slugify",
    "load_exceptions",
    # Credentials. Read from the *workspace*.env, never this repo.
    "Secrets",
    "MissingCredentialError",
    "ANTHROPIC_KEY_VAR",
    "PRINTIFY_TOKEN_VAR",
    # Actionable load failures: never a bare pydantic traceback.
    "ConfigLoadError",
    "format_validation_error",
]
