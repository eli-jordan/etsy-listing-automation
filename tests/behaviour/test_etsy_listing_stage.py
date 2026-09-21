"""The `etsy_listing` stage, against `FakeEtsyListingClient` (A4).

Isolated from `publish`: the Etsy listing id this stage needs is seeded
straight into the lockfile's `remote` block rather than produced by running
`publish` first, since A26's within-run threading is `publish`'s own test's
job -- what belongs here is this stage's own resolution, comparison and PATCH.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from etsy_listings.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.clients.etsy.models import (
    ProductionPartner,
    ReturnPolicy,
    ShippingProfile,
    ShopSection,
)
from etsy_listings.engine.apply import execute
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun, build_plan
from etsy_listings.engine.stages.etsy_listing import EtsyListingStage, ReturnPolicyApplied
from etsy_listings.engine.stages.etsy_target import EtsyListingNotMintedError

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import (
    a_context,
    a_lock,
    edit_garment_profile,
    edit_listing,
    set_copy,
    set_etsy_listing_defaults,
    set_etsy_shop_id,
)

SHOP_ID = 12345678

ETSY_LISTING_ID = 4572550919
STAGE = EtsyListingStage()

SHIPPING_PROFILE = ShippingProfile(shipping_profile_id=1, title="NOK standard tee")
RETURN_POLICY = ReturnPolicy(
    return_policy_id=99, accepts_returns=True, accepts_exchanges=True, return_deadline=30
)


@pytest.fixture
def etsy() -> FakeEtsyListingClient:
    client = FakeEtsyListingClient(shipping_profiles=[SHIPPING_PROFILE], policies=[RETURN_POLICY])
    client.seed_listing(ETSY_LISTING_ID, shop_id=12345678)
    return client


@pytest.fixture
def root(workspace_root: Path) -> Path:
    set_etsy_shop_id(workspace_root, SHOP_ID)
    set_copy(workspace_root, title="Take A Hike Tee", description="A retro sunset.")
    set_etsy_listing_defaults(workspace_root, shipping_profile="NOK standard tee")
    return workspace_root


def _ctx(root: Path, etsy: FakeEtsyListingClient) -> RunContext:
    return a_context(root, etsy=etsy)


def _plan(ctx: RunContext, lock: Lockfile) -> PlannedRun:
    return build_plan(ctx, LISTING, lock, [STAGE])


def _stage_plan(ctx: RunContext, lock: Lockfile):
    return _plan(ctx, lock).plan.stage_plans[0]


def _lock_with_listing_id() -> Lockfile:
    return a_lock(remote={"etsy_listing_id": ETSY_LISTING_ID})


def _apply(ctx: RunContext, lock: Lockfile) -> Lockfile:
    return execute(ctx, _plan(ctx, lock), lock)


# ------------------------------------------------------------------ blocking


def test_no_etsy_shop_id_blocks(workspace_root: Path, etsy) -> None:
    """The fixture workspace has no `etsy.shop_id` by default -- the same
    opt-in-only convention `printify.shop_id` already follows."""
    set_copy(workspace_root, title="Take A Hike Tee", description="A retro sunset.")

    stage_plan = _stage_plan(_ctx(workspace_root, etsy), a_lock())

    assert stage_plan.blocked is not None
    assert "setup" in stage_plan.blocked


def test_generate_sentinel_copy_blocks(root: Path, etsy) -> None:
    edit_listing(root, etsy={"title": "<generate>", "description": "<generate>"})

    stage_plan = _stage_plan(_ctx(root, etsy), a_lock())

    assert stage_plan.blocked is not None
    assert "<generate>" in stage_plan.blocked


def test_no_shipping_profile_configured_blocks(workspace_root: Path, etsy) -> None:
    set_etsy_shop_id(workspace_root, SHOP_ID)
    set_copy(workspace_root, title="Take A Hike Tee", description="A retro sunset.")

    stage_plan = _stage_plan(_ctx(workspace_root, etsy), a_lock())

    assert stage_plan.blocked is not None
    assert "shipping_profile" in stage_plan.blocked


def test_an_unresolvable_shipping_profile_name_blocks(root: Path, etsy) -> None:
    set_etsy_listing_defaults(root, shipping_profile="Some other profile")

    stage_plan = _stage_plan(_ctx(root, etsy), a_lock())

    assert stage_plan.blocked is not None
    assert "NOK standard tee" in stage_plan.blocked


def test_who_made_someone_else_with_no_partner_in_the_shop_blocks(root: Path, etsy) -> None:
    set_etsy_listing_defaults(root, who_made="someone_else")

    stage_plan = _stage_plan(_ctx(root, etsy), a_lock())

    assert stage_plan.blocked is not None
    assert "Shop Manager" in stage_plan.blocked


def test_who_made_someone_else_with_a_partner_resolves(root: Path) -> None:
    etsy = FakeEtsyListingClient(
        shipping_profiles=[SHIPPING_PROFILE],
        policies=[RETURN_POLICY],
        production_partners=[
            ProductionPartner(production_partner_id=5785693, partner_name="The Print Provider")
        ],
    )
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=12345678)
    set_etsy_listing_defaults(root, who_made="someone_else")

    stage_plan = _stage_plan(_ctx(root, etsy), a_lock())

    assert stage_plan.blocked is None


def test_an_unresolvable_section_blocks(root: Path, etsy) -> None:
    edit_listing(
        root,
        etsy={
            "title": "Take A Hike Tee",
            "description": "A retro sunset.",
            "section": "Retro Tees",
        },
    )

    stage_plan = _stage_plan(_ctx(root, etsy), a_lock())

    assert stage_plan.blocked is not None
    assert "Retro Tees" in stage_plan.blocked


# ----------------------------------------------------------------- first patch


def test_the_first_plan_says_it_will_patch(root: Path, etsy) -> None:
    stage_plan = _stage_plan(_ctx(root, etsy), a_lock())

    assert stage_plan.will_run
    assert "never been patched" in (stage_plan.reason or "")


def test_apply_patches_the_listing(root: Path, etsy) -> None:
    ctx = _ctx(root, etsy)

    result = _apply(ctx, _lock_with_listing_id())

    assert etsy.updated
    patch = etsy.updated[-1]
    assert patch["title"] == "Take A Hike Tee"
    assert patch["shipping_profile_id"] == SHIPPING_PROFILE.shipping_profile_id
    assert patch["return_policy_id"] == RETURN_POLICY.return_policy_id
    assert result.applied["etsy_listing"]["title"] == "Take A Hike Tee"


def test_apply_without_a_listing_id_fails_loudly(root: Path, etsy) -> None:
    ctx = _ctx(root, etsy)

    with pytest.raises(EtsyListingNotMintedError):
        _apply(ctx, a_lock())


# --------------------------------------------------------------------- no-op


def test_a_second_apply_with_nothing_changed_is_a_no_op(root: Path, etsy) -> None:
    ctx = _ctx(root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())
    updates_so_far = len(etsy.updated)

    stage_plan = _stage_plan(ctx, lock)

    assert stage_plan.will_run is False
    assert len(etsy.updated) == updates_so_far


# --------------------------------------------------------------------- drift


def test_printify_reattaching_its_shipping_profile_is_drift_and_gets_reasserted(
    root: Path, etsy
) -> None:
    ctx = _ctx(root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())

    # Printify republishes and attaches its own US-origin profile (risk 13) --
    # simulated by patching the listing directly, bypassing this stage.
    etsy.update_listing(12345678, ETSY_LISTING_ID, {"shipping_profile_id": 999})

    stage_plan = _stage_plan(ctx, lock)

    assert stage_plan.will_run
    assert stage_plan.drift
    assert stage_plan.drift[0].path == "shipping_profile_id"

    result = _apply(ctx, lock)
    patched = result.applied["etsy_listing"]["shipping_profile_id"]
    assert patched == SHIPPING_PROFILE.shipping_profile_id


def test_a_policy_accepting_neither_describes_as_none() -> None:
    policy = ReturnPolicyApplied(accepts_returns=False, accepts_exchanges=False)

    assert policy.describe() == "no returns or exchanges"


def test_the_drift_names_a_live_section_when_the_catalog_knows_it(root: Path) -> None:
    """Mirrors the shipping-profile case, for `shop_section_id` -- the third
    id whose live side only the catalog can name (A30)."""
    edit_listing(
        root,
        etsy={
            "title": "Take A Hike Tee",
            "description": "A retro sunset.",
            "section": "Retro Tees",
        },
    )
    other_section = ShopSection(shop_section_id=99, title="Seasonal")
    etsy = FakeEtsyListingClient(
        shipping_profiles=[SHIPPING_PROFILE],
        policies=[RETURN_POLICY],
        sections=[ShopSection(shop_section_id=44, title="Retro Tees"), other_section],
    )
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=12345678)
    ctx = _ctx(root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())
    etsy.update_listing(12345678, ETSY_LISTING_ID, {"shop_section_id": 99})

    stage_plan = _stage_plan(ctx, lock)

    section_drift = next(d for d in stage_plan.drift if d.path == "shop_section_id")
    assert section_drift.last_applied_label == "Retro Tees"
    assert section_drift.live_label == "Seasonal"


def test_the_drift_names_the_last_applied_profile(root: Path, etsy) -> None:
    """A30: the last-applied side always has a name -- this stage stores it
    beside the id it resolved -- with no catalog lookup needed for it."""
    ctx = _ctx(root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())
    etsy.update_listing(12345678, ETSY_LISTING_ID, {"shipping_profile_id": 999})

    stage_plan = _stage_plan(ctx, lock)

    assert stage_plan.drift[0].last_applied_label == "NOK standard tee"


def test_the_drift_names_the_live_profile_when_the_catalog_knows_it(root: Path) -> None:
    """The live side has only an id -- naming it needs the shop catalog this
    run already fetched resolving the *desired* shipping profile (A30)."""
    other_profile = ShippingProfile(shipping_profile_id=999, title="US origin")
    etsy = FakeEtsyListingClient(
        shipping_profiles=[SHIPPING_PROFILE, other_profile], policies=[RETURN_POLICY]
    )
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=12345678)
    ctx = _ctx(root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())
    etsy.update_listing(12345678, ETSY_LISTING_ID, {"shipping_profile_id": 999})

    stage_plan = _stage_plan(ctx, lock)

    assert stage_plan.drift[0].live_label == "US origin"


def test_no_catalog_degrades_to_no_live_label_or_live_names(root: Path, etsy) -> None:
    """``catalog`` is only ``None`` for a hand-built ``EtsyListingDesired``
    outside ``desired()`` -- real usage always supplies one. Exercised here
    directly through the stage's own methods, to prove the degradation is a
    missing label, never a crash."""
    ctx = _ctx(root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())
    etsy.update_listing(12345678, ETSY_LISTING_ID, {"shipping_profile_id": 999})
    applied = lock.parse_applied_for("etsy_listing", STAGE.applied_model)
    live = STAGE.read_live(ctx, LISTING, lock, applied)
    desired = dataclasses.replace(STAGE.desired(ctx, LISTING, applied), catalog=None)

    verdict = STAGE.plan(desired, applied, live)
    assert verdict.drift[0].last_applied_label == "NOK standard tee"
    assert verdict.drift[0].live_label is None

    snapshot = STAGE.snapshot(desired, live)
    assert snapshot.live is not None
    assert snapshot.live.shop_section is None
    assert snapshot.live.shipping_profile is None


def test_an_unknown_live_profile_id_has_no_label(root: Path, etsy) -> None:
    """Never guessed at: a live id the catalog does not recognise is left
    unlabelled rather than shown as ``None``'s stringified nonsense."""
    ctx = _ctx(root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())
    etsy.update_listing(12345678, ETSY_LISTING_ID, {"shipping_profile_id": 999})

    stage_plan = _stage_plan(ctx, lock)

    assert stage_plan.drift[0].live_label is None


