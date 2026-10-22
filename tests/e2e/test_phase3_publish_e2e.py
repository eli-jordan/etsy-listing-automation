"""The full Phase 3 cycle against real Printify and Etsy APIs. ``-m e2e``,
skipped by default.

Where Phase 2's e2e layer was recon over raw ``httpx`` -- the client did not
exist yet -- this drives the real pipeline: ``plan_listings``/
``apply_listings`` over the actual ``STAGES``, against
:class:`~etsy_listings.core.clients.printify.HttpPrintifyClient` and
:class:`~etsy_listings.core.clients.etsy.HttpEtsyListingClient`. The recon this
phase was built from lives in
[docs/research/printify-etsy-integration.md](../../docs/research/printify-etsy-integration.md);
this is what re-takes it once the code exists to take it with.

**Needs two things the offline suite never does**: a Printify token (shared
with the rest of the e2e layer, see ``conftest.py``) and a workspace that has
already run `etsy-listings setup` and `etsy-listings auth etsy` for real --
read from ``ETSY_LISTINGS_ROOT``, the same variable a contributor's own
working setup already points at. Neither is fabricated here; a workspace
without both skips cleanly.

**This layer costs state.** It creates one Printify product, publishes it
-- a real Etsy draft listing -- patches it, uploads real images, and deletes
the product in teardown. Deleting the product **also removes the Etsy draft**:
measured, by asking for a listing a previous run had created and getting a
`404` for it and for its product. An earlier version of this note claimed the
opposite -- that the listing was orphaned and had to be cleared by hand -- and
that claim was never checked. Nothing here ever sets ``state``: the
"live-edit check" confirms the listing is still a draft after every write this
test makes, which is the measurable form of the rule that first publication stays with the seller.

**One journey, not nine ordered tests.** Each milestone below needs the
remote state the one before it left, and nine products to make them
independent would cost nine creates, publishes and uploads on a shared shop.
So the milestones are steps of a single test, which owns its workspace, its
copy and its cleanup: selecting it runs everything it depends on, and no
other case reads what it made. The copy carries a per-run token, because the
product stage adopts an existing product by copy (ADR-0023) -- a fixed title
would let a product an earlier crashed run left behind stand in for this
run's create.

**Every stage must actually run.** A blocked stage is reported, not raised,
and ``RunReport.failed`` does not count one -- so ``assert not report.failed``
passes over a stage that refused, and the layer reports green for work it
never did. It did: `etsy_listing` was blocked for want of a shipping profile
through every run of this test, so the `updateListing` PATCH at the centre of
ADR-0028, ADR-0029, ADR-0030, ADR-0031, ADR-0032 was never once sent against the real API, while the
first test's
title assertion passed anyway because Printify creates the listing from the
*product's* title. :func:`apply_everything` is the guard -- no stage
may refuse -- and the workspace fixture now resolves a shipping profile from
the shop it is pointed at rather than leaving one unset.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from etsy_listings.core.clients.etsy import HttpEtsyListingClient
from etsy_listings.core.clients.printify import HttpCatalogClient
from etsy_listings.core.clients.printify import Transport as PrintifyTransport
from etsy_listings.core.clients.printify.protocol import PrintifyClient
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.run import RunReport, apply_listings, plan_listings
from etsy_listings.core.engine.stages import STAGES
from etsy_listings.core.engine.stages.etsy_target import ETSY_LISTING_ID_KEY
from etsy_listings.core.engine.stages.printify_product import PRODUCT_ID_KEY
from etsy_listings.core.workspace.workspace import Workspace

from tests.conftest import FIXTURE_WORKSPACE
from tests.e2e.conftest import PrerequisiteMissing, point_at_throwaway_shops
from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import (
    edit_listing,
    set_copy,
    write_design,
)

pytestmark = pytest.mark.e2e

VIDEOS = Path(__file__).parent.parent / "fixtures" / "video"
FEATURED_VIDEO = "common-media/size-guide.mp4"
SECOND_VIDEO = "./how-it-fits.mp4"
IMAGES_IN_ORDER = [
    {"template": "flat-lay-01", "colour": colour}
    for colour in ("moss", "black", "blue-jean", "ivory")
]
"""The order the reorder milestone below leaves `media:` in."""


def _with_videos(*, second_after: int) -> list[object]:
    """The images, with the featured video at position 2 and the
    second anchored after ``second_after`` of them."""
    head, rest = IMAGES_IN_ORDER[:1], IMAGES_IN_ORDER[1:]
    media: list[object] = [*head, FEATURED_VIDEO, *rest]
    media.insert(second_after + 1, SECOND_VIDEO)
    return media


def _live_videos(ctx: RunContext, lock: Lockfile) -> dict[int, str | None]:
    """video_id -> state, for every video Etsy lists on the listing."""
    live = ctx.require_etsy().get_listing(
        int(lock.remote[ETSY_LISTING_ID_KEY]), include_videos=True
    )
    assert live is not None
    return {video.video_id: video.video_state for video in live.videos}


# ------------------------------------------------------------- test workspace


def apply_everything(ctx: RunContext) -> RunReport:
    """Apply, and insist the whole pipeline actually ran.

    ``report.failed`` is not enough on its own. A stage that refuses is
    *reported*, not failed, so an
    assertion on ``failed`` alone passes over a pipeline that quietly did half
    its work. That is not a hypothetical: `etsy_listing` refused in every run
    of this test for want of a shipping profile, and nothing said so.

    In this layer a refusal is always a defect in the fixture. Every stage is
    configured, every credential is present, and if one of them still cannot
    run then the run under test is not the run the assertions below describe.
    """
    report = apply_listings(ctx, [LISTING], STAGES)
    assert not report.failed, [o.error for o in report.failures]

    refused = [
        (stage_plan.stage, stage_plan.blocked)
        for outcome in report.outcomes
        if outcome.planned is not None
        for stage_plan in outcome.planned.plan.stage_plans
        if stage_plan.blocked
    ]
    assert not refused, f"a stage refused, so this run tested less than it appears to: {refused}"
    return report


@pytest.fixture
def copy() -> tuple[str, str]:
    """This run's title and description, unique on the shared shop."""
    token = uuid.uuid4().hex[:8]
    return (
        f"etsy-listings e2e {token} -- safe to delete",
        f"Created by automated test run {token}. The Printify product is deleted in teardown.",
    )


