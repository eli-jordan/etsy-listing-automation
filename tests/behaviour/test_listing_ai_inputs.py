"""Saved-listing AI preparation and comparison facts."""

from pathlib import Path

from etsy_listings.ai.listing_inputs import ListingAiInputs
from etsy_listings.ai.proposals import proposal_staleness
from etsy_listings.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING


def test_a_garment_profile_that_no_longer_loads_reads_as_changed(workspace_root: Path) -> None:
    """``ListingAiInputs`` is how "now" is read. A profile file that went
    missing under the same name leaves its facts empty, which is stale
    against a proposal made with them -- never silently current."""
    workspace = Workspace.discover(root_override=workspace_root)
    frozen = ListingAiInputs.read(workspace, FIXTURE_LISTING).snapshot
    workspace.garment_profile_file("comfort-colors-1717").unlink()
    now = ListingAiInputs.read(workspace, FIXTURE_LISTING).snapshot

    assert proposal_staleness(frozen, frozen).is_stale is False
    assert proposal_staleness(frozen, now).reasons == [
        "materials changed since",
        "product type changed since",
        "garment brand changed since",
        "garment model changed since",
    ]


def test_preparation_pairs_the_request_with_its_comparison_inputs(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    prepared = ListingAiInputs.read(workspace, FIXTURE_LISTING).prepare(
        market_block="buyer phrases"
    )
    request, snapshot = prepared.request, prepared.snapshot

    assert request.product_type == snapshot.product_type == "Unisex Garment-Dyed T-shirt"
    assert request.materials == tuple(snapshot.materials) == ("cotton",)
    assert request.garment.brand == snapshot.garment_brand == "Comfort Colors"
    assert request.garment.model == snapshot.garment_model == "1717"
    assert request.brief == snapshot.brief
    assert request.colors == tuple(snapshot.colors)
    assert request.etsy_category == snapshot.etsy_category
    assert request.market_block == "buyer phrases"
    assert request.design_image == workspace.resolve_ref(
        snapshot.design["default"], listing_dir=workspace.listing_dir(FIXTURE_LISTING)
    )
    assert snapshot.design_content_hash is not None
