"""The full Phase 3 cycle against real Printify and Etsy APIs. ``-m e2e``,
skipped by default.

Where Phase 2's e2e layer was recon over raw ``httpx`` -- the client did not
exist yet -- this drives the real pipeline: ``plan_listings``/
``apply_listings`` over the actual ``STAGES``, against
:class:`~etsy_listings.clients.printify.HttpPrintifyClient` and
:class:`~etsy_listings.clients.etsy.HttpEtsyListingClient`. The recon this
phase was built from lives in
[docs/printify-etsy-integration.md](../../docs/printify-etsy-integration.md);
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
test makes, which is the measurable form of PRD's non-goal 1 (the tool never
activates a listing).

**Every stage must actually run.** A blocked stage is reported, not raised,
and ``RunReport.failed`` does not count one -- so ``assert not report.failed``
passes over a stage that refused, and the layer reports green for work it
never did. It did: `etsy_listing` was blocked for want of a shipping profile
through every run of this test, so the `updateListing` PATCH at the centre of
PRD 52-59 was never once sent against the real API, while the first test's
title assertion passed anyway because Printify creates the listing from the
*product's* title (PRD 44). :func:`apply_everything` is the guard -- no stage
may refuse -- and the workspace fixture now resolves a shipping profile from
the shop it is pointed at rather than leaving one unset.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NoReturn

import pytest

from etsy_listings import connections
from etsy_listings.clients.etsy import EtsyAuthError, HttpEtsyListingClient
from etsy_listings.clients.printify import HttpCatalogClient
from etsy_listings.clients.printify import Transport as PrintifyTransport
from etsy_listings.clients.printify.protocol import PrintifyClient
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.run import RunReport, apply_listings, plan_listings
from etsy_listings.engine.stages import STAGES
from etsy_listings.engine.stages.etsy_target import ETSY_LISTING_ID_KEY
from etsy_listings.engine.stages.printify_product import PRODUCT_ID_KEY
from etsy_listings.workspace import layout
from etsy_listings.workspace.userpath import to_native_path
from etsy_listings.workspace.workspace import Workspace

from tests.conftest import FIXTURE_WORKSPACE
from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import (
    edit_garment_profile,
    edit_listing,
    set_copy,
    set_etsy_listing_defaults,
    set_etsy_shop_id,
    set_shop_id,
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
"""The order the reorder test below leaves `media:` in."""


def _with_videos(*, second_after: int) -> list[object]:
    """The images, with the featured video at position 2 (PRD 71) and the
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


# ------------------------------------------------------- credentials workspace


PrerequisiteMissing = Callable[[str], NoReturn]


@pytest.fixture(scope="session")
def credentials_workspace(prerequisite_missing: PrerequisiteMissing) -> Workspace:
    """The already-set-up workspace named by ``ETSY_LISTINGS_ROOT`` -- the
    source of the shop ids and the Etsy sign-in this test borrows rather than
    fabricates. Distinct from the *test* workspace below, which is a fresh
    copy of the fixture that this test actually renders and applies into.
    """
    root = os.environ.get(layout.ROOT_ENV_VAR)
    if not root:
        prerequisite_missing(
            f"{layout.ROOT_ENV_VAR} must point at a workspace that has already run "
            f"`etsy-listings setup` and `etsy-listings auth etsy`"
        )
    workspace = Workspace.discover(root_override=to_native_path(root))
    if workspace.defaults.printify.shop_id is None:
        prerequisite_missing(f"{root}: no printify.shop_id -- run `etsy-listings setup` there")
    if workspace.defaults.etsy.shop_id is None:
        prerequisite_missing(f"{root}: no etsy.shop_id -- run `etsy-listings setup` there")
    return workspace


@pytest.fixture(scope="session")
def etsy_client(
    credentials_workspace: Workspace, prerequisite_missing: PrerequisiteMissing
) -> HttpEtsyListingClient:
    """The same connection `apply` uses, assembled the same way.

    Built through ``connections`` rather than by hand: this fixture was the
    fourth copy of that five-step sequence, and the one nobody would remember
    to update -- it only runs where there are real credentials. What is left
    here is the part that is genuinely the e2e layer's, which is deciding
    what counts as a missing prerequisite.
    """
    root = credentials_workspace.root
    transport = connections.etsy_transport(root)
    if transport is None:
        prerequisite_missing(f"{root}: no Etsy app key -- run `etsy-listings auth etsy` there")
    if connections.etsy_token_store(root).load() is None:
        prerequisite_missing(
            f"{root}: no stored Etsy sign-in -- run `etsy-listings auth etsy` there"
        )
    try:
        transport.ping()
    except EtsyAuthError as exc:
        prerequisite_missing(f"Etsy app key rejected: {exc}")
    return HttpEtsyListingClient(transport)


