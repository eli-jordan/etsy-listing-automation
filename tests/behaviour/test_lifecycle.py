"""Delete and retire (PRD 61–67), through `plan_listings` / `apply_listings`.

Wrong verb is `Blocked`. Delete is retract-only. Retire still syncs copy.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from etsy_listings.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.clients.etsy.models import ReturnPolicy, ShippingProfile
from etsy_listings.clients.printify.fakes import FakePrintifyClient
from etsy_listings.config.listing_validation import DELETED_ON_PUBLISHED, RETIRED_ON_NEVER_LIVE
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.run import apply_listings, plan_listings
from etsy_listings.engine.stages import STAGES
from etsy_listings.engine.stages.etsy_listing import EtsyListingStage
from etsy_listings.errors import UserFacingError

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import (
    a_context,
    a_lock,
    edit_listing,
    listing_file,
    set_copy,
    set_etsy_listing_defaults,
    set_etsy_shop_id,
    set_shop_id,
)

SHOP_ID = 28819281
ETSY_SHOP_ID = 12345678
ETSY_LISTING_ID = 4572550919
PRODUCT_ID = "6aa332559f8d2ff30103b4c9"

SHIPPING_PROFILE = ShippingProfile(shipping_profile_id=1, title="NOK standard tee")
RETURN_POLICY = ReturnPolicy(
    return_policy_id=99, accepts_returns=True, accepts_exchanges=True, return_deadline=30
)


def _etsy() -> FakeEtsyListingClient:
    return FakeEtsyListingClient(shipping_profiles=[SHIPPING_PROFILE], policies=[RETURN_POLICY])


def _ready(root: Path) -> Path:
    set_shop_id(root, SHOP_ID)
    set_etsy_shop_id(root, ETSY_SHOP_ID)
    set_copy(root, title="Take A Hike Tee", description="A retro sunset.")
    set_etsy_listing_defaults(root, shipping_profile="NOK standard tee")
    return root


def _lock(*, etsy_listing_id: int | None = None, product_id: str | None = None) -> Lockfile:
    remote: dict[str, object] = {}
    if etsy_listing_id is not None:
        remote["etsy_listing_id"] = etsy_listing_id
    if product_id is not None:
        remote["printify_product_id"] = product_id
    return a_lock(remote=remote, stages_completed=["printify_product", "etsy_listing"])


def _write_lock(root: Path, lock: Lockfile) -> None:
    lock.write(root / "listings" / LISTING / "state.lock.json")


def _plan(
    root: Path,
    *,
    etsy: FakeEtsyListingClient | None = None,
    printify: FakePrintifyClient | None = None,
):
    ctx = a_context(root, etsy=etsy, printify=printify or FakePrintifyClient())
    return plan_listings(ctx, [LISTING], STAGES).outcomes[0]


def _blocked_text(outcome) -> str:
    assert outcome.planned is not None
    blocked = [sp.blocked for sp in outcome.planned.plan.stage_plans if sp.blocked]
    assert blocked
    return blocked[0]


class TestWrongVerb:
    def test_deleted_on_a_published_listing_is_blocked(self, workspace_root: Path) -> None:
        root = _ready(workspace_root)
        edit_listing(root, lifecycle="deleted")
        _write_lock(root, _lock(etsy_listing_id=ETSY_LISTING_ID, product_id=PRODUCT_ID))
        etsy = _etsy()
        etsy.seed_listing(ETSY_LISTING_ID, shop_id=ETSY_SHOP_ID, state="active")

        assert _blocked_text(_plan(root, etsy=etsy)) == DELETED_ON_PUBLISHED

    def test_retired_on_a_never_live_listing_is_blocked(self, workspace_root: Path) -> None:
        root = _ready(workspace_root)
        edit_listing(root, lifecycle="retired")
        _write_lock(root, _lock(product_id=PRODUCT_ID))

        assert _blocked_text(_plan(root, etsy=_etsy())) == RETIRED_ON_NEVER_LIVE


class TestMissingYaml:
    def test_a_lockfile_without_listing_yaml_is_blocked(self, workspace_root: Path) -> None:
        root = _ready(workspace_root)
        _write_lock(root, _lock(etsy_listing_id=ETSY_LISTING_ID, product_id=PRODUCT_ID))
        listing_file(root).unlink()

        assert "listing.yaml" in _blocked_text(_plan(root, etsy=_etsy()))
        assert "not consent" in _blocked_text(_plan(root, etsy=_etsy()))


class TestRetract:
    def test_delete_is_retract_only(self, workspace_root: Path) -> None:
        root = _ready(workspace_root)
        edit_listing(root, lifecycle="deleted")
        _write_lock(root, _lock(product_id=PRODUCT_ID))

        outcome = _plan(root, etsy=_etsy(), printify=FakePrintifyClient())
        assert outcome.planned is not None
        stages = [sp.stage for sp in outcome.planned.plan.stage_plans]
        assert stages == ["retract"]
        assert outcome.planned.plan.stage_plans[0].will_run

    def test_apply_deletes_the_printify_product_and_wipes_files(self, workspace_root: Path) -> None:
        root = _ready(workspace_root)
        edit_listing(root, lifecycle="deleted")
        _write_lock(root, _lock(product_id=PRODUCT_ID))
        printify = FakePrintifyClient()
        renders = root / ".cache" / "renders" / LISTING
        renders.mkdir(parents=True)
        (renders / "flat-lay-01-black.png").write_bytes(b"png")
        # A32: a preview left behind by an earlier plan is wiped too.
        previews = root / ".cache" / "previews" / LISTING / "flat-lay-01"
        previews.mkdir(parents=True)
        (previews / "black-deadbeef.png").write_bytes(b"png")

        report = apply_listings(a_context(root, etsy=_etsy(), printify=printify), [LISTING], STAGES)

        assert report.outcomes[0].ok
        assert printify.deleted == [PRODUCT_ID]
        assert printify.updated == []
        assert not (root / "listings" / LISTING).exists()
        assert not renders.exists()
        assert not previews.exists()

    def test_an_etsy_draft_that_survived_printify_delete_keeps_local_files(
        self, workspace_root: Path
    ) -> None:
        root = _ready(workspace_root)
        edit_listing(root, lifecycle="deleted")
        _write_lock(root, _lock(etsy_listing_id=ETSY_LISTING_ID, product_id=PRODUCT_ID))
        etsy = _etsy()
        etsy.seed_listing(ETSY_LISTING_ID, shop_id=ETSY_SHOP_ID, state="draft")
        printify = FakePrintifyClient()

        report = apply_listings(a_context(root, etsy=etsy, printify=printify), [LISTING], STAGES)

        assert not report.outcomes[0].ok
        assert isinstance(report.outcomes[0].error, UserFacingError)
        assert str(ETSY_LISTING_ID) in str(report.outcomes[0].error)
        assert "Shop Manager" in str(report.outcomes[0].error)
        assert listing_file(root).is_file()


class TestEtsyStateWrites:
    def _apply_etsy(self, root: Path, etsy: FakeEtsyListingClient, lock: Lockfile) -> Lockfile:
        from etsy_listings.engine.apply import execute
        from etsy_listings.engine.plan import build_plan

        ctx = a_context(root, etsy=etsy)
        planned = build_plan(ctx, LISTING, lock, [EtsyListingStage()])
        return execute(ctx, planned, lock)

    def test_retire_sends_inactive(self, workspace_root: Path) -> None:
        root = _ready(workspace_root)
        edit_listing(root, lifecycle="retired")
        etsy = _etsy()
        etsy.seed_listing(ETSY_LISTING_ID, shop_id=ETSY_SHOP_ID, state="active")
        lock = _lock(etsy_listing_id=ETSY_LISTING_ID)

        self._apply_etsy(root, etsy, lock)

        assert etsy.updated[-1]["state"] == "inactive"

    def test_un_retire_sends_active(self, workspace_root: Path) -> None:
        root = _ready(workspace_root)
        edit_listing(root, lifecycle="retired")
        etsy = _etsy()
        etsy.seed_listing(ETSY_LISTING_ID, shop_id=ETSY_SHOP_ID, state="active")
        lock = self._apply_etsy(root, etsy, _lock(etsy_listing_id=ETSY_LISTING_ID))

        document = yaml.safe_load(listing_file(root).read_text(encoding="utf-8"))
        document.pop("lifecycle", None)
        listing_file(root).write_text(yaml.safe_dump(document), encoding="utf-8")

        self._apply_etsy(root, etsy, lock)

        assert etsy.updated[-1]["state"] == "active"

    def test_renew_sends_active_and_omits_the_key(self, workspace_root: Path) -> None:
        root = _ready(workspace_root)
        edit_listing(root, lifecycle="renew")
        etsy = _etsy()
        etsy.seed_listing(ETSY_LISTING_ID, shop_id=ETSY_SHOP_ID, state="expired")
        _write_lock(root, _lock(etsy_listing_id=ETSY_LISTING_ID))

        apply_listings(
            a_context(root, etsy=etsy, printify=FakePrintifyClient()),
            [LISTING],
            [EtsyListingStage()],
        )

        assert etsy.updated[-1]["state"] == "active"
        written = yaml.safe_load(listing_file(root).read_text(encoding="utf-8"))
        assert "lifecycle" not in written

    def test_a_remote_pause_does_not_send_active(self, workspace_root: Path) -> None:
        root = _ready(workspace_root)
        etsy = _etsy()
        etsy.seed_listing(ETSY_LISTING_ID, shop_id=ETSY_SHOP_ID, state="inactive")
        lock = _lock(etsy_listing_id=ETSY_LISTING_ID)

        self._apply_etsy(root, etsy, lock)

        assert all("state" not in patch for patch in etsy.updated)

    def test_state_is_never_sent_on_a_draft(self, workspace_root: Path) -> None:
        root = _ready(workspace_root)
        etsy = _etsy()
        etsy.seed_listing(ETSY_LISTING_ID, shop_id=ETSY_SHOP_ID, state="draft")
        lock = _lock(etsy_listing_id=ETSY_LISTING_ID)

        self._apply_etsy(root, etsy, lock)

        assert "state" not in etsy.updated[-1]
