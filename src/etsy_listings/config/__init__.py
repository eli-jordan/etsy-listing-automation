"""The models for the workspace's commercial and creative files, and the value
types they are built from.

``shop.yaml`` (:class:`Defaults`), ``garment-profiles/*.yaml``
(:class:`GarmentProfile`), ``listings/*/listing.yaml`` (:class:`Listing`),
``pricing-plans/**.yaml``
(:class:`PricingPlan`) and ``exceptions.yaml``. Every one of them is loaded
*by path* -- this module has no idea where any of those files live, which is
``workspace``'s job, and it knows nothing about ``render`` or ``catalog``.

``template.yaml`` is deliberately not here: it is render geometry, so its
models live in :mod:`etsy_listings.render`.
"""

from etsy_listings.config.defaults import Defaults
from etsy_listings.config.description import DescriptionConfig, compose_description
from etsy_listings.config.errors import ConfigLoadError, format_validation_error
from etsy_listings.config.exceptions import load_exceptions
from etsy_listings.config.garment_profile import GarmentProfile, PrintArea
from etsy_listings.config.listing import EtsyListingConfig, Listing
from etsy_listings.config.media import (
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
from etsy_listings.config.money import Money, PriceField, require_currency
from etsy_listings.config.pricing_plan import PricingPlan
from etsy_listings.config.secrets import (
    ANTHROPIC_KEY_VAR,
    PRINTIFY_TOKEN_VAR,
    MissingCredentialError,
    Secrets,
)
from etsy_listings.config.slug import ColourExceptions, SlugCollisionError, slug_map, slugify

__all__ = [
    # One class per config file.
    "Defaults",
    "Listing",
    "PricingPlan",
    "GarmentProfile",
    "EtsyListingConfig",
    "MediaEntry",
    "TemplateMediaEntry",
    "PrintArea",
    # What a media: entry is, and the gallery's caps (PRD 72).
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
    # Money. Every price carries an explicit currency (PRD 24).
    "Money",
    "PriceField",
    "require_currency",
    # Colour slugification, and the sparse exceptions file behind it (PRD 7a).
    "ColourExceptions",
    "SlugCollisionError",
    "slug_map",
    "slugify",
    "load_exceptions",
    # Credentials. Read from the *workspace* .env, never this repo.
    "Secrets",
    "MissingCredentialError",
    "ANTHROPIC_KEY_VAR",
    "PRINTIFY_TOKEN_VAR",
    # Actionable load failures: never a bare pydantic traceback.
    "ConfigLoadError",
    "format_validation_error",
]