# ------------------------------------------------------------------ snapshot


def test_the_snapshot_names_the_desired_side(root: Path, etsy) -> None:
    stage_plan = _stage_plan(_ctx(root, etsy), a_lock())

    snapshot = stage_plan.snapshot
    assert snapshot is not None
    assert snapshot.desired.title == "Take A Hike Tee"
    assert snapshot.desired.description == "A retro sunset."
    assert snapshot.desired.materials == ("cotton",)
    assert snapshot.desired.shipping_profile == "NOK standard tee"
    assert snapshot.live is None, "no Etsy id at all yet -- not on Etsy"


def test_materials_come_from_the_garment_profile(root: Path, etsy) -> None:
    edit_garment_profile(root, "comfort-colors-1717", materials=["cotton", "polyester"])

    stage_plan = _stage_plan(_ctx(root, etsy), a_lock())

    snapshot = stage_plan.snapshot
    assert snapshot is not None
    assert snapshot.desired.materials == ("cotton", "polyester")


def test_the_snapshot_names_the_live_side_once_a_listing_exists(root: Path, etsy) -> None:
    ctx = _ctx(root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())

    stage_plan = _stage_plan(ctx, lock)

    snapshot = stage_plan.snapshot
    assert snapshot is not None
    assert snapshot.live is not None
    assert snapshot.live.title == "Take A Hike Tee"
    assert snapshot.live.description == "A retro sunset."
    assert snapshot.live.materials == ("cotton",)
    assert snapshot.live.shipping_profile == "NOK standard tee"


def test_a_blocked_stage_has_no_snapshot(workspace_root: Path, etsy) -> None:
    set_copy(workspace_root, title="Take A Hike Tee", description="A retro sunset.")

    stage_plan = _stage_plan(_ctx(workspace_root, etsy), a_lock())

    assert stage_plan.blocked is not None
    assert stage_plan.snapshot is None
