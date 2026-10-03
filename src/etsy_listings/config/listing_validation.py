"""Every reason a listing cannot run, as far as its own files can tell.

Answers one question: is this listing's *own* configuration complete and
self-consistent? Not "would the live shop accept it" -- that needs a real
`plan()` against Etsy/Printify (price-below-cost, shop-section validity) and
is explicitly out of scope here; a static note in the issues banner points at
`etsy-listings plan` for those instead.

**One module, two readers.** The editor's issues banner asks for all of them
(`check_listing`); a stage asks for the two or three it ships and turns each
into a `Blocked` through the adapter in `engine/stages/gates.py`. They used to
be two *modules*, and the same rule was spelled in both: a whitespace-only
`garment_profile` passed the engine's pre-flight and failed the editor's, so
the banner and `apply` disagreed about one file on disk. A rule stated twice
is a rule that will diverge, so each is stated here once -- predicate, message
and all -- and the two readers differ only in what they do with it.

The three rules `gates.py` used to own (`check_design_resolution`,
`check_garment_profile_chosen`, `check_copy_is_concrete`) are here for the same
reason the other eleven are, and the dependency now points the way the rest of
the codebase does: `engine` reads `config`, never the reverse.

Reuses `Listing`'s own pydantic validators for everything structural (money
parsing, cross-reference subsets, length limits) -- a `Listing.model_validate`
failure blocks the write outright and is surfaced by the API layer as inline
field errors, and never reaches this module.

Deliberately not a `Stage`: stages diff local vs. remote state, and this only
ever looks at local config, callable synchronously on every autosave with no
network I/O and no workspace.

Structured as a list of independent check functions rather than a monolith,
since more checks are expected later (see the module's own docstring in
features/listings-ui-20260915/spec.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from PIL import Image, UnidentifiedImageError

from etsy_listings.config.garment_profile import GarmentProfile
from etsy_listings.config.listing import Listing, TemplateMediaEntry
from etsy_listings.config.listing_template import ListingTemplate
from etsy_listings.config.media import ProbeFailure, VideoFacts

Severity = Literal["block", "warn", "info"]
"""``info`` is a note about what Etsy will do, not a problem with the listing
-- the one today is that Etsy strips a video's sound. The banner shows
it quietly and `engine/stages/gates.py` never refuses on it."""
Tab = Literal["variants", "pricing", "images", "details"]

Production = Listing | ListingTemplate
"""What the production checks read: the fields a listing and a listing
template share. A check that takes one takes either, so a template is
judged by the very rules the listings made from it will be."""


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


_GARMENT_PROFILE_WHERE = "Variants › Garment profile"
_DESIGN_WHERE = "Design"
_COPY_WHERE = {"title": "Listing Details › Title", "description": "Listing Details › Description"}
_LIFECYCLE_WHERE = "lifecycle"

DELETED_ON_PUBLISHED = (
    "this listing has been published; retracting it would discard its history.\n"
    "Retire it instead -- that pauses the Etsy listing without throwing the "
    "history away."
)
RETIRED_ON_NEVER_LIVE = (
    "this listing has never been for sale; there is nothing to pause.\n"
    "Delete it instead if you want it gone."
)
MISSING_LISTING_YAML = (
    "listing.yaml is missing; a missing file is not consent to retire or "
    "delete anything.\n"
    "Restore listing.yaml. Until then this tool will not send state, retire, "
    "or delete remotes."
)

RESOLUTION_TOLERANCE = 0.9
"""A design must reach 90% of the print area on each axis.

Not slack for its own sake. The failure worth catching is the file that is a
tenth of the size; a few percent short upscales invisibly, and a gate at
exactly 100% rejects a 4000x4800 file for a 4200x4800 area -- a rule that
fires on work nobody would call wrong is a rule that gets switched off.
"""

PRINTIFY_MAX_VARIANTS = 100
"""Printify's per-product ceiling for enabled variants.

The editor can predict the configured matrix without a catalog request: every
selected colour asks for every size in the garment profile. Printify may offer
fewer cells than that, so this is advice rather than a deployment
refusal; the live catalog remains the authority on what can actually be sent.
"""


def required_design_pixels(profile: GarmentProfile) -> tuple[int, int]:
    """The smallest design ``profile`` prints: 90% of its print area on each
    axis. Public for New batch's size hint (UI doc §4)."""
    return (
        int(profile.print_area.width * RESOLUTION_TOLERANCE),
        int(profile.print_area.height * RESOLUTION_TOLERANCE),
    )


