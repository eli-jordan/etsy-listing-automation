from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, NamedTuple

from PIL import Image, UnidentifiedImageError

from etsy_listings.core.config.artwork import (
    SlotEmpty,
    Tone,
    Unclassified,
    is_light_dark,
    representative,
    resolve,
    slot_users,
)
from etsy_listings.core.config.garment_profile import GarmentProfile
from etsy_listings.core.config.listing import Listing, TemplateMediaEntry
from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.config.media import ProbeFailure, VideoFacts
from etsy_listings.core.config.settings import TemplatePositionLimits
from etsy_listings.core.config.template_positions import BoxPosition, PlacementPositions
from etsy_listings.core.render.config import AnyTemplate, BoundingBox, MultipleTemplate
from etsy_listings.core.render.positions import Pose, decompose

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
    severity: Severity
    tab: Tab
    where: str
    message: str


@dataclass(frozen=True)
class TemplateInfo:
    kind: Literal["colour-matrix", "multiple", "single"]
    colours: frozenset[str]
    preparation_error: str | None = None
    config: AnyTemplate | None = None


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
    return (
        int(profile.print_area.width * RESOLUTION_TOLERANCE),
        int(profile.print_area.height * RESOLUTION_TOLERANCE),
    )


def check_design_resolution(design: Path, profile: GarmentProfile) -> list[Issue]:
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
    """Refuse a listing with a blank garment profile name before it reaches ``_segment``, whose
    plain ``ValueError`` would end a whole ``--all`` batch."""
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


def check_price_source(*, pricing_plan: str | None, priced_sizes: bool) -> list[Issue]:
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


def check_prepared_maps(template: str, error: str | None) -> list[Issue]:
    if error is None:
        return []
    return [Issue("block", "images", f"Listing Images › {template}", error)]


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


def _check_variation_images(listing: Production) -> list[Issue]:
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


_ARTWORK_WHERE = "Artwork"
_LINK_WHERE = "Artwork · Link the two designs if one is all this listing needs"


def _names(colours: Iterable[str]) -> str:
    cap = [colour[:1].upper() + colour[1:] for colour in colours]
    if len(cap) <= 1:
        return "".join(cap)
    return f"{', '.join(cap[:-1])} and {cap[-1]}"


def _shirts(tone: Tone) -> str:
    return f"{tone} shirts"


class _Depicted(NamedTuple):
    colours: list[str]
    unnamed_single_templates: list[str]


def _depicted(listing: Listing, templates: Mapping[str, TemplateInfo]) -> _Depicted:
    colours: dict[str, None] = {}
    colourless: dict[str, None] = {}
    for entry in listing.media:
        if not isinstance(entry, TemplateMediaEntry):
            continue
        scene = _scene_colours(entry, templates)
        if scene.single_names_none:
            colourless.setdefault(entry.template, None)
        for colour in scene.shown:
            colours.setdefault(colour, None)
    return _Depicted(list(colours), list(colourless))


class _SceneColours(NamedTuple):
    shown: list[str]
    single_names_none: bool


def _scene_colours(
    entry: TemplateMediaEntry, templates: Mapping[str, TemplateInfo]
) -> _SceneColours:
    if entry.colour is not None:
        return _SceneColours([entry.colour], single_names_none=False)
    info = templates.get(entry.template)
    if info is None or info.kind == "colour-matrix":
        return _SceneColours([], single_names_none=False)
    return _SceneColours(
        sorted(info.colours), single_names_none=info.kind == "single" and not info.colours
    )


def _unclassified_issue(severity: Severity, profile: str, colours: list[str]) -> list[Issue]:
    if not colours:
        return []
    verb = "isn't" if len(colours) == 1 else "aren't"
    return [
        Issue(
            severity,
            "variants",
            f"Fix it in garment-profiles/{profile}.yaml",
            f"{_names(colours)} {verb} marked light or dark in the {profile} garment profile",
        )
    ]


def _check_template_tones(template: ListingTemplate, profile: GarmentProfile) -> list[Issue]:
    unclassified = [colour for colour in template.colors if colour not in profile.colors]
    return _unclassified_issue("warn", template.garment_profile, unclassified)