@pytest.fixture
def workspace(
    tmp_path_factory: pytest.TempPathFactory,
    credentials_workspace: Workspace,
    etsy_client: HttpEtsyListingClient,
    prerequisite_missing: PrerequisiteMissing,
    copy: tuple[str, str],
) -> Workspace:
    """A fresh copy of the fixture workspace (the same one every offline test
    uses -- real profile, real mockup templates), pointed at the throwaway
    shops named by ``credentials_workspace``."""
    root = tmp_path_factory.mktemp("phase3-e2e") / "workspace"
    shutil.copytree(FIXTURE_WORKSPACE, root)

    # The fixture's own design is the synthetic grid/ruler test image -- far
    # below this garment's real 4500x5400 print area, so `check_design_resolution`
    # would block the product stage before it ever creates anything (silently:
    # a blocked stage is reported, not raised, so the failure only surfaces
    # three stages later as `publish`'s "no product exists"). The offline
    # behaviour tests already swap it for a print-resolution placeholder via
    # `write_design`; this test needs the same thing against the real gate.
    write_design(root, (4500, 5400))

    title, description = copy
    set_copy(root, title=title, description=description)
    point_at_throwaway_shops(root, credentials_workspace, etsy_client, prerequisite_missing)

    return Workspace.discover(root_override=root)


@pytest.fixture
def ctx(
    workspace: Workspace,
    printify_token: str,
    printify_client: PrintifyClient,
    etsy_client: HttpEtsyListingClient,
) -> RunContext:
    catalog = HttpCatalogClient(PrintifyTransport(printify_token))
    return RunContext(
        workspace=workspace, catalog=catalog, printify=printify_client, etsy=etsy_client
    )


@pytest.fixture(autouse=True)
def cleanup_product(
    workspace: Workspace, printify_client: PrintifyClient, copy: tuple[str, str]
) -> Iterator[None]:
    """Deletes the Printify product the journey created, whichever milestone
    it stopped at. Deleting it also removes its Etsy draft (module docstring).

    The lockfile names the product once a run has written it; a failure
    between Printify's create and that write leaves no lockfile, so the
    fallback finds the product by this run's own unique copy."""
    try:
        yield
    finally:
        shop_id = workspace.defaults.printify.require_shop_id()
        existing = Lockfile.read(workspace.lock_file(LISTING))
        product_id = existing.remote.get(PRODUCT_ID_KEY) if existing is not None else None
        if not product_id:
            title, description = copy
            product_id = printify_client.find_product_by_copy(
                shop_id, title=title, description=description
            )
        if product_id:
            printify_client.delete_product(shop_id, str(product_id))


# ------------------------------------------------------------- the full cycle