def check_design_resolution(design: Path, profile: GarmentProfile) -> list[Issue]:
    """Refuse a design that will print soft, or print its background.

    Never auto-upscaled and never converted: a silently upscaled
    design produces a blurry shirt discovered by customer complaint, which is
    the one failure mode this whole gate exists to make impossible.

    The `where` is the bare ``Design``; a multi-artwork listing's caller
    narrows it to the key that failed.
    """

    def blocked(message: str) -> list[Issue]:
        return [Issue("block", "variants", _DESIGN_WHERE, message)]

    if not design.is_file():
        return blocked(f"design file not found: {design}")

    try:
        with Image.open(design) as image:
            width, height = image.size
            mode = image.mode
    except (UnidentifiedImageError, OSError) as exc:
        return blocked(f"{design} is not readable as an image: {exc}")

    if "A" not in mode:
        return blocked(
            f"{design.name} has no alpha channel (mode {mode!r}). A print file without "
            f"transparency prints its background as a rectangle of ink on the shirt.\n"
            f"Export it as RGBA."
        )

    need_width, need_height = required_design_pixels(profile)
    if width < need_width or height < need_height:
        return blocked(
            f"{design.name} is {width}x{height}, too small for this garment's "
            f"{profile.print_area.width}x{profile.print_area.height} print area.\n"
            f"It needs at least {need_width}x{need_height} "
            f"({RESOLUTION_TOLERANCE:.0%} of the print area on each axis).\n"
            f"Re-export the design at that size or larger -- it is never upscaled "
            f"for you, because a blurry print is only ever discovered by a customer."
        )
    return []


def check_garment_profile_chosen(garment_profile: str) -> list[Issue]:
    """Refuse a listing that has not said which garment it prints on.

    The listings editor writes a listing the moment it has a name and a price
    source, so "no garment profile yet" is an ordinary state on disk rather than
    a typo -- and every stage that wants one loads it through
    ``workspace.load_garment_profile``, where an empty name reaches ``_segment``
    and raises ``InvalidNameError``. That is a plain ``ValueError``, not a
    ``UserFacingError``, so it would not merely fail this listing: it would
    unwind the stage walk and end a whole ``--all`` batch on a listing somebody
    is still filling in.

    ``strip()`` rather than a bare truth test, and that is the whole point of
    this living in one place: a name of one space is no more a garment than an
    empty one, and the two copies of this rule used to answer differently.

    A missing profile *file* is `ConfigLoadError`'s to report on the engine
    side, and :func:`_check_garment_profile_exists`'s on the editor's. This
    only catches the name that could never name a file.
    """
    if garment_profile.strip():
        return []
    return [
        Issue(
            "block",
            "variants",
            _GARMENT_PROFILE_WHERE,
            "no garment_profile set, and every stage needs one to know what is being "
            "printed.\n"
            "Pick one in the listings editor's Variants tab, or write it in listing.yaml.",
        )
    ]


def check_copy_is_concrete(*, title: str, lead: str) -> list[Issue]:
    """Refuse blank copy before a product is created.

    The product carries the listing's own title and composed description -- Printify's
    create call requires both, and they are the duplicate
    guard's match key. ``lead`` rather than the full composed
    description: the description model's lead is required and its body is
    optional, so this is the same "deployment
    blocked until it is non-empty" rule the lead itself carries, checked here
    for the one reason nothing downstream would catch it.

    One issue per offending field, so the banner can point at the field that is
    actually wrong. That used to need a placeholder string passed in for
    whichever field wasn't being asked about, because the rule answered with a
    single refusal and the caller had to isolate the cause by calling it twice
    -- a workaround for a shape, now that the shape is a list.
    """
    issues: list[Issue] = []
    for field, value in (("title", title), ("description", lead)):
        if value.strip():
            continue
        where = _COPY_WHERE[field]
        detail = (
            "etsy.description.lead is empty. The lead is the opening paragraph a "
            "shopper reads, and deployment is blocked until it is set."
            if field == "description"
            else "etsy.title is empty, and Printify requires it to create a product "
            "(it is also how a re-run recognises the product as this listing's)."
        )
        issues.append(Issue("block", "details", where, detail))
    return issues


def check_description_ref(ref: str | None, error: str | None) -> list[Issue]:
    """Refuse a `description.ref` that does not resolve to usable common copy.

    ``error`` is the message a caller's own
    :meth:`~etsy_listings.workspace.workspace.Workspace.load_common_copy`
    attempt raised, or ``None`` when it resolved fine -- this module never
    touches the filesystem itself (see this file's own docstring), so the
    caller has already done the one read that can fail and hands back only
    the sentence, the same way `design_paths` arrives pre-resolved for
    :func:`check_design_resolution`'s caller to have tried first.
    """
    if ref is None or error is None:
        return []
    return [Issue("block", "details", _COPY_WHERE["description"], error)]