def check_artwork(
    listing: Listing,
    profile: GarmentProfile | None,
    templates: Mapping[str, TemplateInfo],
) -> list[Issue]:
    design = listing.design
    if representative(design) is None:
        return [
            Issue("block", "variants", _ARTWORK_WHERE, "No design is chosen for this listing yet")
        ]
    if profile is None:
        return []

    tones = profile.colors
    depicted, colourless = _depicted(listing, templates)
    unclassified = [colour for colour in listing.colors if colour not in tones]
    empty: dict[Tone, list[str]] = {"light": [], "dark": []}
    for colour in [*listing.colors, *depicted]:
        match resolve(design, colour, tones):
            case Unclassified() if colour not in unclassified:
                unclassified.append(colour)
            case SlotEmpty(tone) if colour not in empty[tone]:
                empty[tone].append(colour)

    issues = _unclassified_issue("block", listing.garment_profile, unclassified)
    issues += _empty_slot_issues(empty)
    if is_light_dark(design):
        issues += _light_dark_issues(listing, tones, colourless)
    return issues


def _empty_slot_issues(empty: Mapping[Tone, list[str]]) -> list[Issue]:
    issues: list[Issue] = []
    for tone, colours in empty.items():
        if not colours:
            continue
        noun = f"is a {tone} shirt" if len(colours) == 1 else f"are {_shirts(tone)}"
        issues.append(
            Issue(
                "block",
                "variants",
                f"{_ARTWORK_WHERE} · For {_shirts(tone)}",
                f"{_names(colours)} {noun}, but no design for {_shirts(tone)} is chosen",
            )
        )
    return issues


def _light_dark_issues(
    listing: Listing, tones: Mapping[str, Tone], colourless: list[str]
) -> list[Issue]:
    issues = [
        Issue(
            "block",
            "images",
            f"Listing Images › {template}",
            f"{template!r} doesn't say which shirt colour it shows, so it can't choose "
            f"between the designs for light and dark shirts. Name its colour in the "
            f"calibrator, or remove it from this listing.",
        )
        for template in colourless
    ]
    used = [
        tone for tone, users in slot_users(listing.design, listing.colors, tones).items() if users
    ]
    if len(used) == 1:
        other: Tone = "dark" if used[0] == "light" else "light"
        issues.append(
            Issue(
                "warn",
                "variants",
                _LINK_WHERE,
                f"Only the design for {_shirts(used[0])} is in use — no {other} shirt you "
                f"sell needs the design for {_shirts(other)}",
            )
        )
    return issues


MAX_VIDEO_BYTES = 100_000_000
"""Etsy's help page: "max 100 MB". Read as decimal megabytes, the stricter of
the two readings, so a file this passes is one Etsy accepts either way."""
MIN_VIDEO_SECONDS = 3.0
MAX_VIDEO_SECONDS = 15.0
MIN_VIDEO_SHORT_SIDE = 500
"""The help page's "minimum 500px", applied to the shorter side: it gives no
axis, and a clip whose shorter side reaches 500 reaches it on both."""


def check_videos(videos: Mapping[str, VideoFacts | ProbeFailure]) -> list[Issue]:
    return [issue for ref, facts in videos.items() for issue in _video_issues(ref, facts)]


def _video_issues(ref: str, facts: VideoFacts | ProbeFailure) -> list[Issue]:
    where = f"Listing Images › {ref}"
    if isinstance(facts, ProbeFailure):
        message = f"{ref} {facts.reason}. Etsy takes an MP4 or MOV video with a picture."
        return [Issue("block", "images", where, message)]
    refusals: list[str] = []
    if facts.size_bytes > MAX_VIDEO_BYTES:
        refusals.append(
            f"{ref} is {facts.size_bytes / 1_000_000:.1f} MB, over Etsy's "
            f"{MAX_VIDEO_BYTES // 1_000_000} MB limit for a video."
        )
    if not MIN_VIDEO_SECONDS <= facts.duration_seconds <= MAX_VIDEO_SECONDS:
        refusals.append(
            f"{ref} runs {facts.duration_seconds:.1f} s; Etsy takes videos of "
            f"{MIN_VIDEO_SECONDS:g}–{MAX_VIDEO_SECONDS:g} seconds."
        )
    if min(facts.width, facts.height) < MIN_VIDEO_SHORT_SIDE:
        refusals.append(
            f"{ref} is {facts.width}x{facts.height}; Etsy needs at least "
            f"{MIN_VIDEO_SHORT_SIDE} px on the shorter side."
        )
    issues = [Issue("block", "images", where, message) for message in refusals]
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
    if present:
        return []
    return [Issue("block", "details", _LIFECYCLE_WHERE, MISSING_LISTING_YAML)]


