"""The opt-in `etsy_activate` stage, against `FakeEtsyListingClient`.

Like `test_etsy_listing_stage`, the Etsy listing id is seeded into the
lockfile rather than minted by running `publish` first.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.core.clients.etsy.models import ReturnPolicy, ShippingProfile
from etsy_listings.core.engine.apply import execute
from etsy_listings.core.engine.change import StagePlan
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.plan import PlannedRun, build_plan
from etsy_listings.core.engine.run import plan_fingerprint
from etsy_listings.core.engine.stage import AnyStage
from etsy_listings.core.engine.stages import (
    STAGES,
    EtsyActivateStage,
    EtsyListingStage,
    publishing_pipeline,
)
from etsy_listings.core.engine.stages.etsy_activate import EtsyActivateDesired

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import (
    a_context,
    a_lock,
    edit_listing,
    set_copy,
    set_etsy_listing_defaults,
    set_etsy_shop_id,
)

SHOP_ID = 12345678
ETSY_LISTING_ID = 4572550919
STAGE = EtsyActivateStage()


@pytest.fixture
def etsy() -> FakeEtsyListingClient:
    return FakeEtsyListingClient(
        shipping_profiles=[ShippingProfile(shipping_profile_id=1, title="NOK standard tee")],
        policies=[
            ReturnPolicy(
                return_policy_id=99,
                accepts_returns=True,
                accepts_exchanges=True,
                return_deadline=30,
            )
        ],
    )


@pytest.fixture
def root(workspace_root: Path) -> Path:
    set_etsy_shop_id(workspace_root, SHOP_ID)
    set_copy(workspace_root, title="Take A Hike Tee", description="A retro sunset.")
    set_etsy_listing_defaults(workspace_root, shipping_profile="NOK standard tee")
    return workspace_root


def _ctx(root: Path, etsy: FakeEtsyListingClient) -> RunContext:
    return a_context(root, etsy=etsy)


def _lock() -> Lockfile:
    return a_lock(remote={"etsy_listing_id": ETSY_LISTING_ID})


def _plan(ctx: RunContext, lock: Lockfile, stages: list[AnyStage] | None = None) -> PlannedRun:
    return build_plan(ctx, LISTING, lock, stages or [STAGE])


def _activate_plan(planned: PlannedRun) -> StagePlan:
    return next(sp for sp in planned.plan.stage_plans if sp.stage == "etsy_activate")


# ----------------------------------------------------------------- opt-in


def test_without_publish_the_pipeline_is_the_draft_only_one() -> None:
    assert publishing_pipeline(publish=False) == STAGES


def test_publish_appends_activation_after_every_other_stage() -> None:
    pipeline = publishing_pipeline(publish=True)

    assert pipeline[:-1] == STAGES
    assert pipeline[-1].name == "etsy_activate"


# ------------------------------------------------------------------- plan


def test_a_draft_is_published_on_apply(root: Path, etsy: FakeEtsyListingClient) -> None:
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=SHOP_ID, state="draft")
    ctx = _ctx(root, etsy)

    planned = _plan(ctx, _lock())
    assert _activate_plan(planned).will_run

    execute(ctx, planned, _lock())

    assert etsy.updated == [{"state": "active"}]
    listing = etsy.get_listing(ETSY_LISTING_ID)
    assert listing is not None
    assert listing.state == "active"


def test_a_listing_not_created_yet_will_be_published(
    root: Path, etsy: FakeEtsyListingClient
) -> None:
    stage_plan = _activate_plan(_plan(_ctx(root, etsy), a_lock()))

    assert stage_plan.will_run
    assert stage_plan.reason is not None
    assert "new listing" in stage_plan.reason


@pytest.mark.parametrize("state", ["active", "inactive", "sold_out", "expired"])
def test_a_listing_that_has_left_draft_is_never_touched(
    root: Path, etsy: FakeEtsyListingClient, state: str
) -> None:
    """``inactive`` is a pause the seller made, or a retirement: not a draft."""
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=SHOP_ID, state=state)

    stage_plan = _activate_plan(_plan(_ctx(root, etsy), _lock()))

    assert not stage_plan.will_run
    assert stage_plan.blocked is None


@pytest.mark.parametrize("lifecycle", ["retired", "renew"])
def test_a_lifecycle_verb_leaves_activation_to_itself(lifecycle: str) -> None:
    verdict = STAGE.plan(EtsyActivateDesired(lifecycle=lifecycle), None, None)

    assert not verdict.will_run
    assert verdict.refusal is None


def test_no_etsy_shop_blocks(workspace_root: Path, etsy: FakeEtsyListingClient) -> None:
    stage_plan = _activate_plan(_plan(_ctx(workspace_root, etsy), a_lock()))

    assert stage_plan.blocked is not None
    assert "will not be published" in stage_plan.blocked


def test_an_earlier_blocked_stage_keeps_the_listing_a_draft(
    root: Path, etsy: FakeEtsyListingClient
) -> None:
    """Empty copy blocks ``etsy_listing``; publishing would put a listing
    with Printify's copy in front of buyers."""
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=SHOP_ID, state="draft")
    edit_listing(root, etsy={"title": "", "description": {"lead": ""}})

    stage_plan = _activate_plan(_plan(_ctx(root, etsy), _lock(), [EtsyListingStage(), STAGE]))

    assert stage_plan.blocked is not None
    assert "stay a draft" in stage_plan.blocked
    assert "etsy_listing" in stage_plan.blocked