def _a_first_apply_creates_publishes_and_patches_the_listing(
    ctx: RunContext, workspace: Workspace, title: str
) -> None:
    apply_everything(ctx)
    lock = workspace.lock_file(LISTING)

    written = Lockfile.read(lock)
    assert written is not None
    assert written.remote.get(PRODUCT_ID_KEY)
    assert written.remote.get(ETSY_LISTING_ID_KEY)

    # Every stage wrote a document, which is the only proof that every
    # stage ran: a refusal writes nothing and fails nothing. `etsy_videos`
    # is the exception by design -- this listing has no video yet, and a
    # stage with nothing to place records nothing (the video milestones below
    # are where it runs).
    assert set(written.applied) == {
        "render",
        "printify_product",
        "publish",
        "etsy_listing",
        "etsy_media",
    }

    listing_id = int(written.remote[ETSY_LISTING_ID_KEY])
    live = ctx.require_etsy().get_listing(listing_id, include_images=True)
    assert live is not None
    assert live.title == title
    assert len(live.images) == 4, "one per colour in the fixture listing"

    # The fields only `etsy_listing`'s PATCH can have set. The title is not
    # one of them -- Printify creates the listing carrying the *product's*
    # title, so asserting on it proves nothing about the PATCH,
    # which is how a stage that never ran passed this test for weeks.
    assert live.materials == ("cotton",)
    assert live.who_made == "i_did"
    assert live.when_made == "made_to_order"
    assert live.is_supply is False
    assert live.should_auto_renew is False, "renewal: manual"
    # Resolved from a *name* against the live shop. A stale id here
    # is a 400 that fails the whole PATCH, which is why it is resolved per
    # run rather than cached.
    assert live.shipping_profile_id is not None
    assert live.return_policy_id is not None


def _a_second_plan_reports_no_changes(ctx: RunContext, workspace: Workspace) -> None:
    """Idempotency, against the real APIs: nothing in `listing.yaml`
    changed, so nothing should want to run."""
    planned = plan_listings(ctx, [LISTING], STAGES)
    outcome = planned.outcomes[0]
    assert outcome.ok, outcome.error
    assert outcome.planned is not None
    assert not outcome.planned.plan.has_changes


def _the_listing_is_still_a_draft(ctx: RunContext, workspace: Workspace) -> None:
    """The live-edit check: nothing this tool did activated the listing
     -- `state` is never in the PATCH body, and this is
    what proves the omission holds against the real API."""

    written = Lockfile.read(workspace.lock_file(LISTING))
    assert written is not None
    listing_id = int(written.remote[ETSY_LISTING_ID_KEY])

    live = ctx.require_etsy().get_listing(listing_id)
    assert live is not None
    assert live.state == "draft"


def _getting_the_listing_with_images_returns_a_570xn_url(
    ctx: RunContext, workspace: Workspace
) -> None:
    """ADR-0038, read-only: `getListing?includes=Images` on the real shop
    carries `url_570xN` for a real, already-uploaded image -- the deploy
    review's "On Etsy now" column reads this for a draft. Reads the
    listing the first milestone of this journey created; this step
    itself performs no write of its own (see the e2e credentials note)."""
    written = Lockfile.read(workspace.lock_file(LISTING))
    assert written is not None
    listing_id = int(written.remote[ETSY_LISTING_ID_KEY])

    live = ctx.require_etsy().get_listing(listing_id, include_images=True)

    assert live is not None
    assert live.images, "the first apply of this journey uploaded four"
    assert all(image.url_570xN for image in live.images)


def _reordering_media_and_reapplying_only_touches_the_order(
    ctx: RunContext, workspace: Workspace
) -> None:
    """One colour moved to the front of `media:`. No design changed, so
    this should cost one `image_ids` PATCH and zero uploads."""

    edit_listing(
        workspace.root,
        media=[
            {"template": "flat-lay-01", "colour": "moss"},
            {"template": "flat-lay-01", "colour": "black"},
            {"template": "flat-lay-01", "colour": "blue-jean"},
            {"template": "flat-lay-01", "colour": "ivory"},
        ],
    )

    apply_everything(ctx)

    written = Lockfile.read(workspace.lock_file(LISTING))
    assert written is not None
    listing_id = int(written.remote[ETSY_LISTING_ID_KEY])
    live = ctx.require_etsy().get_listing(listing_id, include_images=True)
    assert live is not None
    assert len(live.images) == 4, "a reorder must not lose or duplicate an image"
    ranked = sorted(live.images, key=lambda image: image.rank or 0)
    moss_id = written.remote["etsy_image_ids"]["flat-lay-01:moss"]
    assert ranked[0].listing_image_id == moss_id