_POSITION_RESIDUAL_PIXELS = 1.0
_POSITION_ROUNDOFF = 1e-8


def _similarity_pose(template_box: BoundingBox, box: BoundingBox) -> Pose | None:
    try:
        fit = decompose(template_box, box)
    except ValueError:
        return None
    if fit.residual_pixels > _POSITION_RESIDUAL_PIXELS + _POSITION_ROUNDOFF:
        return None
    return fit.pose


def _limit_problems(pose: Pose, limits: TemplatePositionLimits) -> list[str]:
    problems = []
    if (
        not limits.scale.min - _POSITION_ROUNDOFF
        <= pose.scale
        <= limits.scale.max + _POSITION_ROUNDOFF
    ):
        problems.append(
            f"scales the design to {pose.scale:.2f}; the limit is "
            f"{limits.scale.min:.2f}–{limits.scale.max:.2f}"
        )
    for axis, value in (("horizontal", pose.offset_x), ("vertical", pose.offset_y)):
        if abs(value) > limits.offset + _POSITION_ROUNDOFF:
            problems.append(f"has {axis} offset {value:.0%}; the limit is ±{limits.offset:.0%}")
    if abs(pose.rotation) > limits.rotation + _POSITION_ROUNDOFF:
        problems.append(f"has rotation {pose.rotation:g}°; the limit is ±{limits.rotation:g}°")
    return problems


def _box_position_problems(
    template_box: BoundingBox, box: BoundingBox, limits: TemplatePositionLimits
) -> list[str]:
    pose = _similarity_pose(template_box, box)
    if pose is None:
        return ["is not a plain move, resize or tilt of the template's box"]
    return _limit_problems(pose, limits)


def _placement_position_problems(
    key: str,
    position: PlacementPositions,
    template: MultipleTemplate,
    limits: TemplatePositionLimits,
) -> list[tuple[str, str]]:
    boxes = {placement.id: placement.bounding_box for placement in template.placements}
    problems = []
    for placement_id, placement in position.placements.items():
        path = f"{key}.placements.{placement_id}"
        if placement_id not in boxes:
            problems.append((path, "names a placement that no longer exists"))
        else:
            problems.extend(
                (path, problem)
                for problem in _box_position_problems(
                    boxes[placement_id], placement.bounding_box, limits
                )
            )
    return problems


def _position_problems(
    key: str,
    position: BoxPosition | PlacementPositions,
    template: AnyTemplate,
    limits: TemplatePositionLimits,
) -> list[tuple[str, str]]:
    if isinstance(template, MultipleTemplate):
        if not isinstance(position, PlacementPositions):
            return [(key, "uses bounding_box on a multiple template; use placements instead")]
        return _placement_position_problems(key, position, template, limits)
    if not isinstance(position, BoxPosition):
        return [(key, f"uses placements on a {template.kind} template; use bounding_box instead")]
    return [
        (key, problem)
        for problem in _box_position_problems(template.bounding_box, position.bounding_box, limits)
    ]


def check_template_positions(
    listing: Listing,
    templates: Mapping[str, AnyTemplate],
    limits: TemplatePositionLimits,
    *,
    name: str = "",
) -> list[Issue]:
    referenced = {
        entry.template for entry in listing.media if isinstance(entry, TemplateMediaEntry)
    }
    problems = []
    for template_name, position in (listing.template_positions or {}).items():
        key = f"template_positions.{template_name}"
        if template_name not in referenced:
            problems.append((key, "names a template that is not in media"))
        elif template_name not in templates:
            problems.append((key, "names a template whose configuration is unavailable"))
        else:
            problems.extend(_position_problems(key, position, templates[template_name], limits))
    prefix = f"{name}: " if name else ""
    return [Issue("block", "images", key, f"{prefix}{key} {problem}") for key, problem in problems]


def positions_outside_limits(
    listing: Listing,
    templates: Mapping[str, AnyTemplate],
    limits: TemplatePositionLimits,
) -> list[str]:
    referenced = {
        entry.template for entry in listing.media if isinstance(entry, TemplateMediaEntry)
    }
    outside: list[str] = []
    for template_name, position in (listing.template_positions or {}).items():
        template = templates.get(template_name) if template_name in referenced else None
        if template is None:
            continue
        boxes = _positioned_boxes(f"template_positions.{template_name}", position, template)
        outside += [path for path, own, box in boxes if _limited(own, box, limits)]
    return outside


