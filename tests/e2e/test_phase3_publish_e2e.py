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
the product in teardown. The Etsy listing itself survives teardown: Etsy's
cleanup asymmetry (deleting the product orphans the listing rather than
removing it, and there is no delete endpoint this tool is scoped for) means
every run of this test leaves one draft behind in the throwaway shop, to be
cleared by hand occasionally. Nothing here ever sets ``state`` -- the
"live-edit check" at the end confirms the listing is still a draft after
every write this test makes, which is the measurable form of PRD's non-goal
1 (the tool never activates a listing).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterator
from typing import NoReturn

import pytest

from etsy_listings.clients.etsy import EtsyAuthError, HttpEtsyListingClient, OAuthClient, TokenStore
from etsy_listings.clients.etsy import Transport as EtsyTransport
from etsy_listings.clients.printify import HttpCatalogClient, HttpPrintifyClient
from etsy_listings.clients.printify import Transport as PrintifyTransport
from etsy_listings.config.secrets import Secrets
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.run import apply_listings, plan_listings
from etsy_listings.engine.stages import STAGES
from etsy_listings.engine.stages.printify_product import PRODUCT_ID_KEY
from etsy_listings.engine.stages.publish import ETSY_LISTING_ID_KEY
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
    secrets = Secrets.load(credentials_workspace.env_file())
    if not (secrets.etsy_keystring and secrets.etsy_shared_secret):
        prerequisite_missing(
            f"{credentials_workspace.root}: no Etsy app key -- run `etsy-listings auth etsy` there"
        )
    app_key = secrets.require_etsy_app_key()
    store = TokenStore(
        credentials_workspace.root / layout.AUTH_DIR / layout.ETSY_TOKENS_FILE,
        refresh=lambda token: OAuthClient(app_key.keystring).refresh(token),
    )
    if store.load() is None:
        prerequisite_missing(
            f"{credentials_workspace.root}: no stored Etsy sign-in -- run "
            f"`etsy-listings auth etsy` there"
        )
    transport = EtsyTransport(app_key, bearer=store.access_token)
    try:
        transport.ping()
    except EtsyAuthError as exc:
        prerequisite_missing(f"Etsy app key rejected: {exc}")
    return HttpEtsyListingClient(transport)


@pytest.fixture(scope="session")
def printify_client(printify_token: str) -> HttpPrintifyClient:
    return HttpPrintifyClient(PrintifyTransport(printify_token))


# ------------------------------------------------------------- test workspace


@pytest.fixture(scope="class")
def workspace(
    tmp_path_factory: pytest.TempPathFactory, credentials_workspace: Workspace
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
    set_etsy_shop_id(root, credentials_workspace.defaults.etsy.require_shop_id())
    set_copy(
        root,
        title="etsy-listings e2e -- safe to delete",
        description="Created by an automated test. The Printify product is deleted in teardown.",
    )
    set_etsy_listing_defaults(root, who_made="i_did")
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
    printify_client: HttpPrintifyClient,
    etsy_client: HttpEtsyListingClient,
) -> RunContext:
    catalog = HttpCatalogClient(PrintifyTransport(printify_token))
    return RunContext(
        workspace=workspace, catalog=catalog, printify=printify_client, etsy=etsy_client
    )


@pytest.fixture(scope="class", autouse=True)
def cleanup_product(workspace: Workspace, printify_client: HttpPrintifyClient) -> Iterator[None]:
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
        report = apply_listings(ctx, [LISTING], STAGES)

        assert not report.failed, [o.error for o in report.failures]
        lock = workspace.lock_file(LISTING)

        written = Lockfile.read(lock)
        assert written is not None
        assert written.remote.get(PRODUCT_ID_KEY)
        assert written.remote.get(ETSY_LISTING_ID_KEY)

        listing_id = int(written.remote[ETSY_LISTING_ID_KEY])
        live = ctx.require_etsy().get_listing(listing_id, include_images=True)
        assert live is not None
        assert live.title == "etsy-listings e2e -- safe to delete"
        assert len(live.images) == 4, "one per colour in the fixture listing"

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

        report = apply_listings(ctx, [LISTING], STAGES)
        assert not report.failed, [o.error for o in report.failures]

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
                "description": "Created by an automated test.",
                "materials": ["cotton"],
                "variation_images": "flat-lay-01",
            },
        )

        report = apply_listings(ctx, [LISTING], STAGES)
        assert not report.failed, [o.error for o in report.failures]

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
