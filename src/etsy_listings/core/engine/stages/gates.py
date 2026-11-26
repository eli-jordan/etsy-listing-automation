"""The stage's view of ``config/listing_validation.py``'s rules: the same checks,
returning a :class:`~etsy_listings.core.engine.stage.Blocked` instead of an ``Issue``."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from etsy_listings.core.config import listing_validation as rules
from etsy_listings.core.config.artwork import DesignMap, Resolved, Tone, resolve
from etsy_listings.core.config.description import DescriptionConfig
from etsy_listings.core.config.garment_profile import GarmentProfile
from etsy_listings.core.config.listing import EtsyListingConfig, Listing
from etsy_listings.core.config.listing_validation import Issue, TemplateInfo
from etsy_listings.core.config.media import ProbeFailure, VideoFacts
from etsy_listings.core.config.settings import TemplatePositionLimits
from etsy_listings.core.engine.stage import Blocked
from etsy_listings.core.render.config import AnyTemplate
from etsy_listings.core.workspace.common_copy import CommonCopyError


def concrete_description(
    config: EtsyListingConfig, compose: Callable[[DescriptionConfig], str]
) -> str | Blocked:
    blocked = check_copy_is_concrete(title=config.title, lead=config.description.lead)
    if blocked is not None:
        return blocked
    try:
        return compose(config.description)
    except CommonCopyError as exc:
        return Blocked(str(exc))


def _refuse(issues: Sequence[Issue]) -> Blocked | None:
    """The first *blocking* issue, as a refusal.

    A ``warn`` or ``info`` is something the banner shows and a deploy goes
    ahead past -- a video's stripped sound is the case that made a
    rule return both kinds from one call.

    A stage refuses or it does not, so only the first message can be shown --
    the banner is what wants the whole list. ``where`` and ``tab`` are dropped
    here rather than folded into the text: a stage's refusal is already
    attributed to the stage that returned it, and "Variants › Garment profile"
    names a tab a CLI user is not looking at.
    """
    blocking = [issue for issue in issues if issue.severity == "block"]
    return Blocked(blocking[0].message) if blocking else None


def check_design_resolution(design: Path, profile: GarmentProfile) -> Blocked | None:
    return _refuse(rules.check_design_resolution(design, profile))


def check_artwork(
    listing: Listing, profile: GarmentProfile, templates: Mapping[str, TemplateInfo]
) -> Blocked | None:
    return _refuse(rules.check_artwork(listing, profile, templates))


def resolved_design(
    design: DesignMap, colour: str | None, tones: Mapping[str, Tone], *, where: str
) -> str | Blocked:
    resolution = resolve(design, colour, tones)
    if isinstance(resolution, Resolved):
        return resolution.ref
    subject = f"colour {colour!r}" if colour is not None else "a scene that names no colour"
    return Blocked(
        f"{where}: no design resolves for {subject}. Check the listing's design: and the "
        f"colours this template depicts."
    )


def check_garment_profile_chosen(garment_profile: str) -> Blocked | None:
    return _refuse(rules.check_garment_profile_chosen(garment_profile))


def check_copy_is_concrete(*, title: str, lead: str) -> Blocked | None:
    return _refuse(rules.check_copy_is_concrete(title=title, lead=lead))


def check_lifecycle_verb(lifecycle: str | None, *, published: bool) -> Blocked | None:
    return _refuse(rules.check_lifecycle_verb(lifecycle, published=published))


def check_listing_yaml_present(*, present: bool) -> Blocked | None:
    return _refuse(rules.check_listing_yaml_present(present=present))


def check_price_source(*, pricing_plan: str | None, priced_sizes: bool) -> Blocked | None:
    """Nothing says what a variant costs.

    This gate is what the price-source rule became when it stopped blocking
    the write. `Listing.resolved_price` raises `KeyError` when nothing
    resolves, and a `KeyError` is not a `UserFacingError` -- it would end a
    whole ``--all`` batch on one unpriced listing, which is precisely the
    shape of failure this vocabulary exists to replace.
    """
    return _refuse(rules.check_price_source(pricing_plan=pricing_plan, priced_sizes=priced_sizes))


def check_videos(videos: Mapping[str, VideoFacts | ProbeFailure]) -> Blocked | None:
    return _refuse(rules.check_videos(videos))


def check_scene_colour(template: str, kind: str, colour: str | None) -> Blocked | None:
    return _refuse(rules.check_scene_colour(template, kind, colour))


def check_render_template(template: str, path: Path) -> Blocked | None:
    return _refuse(rules.check_render_template(template, path, present=path.is_file()))


def check_render_photo(template: str, colour: str | None, path: Path) -> Blocked | None:
    return _refuse(rules.check_render_photo(template, colour, path, present=path.is_file()))


def check_prepared_maps(template: str, error: str | None) -> Blocked | None:
    return _refuse(rules.check_prepared_maps(template, error))


def check_template_positions(
    listing: Listing,
    templates: Mapping[str, AnyTemplate],
    limits: TemplatePositionLimits,
    *,
    name: str,
) -> Blocked | None:
    return _refuse(rules.check_template_positions(listing, templates, limits, name=name))