def _limited(template_box: BoundingBox, box: BoundingBox, limits: TemplatePositionLimits) -> bool:
    pose = _similarity_pose(template_box, box)
    return pose is not None and bool(_limit_problems(pose, limits))


def _positioned_boxes(
    key: str, position: BoxPosition | PlacementPositions, template: AnyTemplate
) -> list[tuple[str, BoundingBox, BoundingBox]]:
    if isinstance(template, MultipleTemplate):
        if not isinstance(position, PlacementPositions):
            return []
        boxes = {placement.id: placement.bounding_box for placement in template.placements}
        return [
            (f"{key}.placements.{pid}", boxes[pid], placement.bounding_box)
            for pid, placement in position.placements.items()
            if pid in boxes
        ]
    if not isinstance(position, BoxPosition):
        return []
    return [(key, template.bounding_box, position.bounding_box)]


@dataclass(frozen=True)
class CheckInputs:
    garment_profile: GarmentProfile | None
    garment_profile_names: Iterable[str]
    templates: Mapping[str, TemplateInfo]
    description_ref_error: str | None = None
    videos: Mapping[str, VideoFacts | ProbeFailure] = MappingProxyType({})
    template_position_limits: TemplatePositionLimits = dataclass_field(
        default_factory=TemplatePositionLimits
    )
    template_position_limits_error: str | None = None
    """The caller's failed ``settings.yaml`` read; positions are then refused
    with it rather than checked against defaults."""
    listing_name: str = ""


def _check_positions(listing: Listing, inputs: CheckInputs) -> list[Issue]:
    if listing.template_positions and inputs.template_position_limits_error is not None:
        return [
            Issue("block", "images", "template_positions", inputs.template_position_limits_error)
        ]
    return check_template_positions(
        listing,
        {name: info.config for name, info in inputs.templates.items() if info.config is not None},
        inputs.template_position_limits,
        name=inputs.listing_name,
    )


def check_listing(
    listing: Listing,
    inputs: CheckInputs,
    *,
    design_paths: Mapping[str, Path],
    published: bool | None = None,
) -> list[Issue]:
    garment_profile, templates = inputs.garment_profile, inputs.templates
    issues: list[Issue] = []
    issues += _check_garment_profile_exists(listing, inputs.garment_profile_names)
    issues += check_artwork(listing, garment_profile, templates)
    issues += _check_colours_enabled(listing)
    issues += _check_price_source(listing)
    issues += _check_media_present(listing)
    issues += _check_copy(listing, description_ref_error=inputs.description_ref_error)
    if garment_profile is not None:
        issues += _check_design(design_paths, garment_profile)
        issues += _check_printify_variant_limit(listing, garment_profile)
    issues += _check_template_kind_colour_match(listing, templates)
    issues += _check_variation_images(listing)
    issues += _check_positions(listing, inputs)
    for name in dict.fromkeys(
        entry.template for entry in listing.media if isinstance(entry, TemplateMediaEntry)
    ):
        info = templates.get(name)
        if info is not None:
            issues += check_prepared_maps(name, info.preparation_error)
    issues += check_videos(inputs.videos)
    issues += _check_tags(listing)
    if published is not None:
        issues += check_lifecycle_verb(listing.lifecycle, published=published)
    return issues


def check_listing_template(template: ListingTemplate, inputs: CheckInputs) -> list[Issue]:
    """The checks :func:`check_listing` makes about garment, colours, price source, gallery, videos
    and mockup-template kinds, without its design, brief, copy or lifecycle ones. Any ``block``
    refuses the write."""
    garment_profile = inputs.garment_profile
    issues: list[Issue] = []
    issues += _check_garment_profile_exists(template, inputs.garment_profile_names)
    issues += _check_colours_enabled(template)
    issues += _check_price_source(template)
    issues += _check_media_present(template)
    issues += check_description_ref(template.etsy.description.ref, inputs.description_ref_error)
    if garment_profile is not None:
        issues += _check_template_tones(template, garment_profile)
        issues += _check_printify_variant_limit(template, garment_profile)
    issues += _check_template_kind_colour_match(template, inputs.templates)
    issues += _check_variation_images(template)
    issues += check_videos(inputs.videos)
    return issues
