"""Pruning position fits (spec *Rendering → Marigold (option B)*: "Fits no
listing references are pruned with the cache"). A fit survives while some
listing's current position, against its template's current evidence,
produces it, or while a scene holds it; every other one is removed."""

from __future__ import annotations

from etsy_listings.core.application.position_fit_pruning import prune_position_fits
from etsy_listings.core.preparation.position_fits import PositionFits
from etsy_listings.core.render.positions import Pose

from tests.core.behaviour.test_marigold_positions import plan, position
from tests.support.builders import copy_listing, edit_listing
from tests.support.marigold import listing_with_prepared_marigold

OLD = Pose(rotation=8)
NEW = Pose(scale=0.9, rotation=-6)


def fitted(workspace, pose: Pose, listing: str | None = None) -> str:
    """Save ``pose`` on the listing and plan it; the key of the fit it made."""
    before = set(workspace.position_fits())
    if listing is None:
        edit_listing(workspace.root, template_positions=position(workspace, pose))
        plan(workspace.root)
    else:
        edit_listing(workspace.root, listing, template_positions=position(workspace, pose))
        plan(workspace.root, listing)
    (key,) = set(workspace.position_fits()) - before
    return key


def test_prune_removes_only_fits_no_current_position_produces(workspace_root):
    workspace = listing_with_prepared_marigold(workspace_root)
    old = fitted(workspace, OLD)
    shared = "second-listing"
    copy_listing(workspace_root, shared)
    new = fitted(workspace, NEW)
    kept_by_other = fitted(workspace, Pose(rotation=-12), shared)

    assert prune_position_fits(workspace) == [old]
    assert sorted(workspace.position_fits()) == sorted([new, kept_by_other])


def test_prune_spares_a_fit_a_scene_still_holds(workspace_root):
    workspace = listing_with_prepared_marigold(workspace_root)
    old = fitted(workspace, OLD)
    fitted(workspace, NEW)

    with PositionFits(workspace).lease([old]):
        assert prune_position_fits(workspace) == []
    assert prune_position_fits(workspace) == [old]
