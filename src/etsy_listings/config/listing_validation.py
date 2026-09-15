"""The listings UI's local-only health check (phase-5-listings-ui.md).

Answers one question: is this listing's *own* configuration complete and
self-consistent? Not "would the live shop accept it" -- that needs a real
`plan()` against Etsy/Printify (price-below-cost, shop-section validity) and
is explicitly out of scope here; a static note in the issues banner points at
`etsy-listings plan` for those instead.

Reuses `Listing`'s own pydantic validators for everything structural (money
parsing, cross-reference subsets, length limits) -- a `Listing.model_validate`
failure blocks the write outright and is surfaced by the API layer as inline
field errors, and never reaches this module. `gates.py`'s two pure checks
(`check_copy_is_concrete`, `check_design_resolution`) are reused directly
rather than re-implemented. Everything else here is new: cross-references
between a listing's own fields and the garment profile / template catalog it
names.

Deliberately not a `Stage`: stages diff local vs. remote state, and this only
ever looks at local config, callable synchronously on every autosave with no
network I/O and no workspace.

Structured as a list of independent check functions rather than a monolith,
since more checks are expected later (see the module's own docstring in
phase-5-listings-ui.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from etsy_listings.config.garment_profile import GarmentProfile
from etsy_listings.config.listing import Listing, TemplateMediaEntry
from etsy_listings.engine.stages.gates import check_copy_is_concrete, check_design_resolution

Severity = Literal["block", "warn"]
Tab = Literal["variants", "images", "details"]


@dataclass(frozen=True)
class Issue:
    """One entry in the editor's issues banner -- the exact shape the design
    mockup's `issues`/`raw` array already expects, so only the source of the
    list changes: from a hardcoded demo array to this module's real output."""

    severity: Severity
    tab: Tab
    where: str
    message: str


@dataclass(frozen=True)
class TemplateInfo:
    """The two facts a listing's media can be checked against, per template it
    references -- a slice of the calibrator's `TemplateSummary`
    (`GET /api/templates`), so kind and colours are the real ones on disk,
    never re-derived here. A template this listing names that isn't in the
    map at all (renamed or deleted from under it) is not this module's check
    to make -- nothing in the agreed rule list covers it."""

    kind: Literal["colour-matrix", "multiple", "single"]
    colours: frozenset[str]


_PLACEHOLDER_COPY = "placeholder -- passes check_copy_is_concrete's own test"
"""Stands in for whichever of title/description isn't being asked about below,
so a failure in one is never misreported against the other -- `Listing`'s
model already guarantees neither is blank or the literal GENERATE sentinel by
the time this only ever needs to isolate which one is."""


def _check_copy(listing: Listing) -> list[Issue]:
    issues: list[Issue] = []
    title_blocked = check_copy_is_concrete(title=listing.etsy.title, description=_PLACEHOLDER_COPY)
    if title_blocked is not None:
        issues.append(Issue("block", "details", "Listing Details › Title", title_blocked.message))
    description_blocked = check_copy_is_concrete(
        title=_PLACEHOLDER_COPY, description=listing.etsy.description
    )
    if description_blocked is not None:
        issues.append(
            Issue("block", "details", "Listing Details › Description", description_blocked.message)
        )
    return issues


def _check_design(design_paths: Mapping[str, Path], profile: GarmentProfile) -> list[Issue]:
    issues: list[Issue] = []
    for key, path in design_paths.items():
        blocked = check_design_resolution(path, profile)
        if blocked is not None:
            where = "Design" if key == "default" else f"Design ({key})"
            issues.append(Issue("block", "variants", where, blocked.message))
    return issues


def _check_media_present(listing: Listing) -> list[Issue]:
    if listing.media:
        return []
    return [
        Issue(
            "block",
            "images",
            "Listing Images",
            "No listing images -- Etsy will not publish a listing without one.",
        )
    ]


def _check_colours_enabled(listing: Listing) -> list[Issue]:
    if listing.colors:
        return []
    return [
        Issue(
            "block",
            "variants",
            "Variants › Colours",
            "No colours enabled -- the product would have no variants to sell.",
        )
    ]