def _variation_images_bind_each_colour_actually_uploaded(
    ctx: RunContext, workspace: Workspace, title: str
) -> None:
    """decision 6, against the real inventory and the real join."""

    edit_listing(
        workspace.root,
        etsy={
            "title": title,
            "description": {"lead": "Created by an automated test."},
            "variation_images": "flat-lay-01",
        },
    )

    apply_everything(ctx)

    written = Lockfile.read(workspace.lock_file(LISTING))
    assert written is not None
    listing_id = int(written.remote[ETSY_LISTING_ID_KEY])
    shop_id = workspace.defaults.etsy.require_shop_id()
    links = ctx.require_etsy().get_listing_variation_images(shop_id, listing_id)
    if len(links) != 4:
        inventory = ctx.require_etsy().get_listing_inventory(listing_id)
        properties = [
            (pv.property_id, pv.values) for p in inventory.products for pv in p.property_values
        ]
        pytest.fail(
            f"expected 4 variation image links, got {len(links)}. This binds against "
            f"Etsy's own inventory (Printify's variant push), not anything this tool "
            f"writes -- if that hasn't materialised yet by the time this test asks, "
            f"resolve_colour_property finds no overlap and the media stage skips "
            f"loudly rather than failing (decision 6, missing variant cells). "
            f"Inventory properties as read: {properties}"
        )
    image_ids = set(written.remote["etsy_image_ids"].values())
    assert {link.image_id for link in links} <= image_ids


def _two_videos_are_placed_and_their_ids_recorded(ctx: RunContext, workspace: Workspace) -> None:
    """decision 9 against the real API: both uploaded with
    `is_multi_video=true`, both `active`. Where each sits in the gallery
    cannot be read back through any API -- the fake's `gallery()` is what
    the behaviour layer asserts; here it is what Etsy accepted."""
    shared = workspace.root / "common-media"
    shared.mkdir(exist_ok=True)
    shutil.copy(VIDEOS / "valid-3s-512.mp4", workspace.root / FEATURED_VIDEO)
    shutil.copy(
        VIDEOS / "with-audio-3s-512.mp4", workspace.listing_dir(LISTING) / "how-it-fits.mp4"
    )
    edit_listing(workspace.root, media=_with_videos(second_after=2))

    apply_everything(ctx)

    written = Lockfile.read(workspace.lock_file(LISTING))
    assert written is not None
    video_ids = written.remote["etsy_video_ids"]
    assert set(video_ids) == {FEATURED_VIDEO, SECOND_VIDEO}
    assert _live_videos(ctx, written) == dict.fromkeys(video_ids.values(), "active")


def _moving_the_second_video_re_attaches_it_without_an_upload(
    ctx: RunContext, workspace: Workspace
) -> None:
    """One image later: the same `video_id`s, so no bytes were re-sent,
    and the swatch links the cut detached are set again (decision 9's
    "What it costs")."""
    before = Lockfile.read(workspace.lock_file(LISTING))
    assert before is not None
    shop_id = workspace.defaults.etsy.require_shop_id()
    listing_id = int(before.remote[ETSY_LISTING_ID_KEY])
    links_before = ctx.require_etsy().get_listing_variation_images(shop_id, listing_id)
    edit_listing(workspace.root, media=_with_videos(second_after=3))

    report = apply_everything(ctx)

    planned = report.outcomes[0].planned
    assert planned is not None
    running = [sp.stage for sp in planned.plan.stage_plans if sp.will_run]
    assert running == ["etsy_videos"], "a video move is no image's business"
    written = Lockfile.read(workspace.lock_file(LISTING))
    assert written is not None
    assert written.remote["etsy_video_ids"] == before.remote["etsy_video_ids"]
    assert set(_live_videos(ctx, written).values()) == {"active"}
    links = ctx.require_etsy().get_listing_variation_images(shop_id, listing_id)
    assert len(links) == len(links_before)
    assert {link.image_id for link in links} <= set(written.remote["etsy_image_ids"].values())


def _re_applying_the_videos_unchanged_writes_nothing(ctx: RunContext, workspace: Workspace) -> None:
    report = apply_everything(ctx)

    planned = report.outcomes[0].planned
    assert planned is not None
    assert not planned.plan.has_changes


# ------------------------------------------------------------- the journey


def test_the_full_cycle_from_nothing_to_a_media_complete_draft(
    ctx: RunContext, workspace: Workspace, copy: tuple[str, str]
) -> None:
    """Nothing to a patched, media-complete draft, then a change on each side
    and a re-apply that only touches what changed. Each milestone is a step of
    this one test, in the order its remote state requires; a failure names the
    step it stopped at, and ``cleanup_product`` deletes whatever was made."""
    title, _ = copy
    _a_first_apply_creates_publishes_and_patches_the_listing(ctx, workspace, title)
    _a_second_plan_reports_no_changes(ctx, workspace)
    _the_listing_is_still_a_draft(ctx, workspace)
    _getting_the_listing_with_images_returns_a_570xn_url(ctx, workspace)
    _reordering_media_and_reapplying_only_touches_the_order(ctx, workspace)
    _variation_images_bind_each_colour_actually_uploaded(ctx, workspace, title)
    _two_videos_are_placed_and_their_ids_recorded(ctx, workspace)
    _moving_the_second_video_re_attaches_it_without_an_upload(ctx, workspace)
    _re_applying_the_videos_unchanged_writes_nothing(ctx, workspace)
