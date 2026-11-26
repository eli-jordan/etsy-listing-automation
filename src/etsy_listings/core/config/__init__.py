"""The models for the workspace's commercial and creative files, and the value
types they are built from.

``shop.yaml`` ( :class:`Defaults`), ``garment-profiles/*.yaml``
( :class:`GarmentProfile`), ``listings/*/listing.yaml`` ( :class:`Listing`),
``listing-templates/*/template.yaml`` ( :class:`ListingTemplate`, ADR-0047),
``pricing-plans/**.yaml``
( :class:`PricingPlan`) and ``exceptions.yaml``. Every one of them is loaded
*by path* -- this module has no idea where any of those files live, which is
``workspace``'s job. It owns no rendering or catalog workflow.

A *mockup* template's ``template.yaml`` is deliberately not here: it is render
geometry, so its models live in:mod:`etsy_listings.core.render`.

``settings.Settings``, ``AiSettings`` and ``AiProviderSettings`` describe
workspace tuning and ADR-0056's provider preferences. Import them directly
from ``settings``; this initializer deliberately does not re-export them.

``template_positions.TemplatePositions``, ``BoxPosition`` and ``PlacementPositions``
describe a listing's absolute mockup geometry (ADR-0058); import from that module.
They reuse ``render.config.BoundingBox`` rather than duplicating its schema.
``settings.TemplatePositionLimits`` (``scale: PositionScaleLimits``, ``offset``,
``rotation``) is ``Settings.template_positions``; the render pose functions
accept it directly. ``listing_validation.check_template_positions`` takes a
``Listing``, a name-to-template mapping, these limits and optional ``name=``;
it returns blocking Images issues without changing the stored boxes.
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
from etsy_listings.core.config.money import Money, require_currency
from etsy_listings.core.config.pricing_plan import PricingPlan
from etsy_listings.core.config.secrets import (
    ANTHROPIC_KEY_VAR,
    PRINTIFY_TOKEN_VAR,
    MissingCredentialError,
    Secrets,
)
from etsy_listings.core.config.slug import ColourExceptions, SlugCollisionError, slug_map, slugify

__all__ = [
    "ANTHROPIC_KEY_VAR",
    "MAX_IMAGES",
    "MAX_VIDEOS",
    "PRINTIFY_TOKEN_VAR",
    "ColourExceptions",
    "ConfigLoadError",
    "Defaults",
    "DescriptionConfig",
    "EtsyListingConfig",
    "GarmentProfile",
    "Listing",
    "ListingTemplate",
    "MarketWeights",
    "MediaEntry",
    "MediaKind",
    "MissingCredentialError",
    "Money",
    "PricingPlan",
    "PrintArea",
    "ProbeFailure",
    "Secrets",
    "SlugCollisionError",
    "TemplateMediaEntry",
    "UnknownMediaTypeError",
    "VideoFacts",
    "compose_description",
    "format_validation_error",
    "load_exceptions",
    "media_kind",
    "require_currency",
    "slug_map",
    "slugify",
]
