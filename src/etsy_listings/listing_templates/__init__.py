"""Listing templates: a listing's reusable production settings, saved as their
own workspace resource (A35, A36; spec *Listing templates*).

The model is `config.ListingTemplate` and the files are `Workspace`'s
(``listing_template_*``). This package is what happens between them: turning
a listing -- or another listing template -- into a draft
(:func:`from_listing`, :func:`from_template`), judging it complete, and
writing it (:func:`save`), which is the only step that touches the disk.

Deliberately withheld: instantiating a template into listings. That is batch
creation's (A39), which freezes a template before it creates anything.
"""

from etsy_listings.listing_templates.check import template_issues
from etsy_listings.listing_templates.convert import (
    AssetCopy,
    ListingTemplateDraft,
    ListingTemplateExistsError,
    UnreadableAssetError,
    draft_issues,
    from_listing,
    from_template,
    save,
)

__all__ = [
    # A draft: the document, and the files it will own.
    "ListingTemplateDraft",
    "AssetCopy",
    "from_listing",
    "from_template",
    # Completeness (A36), for a draft and for a named template.
    "draft_issues",
    "template_issues",
    # The one write, and its two refusals.
    "save",
    "ListingTemplateExistsError",
    "UnreadableAssetError",
]