@pytest.fixture(scope="session")
def printify_client(printify_token: str) -> PrintifyClient:
    return connections.printify_client_for(printify_token)


# ------------------------------------------------------------- test workspace


def apply_everything(ctx: RunContext) -> RunReport:
    """Apply, and insist the whole pipeline actually ran.

    ``report.failed`` is not enough on its own. A stage that refuses is
    *reported*, not failed -- PRD 16's rule, and the right one -- so an
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


@pytest.fixture(scope="class")
def workspace(
    tmp_path_factory: pytest.TempPathFactory,
    credentials_workspace: Workspace,
    etsy_client: HttpEtsyListingClient,
    prerequisite_missing: PrerequisiteMissing,
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

    set_shop_id(root, credentials_workspace.defaults.printify.require_shop_id())
    etsy_shop_id = credentials_workspace.defaults.etsy.require_shop_id()
    set_etsy_shop_id(root, etsy_shop_id)
    set_copy(
        root,
        title="etsy-listings e2e -- safe to delete",
        description="Created by an automated test. The Printify product is deleted in teardown.",
    )
    # A shipping profile is **required** for `etsy_listing` to run at all
    # (decision 2: no listing- or shop-level name means a `Blocked`), and
    # leaving it unset is what kept that stage out of every run of this test.
    # Resolved from the shop rather than hard-coded, so this configures itself
    # against whichever throwaway shop it is pointed at -- and by name, which
    # is also what exercises A25's name -> id resolution against the real API.
    profiles = [p for p in etsy_client.shipping_profiles(etsy_shop_id) if not p.is_deleted]
    if not profiles:
        prerequisite_missing(
            f"Etsy shop {etsy_shop_id} has no shipping profile -- create one in Shop Manager; "
            f"`etsy_listing` cannot patch a listing without one (PRD 58)"
        )
    set_etsy_listing_defaults(root, who_made="i_did", shipping_profile=profiles[0].title)
    # `i_did`, not the real `someone_else` default: this throwaway shop is not
    # guaranteed to have a production partner declared, and the point of this
    # test is the publish/patch/media cycle, not decision 3's partner ladder
    # (covered at the unit and behaviour layers already).

    # The fixture garment profile's `XXL`/`XXXL` are the offline fakes' own
    # naming, shared with every unit and behaviour test that uses this
    # fixture -- not what the real Comfort Colors 1717 / Monster Digital
    # catalog calls them (`2XL`/`3XL`/`4XL`). Overridden here, in this test's
    # own copy only, so size resolution against the live catalog doesn't
    # raise `UnknownSizeError`; size-naming itself is already covered offline
    # and isn't this test's job.
    edit_garment_profile(
        root, "comfort-colors-1717", sizes=["S", "M", "L", "XL", "2XL", "3XL", "4XL"]
    )
    edit_listing(
        root,
        prices={
            "S": "349 NOK",
            "M": "349 NOK",
            "L": "349 NOK",
            "XL": "359 NOK",
            "2XL": "369 NOK",
            "3XL": "379 NOK",
            "4XL": "379 NOK",
        },
    )

    return Workspace.discover(root_override=root)


@pytest.fixture(scope="class")
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


@pytest.fixture(scope="class", autouse=True)
def cleanup_product(workspace: Workspace, printify_client: PrintifyClient) -> Iterator[None]:
    """Deletes the Printify product the class's tests create, once, after the
    whole ordered sequence has run. The Etsy listing it published cannot be
    cleaned up the same way -- see the module docstring's note on the
    cleanup asymmetry."""
    try:
        yield
    finally:
        existing = Lockfile.read(workspace.lock_file(LISTING))
        product_id = existing.remote.get(PRODUCT_ID_KEY) if existing is not None else None
        if product_id:
            shop_id = workspace.defaults.printify.require_shop_id()
            printify_client.delete_product(shop_id, str(product_id))


# ------------------------------------------------------------- the full cycle


class TestTheFullCycle:
    """One ordered sequence: nothing to a patched, media-complete draft, then
    a change on each side and a re-apply that only touches what changed."""

    def test_a_first_apply_creates_publishes_and_patches_the_listing(
        self, ctx: RunContext, workspace: Workspace
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
        # stage with nothing to place records nothing (the video tests below
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
        assert live.title == "etsy-listings e2e -- safe to delete"
        assert len(live.images) == 4, "one per colour in the fixture listing"

        # The fields only `etsy_listing`'s PATCH can have set. The title is not
        # one of them -- Printify creates the listing carrying the *product's*
        # title (PRD 44), so asserting on it proves nothing about the PATCH,
        # which is how a stage that never ran passed this test for weeks.
        assert live.materials == ("cotton",)
        assert live.who_made == "i_did"
        assert live.when_made == "made_to_order"
        assert live.is_supply is False
        assert live.should_auto_renew is False, "renewal: manual"
        # Resolved from a *name* against the live shop (A25). A stale id here
        # is a 400 that fails the whole PATCH, which is why it is resolved per
        # run rather than cached.
        assert live.shipping_profile_id is not None
        assert live.return_policy_id is not None

    def test_a_second_plan_reports_no_changes(self, ctx: RunContext, workspace: Workspace) -> None:
        """Idempotency, against the real APIs: nothing in `listing.yaml`
        changed, so nothing should want to run."""
        planned = plan_listings(ctx, [LISTING], STAGES)
        outcome = planned.outcomes[0]
        assert outcome.ok, outcome.error
        assert outcome.planned is not None
        assert not outcome.planned.plan.has_changes

    def test_the_listing_is_still_a_draft(self, ctx: RunContext, workspace: Workspace) -> None:
        """The live-edit check: nothing this tool did activated the listing
        (PRD non-goal 1) -- `state` is never in the PATCH body, and this is
        what proves the omission holds against the real API."""

        written = Lockfile.read(workspace.lock_file(LISTING))
        assert written is not None
        listing_id = int(written.remote[ETSY_LISTING_ID_KEY])

        live = ctx.require_etsy().get_listing(listing_id)
        assert live is not None
        assert live.state == "draft"

    def test_getting_the_listing_with_images_returns_a_570xn_url(
        self, ctx: RunContext, workspace: Workspace
    ) -> None:
        """A30, read-only: `getListing?includes=Images` on the real shop
        carries `url_570xN` for a real, already-uploaded image -- the deploy
        review's "On Etsy now" column reads this for a draft. Reads the
        listing an earlier test in this sequence already created; this test
        itself performs no write of its own (see the e2e credentials note)."""
        written = Lockfile.read(workspace.lock_file(LISTING))
        assert written is not None
        listing_id = int(written.remote[ETSY_LISTING_ID_KEY])

        live = ctx.require_etsy().get_listing(listing_id, include_images=True)

        assert live is not None
        assert live.images, "the earlier apply in this sequence uploaded four"
        assert all(image.url_570xN for image in live.images)

    def test_reordering_media_and_reapplying_only_touches_the_order(
        self, ctx: RunContext, workspace: Workspace
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

    def test_variation_images_bind_each_colour_actually_uploaded(
        self, ctx: RunContext, workspace: Workspace
    ) -> None:
        """decision 6, against the real inventory and the real join."""

        edit_listing(
            workspace.root,
            etsy={
                "title": "etsy-listings e2e -- safe to delete",
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
                f"loudly rather than failing (decision 6, PRD 46). "
                f"Inventory properties as read: {properties}"
            )
        image_ids = set(written.remote["etsy_image_ids"].values())
        assert {link.image_id for link in links} <= image_ids

    # -------------------------------------------------- videos (PRD 71)

    def test_two_videos_are_placed_and_their_ids_recorded(
        self, ctx: RunContext, workspace: Workspace
    ) -> None:
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

    def test_moving_the_second_video_re_attaches_it_without_an_upload(
        self, ctx: RunContext, workspace: Workspace
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

    def test_re_applying_the_videos_unchanged_writes_nothing(
        self, ctx: RunContext, workspace: Workspace
    ) -> None:
        report = apply_everything(ctx)

        planned = report.outcomes[0].planned
        assert planned is not None
        assert not planned.plan.has_changes
