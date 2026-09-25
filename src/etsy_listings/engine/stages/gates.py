"""The stage's view of the checks `plan` runs before any remote write.

The rules themselves live in `config/listing_validation.py`, which is the one
module that knows every reason a listing cannot run. This is the adapter a
stage reads them through: same three names, same signatures, an
:class:`~etsy_listings.engine.stage.Blocked` instead of an ``Issue``.

There used to be two modules, each with its own copy of some of the rules, and
they had already diverged -- ``check_garment_profile_chosen`` accepted a
whitespace-only name here while the editor's banner refused it, so one listing
on disk got two answers about whether it could run. One vocabulary for "this
cannot run" is only one vocabulary if there is also one *rule* behind it.

They live outside any single stage because they are checks about a *listing* --
its copy, its artwork -- that any stage shipping either will want, and because
`plan` has to be able to run them before it builds a desired document: a
refusal is more useful than a well-formed payload nobody wants sent.

``check_garment_unchanged`` used to be here and is not, for the same rule read
the other way: it is entirely about the product stage's own applied document,
which is now a type rather than a dict, and a shared module has no business
knowing that type. It lives beside the document it reads.

**Each returns a** :class:`~etsy_listings.engine.stage.Blocked` **rather than
raising one.** A refusal is something `plan` has to report, and raising made
it something `plan` could only die of: the exception unwound the stage walk,
so a design a hundred pixels short took the render stage's plan with it and
the user saw a single line where a whole listing's intent belonged. Returned,
a refusal is a blocked stage like any other -- the same vocabulary an
unconfigured shop already used. ``apply`` still refuses to run a blocked
stage, which is the half that has to stay hard.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from etsy_listings.config import listing_validation as rules
from etsy_listings.config.garment_profile import GarmentProfile
from etsy_listings.config.listing_validation import Issue
from etsy_listings.config.media import ProbeFailure, VideoFacts
from etsy_listings.engine.stage import Blocked


def _refuse(issues: Sequence[Issue]) -> Blocked | None:
    """The first *blocking* issue, as a refusal.

    A ``warn`` or ``info`` is something the banner shows and a deploy goes
    ahead past -- a video's stripped sound (PRD 71) is the case that made a
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


def check_garment_profile_chosen(garment_profile: str) -> Blocked | None:
    return _refuse(rules.check_garment_profile_chosen(garment_profile))


def check_copy_is_concrete(*, title: str, lead: str) -> Blocked | None:
    return _refuse(rules.check_copy_is_concrete(title=title, lead=lead))


def check_lifecycle_verb(lifecycle: str | None, *, published: bool) -> Blocked | None:
    return _refuse(rules.check_lifecycle_verb(lifecycle, published=published))


def check_listing_yaml_present(*, present: bool) -> Blocked | None:
    return _refuse(rules.check_listing_yaml_present(present=present))


def check_price_source(*, pricing_plan: str | None, priced_sizes: bool) -> Blocked | None:
    """Nothing says what a variant costs (PRD 70).

    This gate is what the price-source rule became when it stopped blocking
    the write. `Listing.resolved_price` raises `KeyError` when nothing
    resolves, and a `KeyError` is not a `UserFacingError` -- it would end a
    whole ``--all`` batch on one unpriced listing, which is precisely the
    shape of failure this vocabulary exists to replace.
    """
    return _refuse(rules.check_price_source(pricing_plan=pricing_plan, priced_sizes=priced_sizes))


def check_videos(videos: Mapping[str, VideoFacts | ProbeFailure]) -> Blocked | None:
    """A video Etsy's help page would reject (PRD 71). Its audio note is not
    a refusal, which is why `_refuse` reads severity."""
    return _refuse(rules.check_videos(videos))