def _check_garment_profile_exists(
    listing: Listing, garment_profile_names: Iterable[str]
) -> list[Issue]:
    if listing.garment_profile in set(garment_profile_names):
        return []
    return [
        Issue(
            "block",
            "variants",
            "Variants › Garment profile",
            f"Garment profile {listing.garment_profile!r} does not exist in this workspace.",
        )
    ]


def _check_template_kind_colour_match(
    listing: Listing, templates: Mapping[str, TemplateInfo]
) -> list[Issue]:
    issues: list[Issue] = []
    for entry in listing.media:
        if not isinstance(entry, TemplateMediaEntry):
            continue
        info = templates.get(entry.template)
        if info is None:
            continue
        where = f"Listing Images › {entry.template}"
        if info.kind == "colour-matrix" and entry.colour is None:
            issues.append(
                Issue(
                    "block",
                    "images",
                    where,
                    f"{entry.template!r} is a colour-matrix template and needs a colour.",
                )
            )
        elif info.kind != "colour-matrix" and entry.colour is not None:
            issues.append(
                Issue(
                    "block",
                    "images",
                    where,
                    f"{entry.template!r} is a {info.kind} template and must not name a colour.",
                )
            )
    return issues


def _check_variation_images(listing: Listing, templates: Mapping[str, TemplateInfo]) -> list[Issue]:
    name = listing.etsy.variation_images
    if name is None:
        return []
    referenced = {
        entry.template for entry in listing.media if isinstance(entry, TemplateMediaEntry)
    }
    if name not in referenced:
        return [
            Issue(
                "block",
                "images",
                "Listing Images",
                f"{name!r} is set as the colour-swatch template, but nothing in media: "
                f"references it.",
            )
        ]
    covered = {
        entry.colour
        for entry in listing.media
        if isinstance(entry, TemplateMediaEntry) and entry.template == name and entry.colour
    }
    missing = [colour for colour in listing.colors if colour not in covered]
    if not missing:
        return []
    return [
        Issue(
            "warn",
            "images",
            "Listing Images",
            f"{name!r} has no image for: {', '.join(missing)} -- those colours will have "
            f"no Etsy swatch.",
        )
    ]


def _check_tags(listing: Listing) -> list[Issue]:
    if isinstance(listing.etsy.tags, list) and not listing.etsy.tags:
        return [
            Issue(
                "warn",
                "details",
                "Listing Details › Tags",
                "No tags -- Etsy search has nothing to match this listing on.",
            )
        ]
    return []


def _check_colours_in_garment_profile(
    listing: Listing, profile: GarmentProfile | None
) -> list[Issue]:
    if profile is None:
        return []
    missing = [colour for colour in listing.colors if colour not in profile.colors]
    if not missing:
        return []
    return [
        Issue(
            "warn",
            "variants",
            "Variants › Colours",
            f"{', '.join(missing)} not classified light/dark in the garment profile -- "
            f"Printify may not offer {'it' if len(missing) == 1 else 'them'} (best-effort "
            f"check only).",
        )
    ]


def check_listing(
    listing: Listing,
    *,
    garment_profile: GarmentProfile | None,
    garment_profile_names: Iterable[str],
    design_paths: Mapping[str, Path],
    templates: Mapping[str, TemplateInfo],
) -> list[Issue]:
    """Every business-level issue with ``listing``, assuming it already passed
    `Listing.model_validate` -- structural failures are the API layer's to
    catch and never reach here.

    ``garment_profile`` is ``None`` when ``listing.garment_profile`` does not
    resolve to a real file; the profile-dependent checks (design resolution,
    colour classification) have nothing to check against then and are
    skipped, leaving :func:`_check_garment_profile_exists`'s block as the one
    issue that matters.
    """
    issues: list[Issue] = []
    issues += _check_garment_profile_exists(listing, garment_profile_names)
    issues += _check_colours_enabled(listing)
    issues += _check_media_present(listing)
    issues += _check_copy(listing)
    if garment_profile is not None:
        issues += _check_design(design_paths, garment_profile)
        issues += _check_colours_in_garment_profile(listing, garment_profile)
    issues += _check_template_kind_colour_match(listing, templates)
    issues += _check_variation_images(listing, templates)
    issues += _check_tags(listing)
    return issues