def _check_copy(listing: Listing, *, description_ref_error: str | None) -> list[Issue]:
    issues = check_copy_is_concrete(title=listing.etsy.title, lead=listing.etsy.description.lead)
    issues += check_description_ref(listing.etsy.description.ref, description_ref_error)
    return issues


def _check_design(design_paths: Mapping[str, Path], profile: GarmentProfile) -> list[Issue]:
    issues: list[Issue] = []
    for key, path in design_paths.items():
        where = _DESIGN_WHERE if key == "default" else f"{_DESIGN_WHERE} ({key})"
        issues += [replace(i, where=where) for i in check_design_resolution(path, profile)]
    return issues


def _check_media_present(listing: Production) -> list[Issue]:
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


def _check_colours_enabled(listing: Production) -> list[Issue]:
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


def _check_printify_variant_limit(listing: Production, profile: GarmentProfile) -> list[Issue]:
    colour_count = len(listing.colors)
    size_count = len(profile.sizes)
    variant_count = colour_count * size_count
    if variant_count <= PRINTIFY_MAX_VARIANTS:
        return []

    maximum_colours = PRINTIFY_MAX_VARIANTS // size_count
    colours_to_disable = colour_count - maximum_colours
    colour_word = "colour" if colours_to_disable == 1 else "colours"
    return [
        Issue(
            "warn",
            "variants",
            "Variants › Colours",
            f"{colour_count} colours × {size_count} sizes configures {variant_count} variants; "
            f"Printify allows at most {PRINTIFY_MAX_VARIANTS} per product. "
            f"Disable at least {colours_to_disable} {colour_word} or reduce the garment "
            "profile's sizes.",
        )
    ]


def _check_garment_profile_exists(
    listing: Production, garment_profile_names: Iterable[str]
) -> list[Issue]:
    # A new listing starts unchosen: the editor opens on a document with nothing
    # picked, so "not chosen yet" is the ordinary case and reporting it as
    # `'' does not exist` would describe a mistake nobody made. That half of the
    # rule is `check_garment_profile_chosen`'s, shared with every stage.
    unchosen = check_garment_profile_chosen(listing.garment_profile)
    if unchosen:
        return unchosen
    if listing.garment_profile in set(garment_profile_names):
        return []
    return [
        Issue(
            "block",
            "variants",
            _GARMENT_PROFILE_WHERE,
            f"Garment profile {listing.garment_profile!r} does not exist in this workspace.",
        )
    ]


def _check_design_selected(listing: Listing) -> list[Issue]:
    if listing.design:
        return []
    return [
        Issue(
            "block",
            "variants",
            "Design",
            "No design selected -- pick the artwork this listing prints.",
        )
    ]


def check_price_source(*, pricing_plan: str | None, priced_sizes: bool) -> list[Issue]:
    """Nothing says what a variant costs.

    Public, and narrow-argument, like every other rule a stage shares: this one
    became one when ADR-0043 took it out of `Listing` itself. It used to block
    the *write*, which made it the single incompleteness out of eight that a
    seller met as the tool refusing to save their work; now it blocks the
    deploy, through `engine/stages/gates.py.check_price_source`, exactly as the
    other seven do.

    That move is also what makes the rule safe to state once. While it lived in
    the model, this module had to restate it so the banner could say *something*
    about a refusal the model made silently -- two expressions of one rule, and
    the comment here used to say so.
    """
    if pricing_plan is not None or priced_sizes:
        return []
    return [
        Issue(
            "block",
            "pricing",
            "Pricing",
            "No pricing plan and no prices -- pick a plan, or set a price for every size. "
            "Deployment is blocked until one of them is set.",
        )
    ]


def _check_price_source(listing: Production) -> list[Issue]:
    return check_price_source(pricing_plan=listing.pricing_plan, priced_sizes=bool(listing.prices))


def _check_template_kind_colour_match(
    listing: Production, templates: Mapping[str, TemplateInfo]
) -> list[Issue]:
    issues: list[Issue] = []
    for entry in listing.media:
        if not isinstance(entry, TemplateMediaEntry):
            continue
        info = templates.get(entry.template)
        if info is None:
            continue
        issues.extend(check_scene_colour(entry.template, info.kind, entry.colour))
    return issues


def check_scene_colour(template: str, kind: str, colour: str | None) -> list[Issue]:
    if (kind == "colour-matrix") == (colour is not None):
        return []
    message = (
        f"{template!r} is a colour-matrix template and needs a colour."
        if kind == "colour-matrix"
        else f"{template!r} is a {kind} template and must not name a colour."
    )
    return [Issue("block", "images", f"Listing Images › {template}", message)]


