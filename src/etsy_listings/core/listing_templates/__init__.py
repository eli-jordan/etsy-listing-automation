"""Listing templates: a listing's reusable production settings, saved as their
own workspace resource (ADR-0047, template completeness; spec *Listing templates*).

The model is `config.ListingTemplate` and the files are `Workspace`'s
(``listing_template_*``). This package is what happens between them: turning
a listing -- or another listing template -- into a draft
(:func:`from_listing`, :func:`from_template`), judging it complete, and
writing it (:func:`save`). FrozenListingTemplate captures the document,
owned assets and saved-at time together for a staging session.

Deliberately withheld: instantiating a template into listings. That is
`batches`', which freezes a template before it creates anything and
asks FrozenListingTemplate to capture, carry and check its owned content.
"""

from etsy_listings.core.listing_templates.check import template_issues
from etsy_listings.core.listing_templates.convert import (
    AssetCopy,
    ListingTemplateDraft,
    ListingTemplateExistsError,
    UnreadableAssetError,
    draft_issues,
    from_listing,
    from_template,
    owned_refs,
    save,
)
from etsy_listings.core.listing_templates.frozen import FrozenListingTemplate, TemplateLock

__all__ = [
    "FrozenListingTemplate",
    "TemplateLock",
    # A draft: the document, and the files it will own.
    "ListingTemplateDraft",
    "AssetCopy",
    "from_listing",
    "from_template",
    "owned_refs",
    # Completeness, for a draft and for a named template.
    "draft_issues",
    "template_issues",
    # The one write, and its two refusals.
    "save",
    "ListingTemplateExistsError",
    "UnreadableAssetError",
]