# ------------------------------------------- chosen at apply, not at review


def test_the_fingerprint_leaves_the_publish_step_out(
    root: Path, etsy: FakeEtsyListingClient
) -> None:
    """A review plans without ``etsy_activate``; the apply that opts in plans
    with it, and must still match the review (ADR-0039)."""
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=SHOP_ID, state="draft")
    ctx = _ctx(root, etsy)

    reviewed = _plan(ctx, _lock(), [EtsyListingStage()])
    applying = _plan(ctx, _lock(), publishing_pipeline([EtsyListingStage()], publish=True))

    assert _activate_plan(applying).chosen_at_apply
    assert plan_fingerprint(applying.plan) == plan_fingerprint(reviewed.plan)


@pytest.mark.parametrize(
    ("state", "publishable"),
    [("draft", True), ("active", False), ("inactive", False), ("sold_out", False)],
)
def test_a_review_says_whether_an_opt_in_would_publish_the_listing(
    root: Path, etsy: FakeEtsyListingClient, state: str, *, publishable: bool
) -> None:
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=SHOP_ID, state=state)

    planned = _plan(_ctx(root, etsy), _lock(), [EtsyListingStage()])

    assert planned.plan.publishable is publishable


def test_a_listing_not_on_etsy_yet_is_publishable(root: Path, etsy: FakeEtsyListingClient) -> None:
    planned = _plan(_ctx(root, etsy), a_lock(), [EtsyListingStage()])

    assert planned.plan.publishable


def test_a_blocked_stage_makes_the_listing_unpublishable(
    root: Path, etsy: FakeEtsyListingClient
) -> None:
    """The review shows what the apply's held-back ``etsy_activate`` would do."""
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=SHOP_ID, state="draft")
    edit_listing(root, etsy={"title": "", "description": {"lead": ""}})

    planned = _plan(_ctx(root, etsy), _lock(), [EtsyListingStage()])

    assert not planned.plan.publishable


def test_a_listing_marked_for_deletion_is_not_publishable(
    root: Path, etsy: FakeEtsyListingClient
) -> None:
    edit_listing(root, lifecycle="deleted")

    planned = _plan(_ctx(root, etsy), a_lock(), [EtsyListingStage()])

    assert not planned.plan.publishable