def check_render_template(template: str, path: Path, *, present: bool) -> list[Issue]:
    if present:
        return []
    return [
        Issue(
            "block",
            "images",
            "Listing Images",
            f"media references template {template!r}, but no template.yaml exists at {path}",
        )
    ]


def check_render_photo(
    template: str, colour: str | None, path: Path, *, present: bool
) -> list[Issue]:
    if present:
        return []
    where = f"colour {colour!r}" if colour is not None else "its scene"
    return [
        Issue(
            "block",
            "images",
            "Listing Images",
            f"template {template!r}: no mockup base image for {where} at {path}",
        )
    ]


def check_artwork_resolved(
    colour: str | None,
    tone: str | None,
    available: list[str],
    *,
    wanted: str | None = None,
    source: str = "",
) -> list[Issue]:
    if wanted is not None and wanted in available:
        return []
    detail = f"colour {colour!r}" if colour is not None else "this template"
    tone_note = f" (tone: {tone})" if tone else ""
    message = (
        f"{detail}{tone_note}: {source} asks for artwork {wanted!r}, which the "
        f"design does not have -- it offers {available!r}. Add {wanted!r} to the "
        f"listing's design:, or remove the override."
        if wanted is not None
        else f"{detail}{tone_note} needs an artwork but none resolves -- design offers "
        f"{available!r}; add a listing.artwork override or a matching key"
    )
    return [Issue("block", "variants", "Design", message)]


def _check_variation_images(
    listing: Production, templates: Mapping[str, TemplateInfo]
) -> list[Issue]:
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
    if not listing.etsy.tags:
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
    listing: Production, profile: GarmentProfile | None
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


MAX_VIDEO_BYTES = 100_000_000
"""Etsy's help page: "max 100 MB". Read as decimal megabytes, the stricter of
the two readings, so a file this passes is one Etsy accepts either way."""
MIN_VIDEO_SECONDS = 3.0
MAX_VIDEO_SECONDS = 15.0
MIN_VIDEO_SHORT_SIDE = 500
"""The help page's "minimum 500px", applied to the shorter side: it gives no
axis, and a clip whose shorter side reaches 500 reaches it on both."""


def check_videos(videos: Mapping[str, VideoFacts | ProbeFailure]) -> list[Issue]:
    """Refuse a video Etsy's help page would reject.

    The help page, not the API, because the API is no guide: it accepted a
    3 s and a 20 s clip and answered a non-video with a bare ``500``
    (decision 9). Keyed by the ref ``media:`` names it by, so every message
    names the file the seller has to go and fix. No aspect rule -- the help
    page states none.

    The extension is not checked here: `Listing` refuses a ref that is neither
    an image nor a video when it loads, and the probe refuses a file whose
    contents are not MP4/MOV whatever it is called.
    """
    issues: list[Issue] = []
    for ref, facts in videos.items():
        where = f"Listing Images › {ref}"

        def block(message: str, where: str = where) -> None:
            issues.append(Issue("block", "images", where, message))

        if isinstance(facts, ProbeFailure):
            block(f"{ref} {facts.reason}. Etsy takes an MP4 or MOV video with a picture.")
            continue
        if facts.size_bytes > MAX_VIDEO_BYTES:
            block(
                f"{ref} is {facts.size_bytes / 1_000_000:.1f} MB, over Etsy's "
                f"{MAX_VIDEO_BYTES // 1_000_000} MB limit for a video."
            )
        if not MIN_VIDEO_SECONDS <= facts.duration_seconds <= MAX_VIDEO_SECONDS:
            block(
                f"{ref} runs {facts.duration_seconds:.1f} s; Etsy takes videos of "
                f"{MIN_VIDEO_SECONDS:g}–{MAX_VIDEO_SECONDS:g} seconds."
            )
        if min(facts.width, facts.height) < MIN_VIDEO_SHORT_SIDE:
            block(
                f"{ref} is {facts.width}x{facts.height}; Etsy needs at least "
                f"{MIN_VIDEO_SHORT_SIDE} px on the shorter side."
            )
        if facts.has_audio:
            issues.append(
                Issue(
                    "info",
                    "images",
                    where,
                    f"{ref} has a sound track; Etsy strips the sound, so buyers see it silent.",
                )
            )
    return issues


def check_lifecycle_verb(lifecycle: str | None, *, published: bool) -> list[Issue]:
    """Refuse the wrong end-of-life verb.

    ``deleted`` on something that has left Etsy ``draft`` would throw away
    reviews, favourites and search history -- the same history ADR-0017
    refused to discard to change a garment. ``retired`` on a never-live
    listing pauses nothing. Wrong verb is never rewritten as the right one.
    """
    if lifecycle == "deleted" and published:
        return [
            Issue("block", "details", _LIFECYCLE_WHERE, DELETED_ON_PUBLISHED),
        ]
    if lifecycle == "retired" and not published:
        return [
            Issue("block", "details", _LIFECYCLE_WHERE, RETIRED_ON_NEVER_LIVE),
        ]
    return []


def check_listing_yaml_present(*, present: bool) -> list[Issue]:
    """Refuse to infer retire or delete from a missing file.

    A directory that still has a lockfile is visible; a missing document is
    not consent. Never send ``state``, never delete remotes.
    """
    if present:
        return []
    return [Issue("block", "details", _LIFECYCLE_WHERE, MISSING_LISTING_YAML)]


def check_listing(
    listing: Listing,
    *,
    garment_profile: GarmentProfile | None,
    garment_profile_names: Iterable[str],
    design_paths: Mapping[str, Path],
    templates: Mapping[str, TemplateInfo],
    published: bool | None = None,
    description_ref_error: str | None = None,
    videos: Mapping[str, VideoFacts | ProbeFailure] | None = None,
) -> list[Issue]:
    """Every business-level issue with ``listing``, assuming it already passed
    `Listing.model_validate` -- structural failures are the API layer's to
    catch and never reach here.

    ``garment_profile`` is ``None`` when ``listing.garment_profile`` does not
    resolve to a real file; the profile-dependent checks (design resolution,
    colour classification) have nothing to check against then and are
    skipped, leaving :func:`_check_garment_profile_exists`'s block as the one
    issue that matters.

    ``description_ref_error`` is the caller's own
    ``Workspace.load_common_copy(listing.etsy.description.ref)`` attempt,
    pre-resolved the same way ``design_paths`` is -- ``None`` when there is no
    ref to check, or when it resolved fine.

    ``videos`` is every video ``media:`` names, probed by the caller --
    `WorkspaceFacts.videos` -- and keyed by its ref, for the same reason: this
    module opens no file.
    """
    issues: list[Issue] = []
    issues += _check_garment_profile_exists(listing, garment_profile_names)
    issues += _check_design_selected(listing)
    issues += _check_colours_enabled(listing)
    issues += _check_price_source(listing)
    issues += _check_media_present(listing)
    issues += _check_copy(listing, description_ref_error=description_ref_error)
    if garment_profile is not None:
        issues += _check_design(design_paths, garment_profile)
        issues += _check_colours_in_garment_profile(listing, garment_profile)
        issues += _check_printify_variant_limit(listing, garment_profile)
    issues += _check_template_kind_colour_match(listing, templates)
    issues += _check_variation_images(listing, templates)
    issues += check_videos(videos or {})
    issues += _check_tags(listing)
    if published is not None:
        issues += check_lifecycle_verb(listing.lifecycle, published=published)
    return issues


def check_listing_template(
    template: ListingTemplate,
    *,
    garment_profile: GarmentProfile | None,
    garment_profile_names: Iterable[str],
    templates: Mapping[str, TemplateInfo],
    description_ref_error: str | None = None,
    videos: Mapping[str, VideoFacts | ProbeFailure] | None = None,
) -> list[Issue]:
    """Every production issue with a listing template: the checks
    :func:`check_listing` makes about garment, colours, price source,
    gallery, videos and mockup-template kinds, and none of its design, brief,
    copy or lifecycle checks -- a template has none of those fields, and their
    absence is the point of it rather than something to finish.

    Any ``block`` refuses the write: a listing template on disk is always
    complete, so the server keeps the last complete version instead. Its
    inputs arrive pre-resolved, exactly as :func:`check_listing`'s do (this
    module opens no file), and nothing here asks a provider -- live facts such
    as a price under Printify's cost stay deployment-time checks.
    """
    issues: list[Issue] = []
    issues += _check_garment_profile_exists(template, garment_profile_names)
    issues += _check_colours_enabled(template)
    issues += _check_price_source(template)
    issues += _check_media_present(template)
    issues += check_description_ref(template.etsy.description.ref, description_ref_error)
    if garment_profile is not None:
        issues += _check_colours_in_garment_profile(template, garment_profile)
        issues += _check_printify_variant_limit(template, garment_profile)
    issues += _check_template_kind_colour_match(template, templates)
    issues += _check_variation_images(template, templates)
    issues += check_videos(videos or {})
    return issues
