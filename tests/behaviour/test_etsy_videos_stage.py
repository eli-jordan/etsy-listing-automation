"""The `etsy_videos` stage, against `FakeEtsyListingClient` (A4).

Every test asserts the gallery the fake keeps, because nothing in Etsy's API
reports where a video sits (decision 9): `gallery()` is the only place the
layout this stage produced can be read back. `etsy_media` runs first in each
apply, as it does in `STAGES`, so the images a video is placed among exist.
Renders are written straight to `workspace.render_file()`, as
`test_etsy_media_stage.py` does, rather than produced by the renderer.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from etsy_listings.cli.render import format_plan
from etsy_listings.clients.etsy.fakes import DAY_SECONDS, FakeEtsyListingClient
from etsy_listings.clients.etsy.models import Inventory, InventoryProduct, InventoryPropertyValue
from etsy_listings.engine.apply import execute
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun, build_plan
from etsy_listings.engine.run import apply_listings
from etsy_listings.engine.stages.etsy_media import EtsyMediaStage
from etsy_listings.engine.stages.etsy_videos import EtsyVideosStage
from etsy_listings.ui.runs.events import stage_plan_dto

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock, edit_listing, set_etsy_shop_id

ETSY_LISTING_ID = 4572550919
SHOP_ID = 12345678
STAGES = [EtsyMediaStage(), EtsyVideosStage()]
TEMPLATE = "flat-lay-01"
COLOURS = ["black", "blue-jean", "ivory", "moss"]
VIDEOS = Path(__file__).parent.parent / "fixtures" / "video"
FEATURED = "common-media/size-guide.mp4"
SECOND = "./how-it-fits.mp4"


def _image(colour: str) -> dict[str, str]:
    return {"template": TEMPLATE, "colour": colour}


BLACK, BLUE_JEAN, IVORY, MOSS = (_image(c) for c in COLOURS)


@pytest.fixture(autouse=True)
def _workspace(workspace_root: Path) -> None:
    set_etsy_shop_id(workspace_root, SHOP_ID)
    ctx = a_context(workspace_root)
    for colour in COLOURS:
        path = ctx.workspace.render_file(LISTING, TEMPLATE, colour)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png-bytes" + colour.encode())
    (workspace_root / "common-media").mkdir()
    shutil.copy(VIDEOS / "valid-3s-512.mp4", workspace_root / FEATURED)
    shutil.copy(VIDEOS / "with-audio-3s-512.mp4", ctx.workspace.listing_dir(LISTING) / SECOND)


class Clock:
    def __init__(self) -> None:
        self.now = 1_790_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def etsy(clock: Clock) -> FakeEtsyListingClient:
    client = FakeEtsyListingClient(clock=clock)
    client.seed_listing(ETSY_LISTING_ID, shop_id=SHOP_ID)
    return client


@pytest.fixture
def ctx(workspace_root: Path, etsy: FakeEtsyListingClient) -> RunContext:
    return a_context(workspace_root, etsy=etsy)


def _plan(ctx: RunContext, lock: Lockfile) -> PlannedRun:
    return build_plan(ctx, LISTING, lock, STAGES)


def _videos_plan(ctx: RunContext, lock: Lockfile):
    return _plan(ctx, lock).plan.stage_plans[1]


def _apply(ctx: RunContext, lock: Lockfile) -> Lockfile:
    return execute(ctx, _plan(ctx, lock), lock)


def _first_apply(ctx: RunContext) -> Lockfile:
    return _apply(ctx, a_lock(remote={"etsy_listing_id": ETSY_LISTING_ID}))


def _gallery(etsy: FakeEtsyListingClient, lock: Lockfile) -> list[str]:
    """The gallery as refs, so a test reads like the `media:` it wrote."""
    ref_by_id = {
        **{("image", i): ref for ref, i in lock.remote["etsy_image_ids"].items()},
        **{("video", i): ref for ref, i in lock.remote["etsy_video_ids"].items()},
    }
    return [
        ref_by_id.get((slot.kind, slot.id), f"foreign {slot.kind}")
        for slot in etsy.gallery(ETSY_LISTING_ID)
    ]


def _changes(stage_plan) -> list[tuple[str, object, object]]:  # noqa: ANN001
    return [(c.path, c.before, c.after) for c in stage_plan.changes]


def _refs(*media: object) -> list[str]:
    return [f"{m['template']}:{m['colour']}" if isinstance(m, dict) else str(m) for m in media]


TWO_VIDEOS = [BLACK, FEATURED, BLUE_JEAN, SECOND, IVORY, MOSS]


# -------------------------------------------------------------- first apply


def test_a_first_apply_places_both_videos_where_media_puts_them(ctx, etsy, workspace_root) -> None:
    edit_listing(workspace_root, media=TWO_VIDEOS)
    first = a_lock(remote={"etsy_listing_id": ETSY_LISTING_ID})

    assert _changes(_videos_plan(ctx, first)) == [
        ("videos.featured", None, FEATURED),
        ("videos.second", None, SECOND),
    ]
    lock = _first_apply(ctx)

    assert _gallery(etsy, lock) == _refs(*TWO_VIDEOS)
    assert len(etsy.video_uploads) == 2


def test_a_second_apply_with_nothing_changed_writes_nothing(ctx, etsy, workspace_root) -> None:
    edit_listing(workspace_root, media=TWO_VIDEOS)
    lock = _first_apply(ctx)
    writes = (len(etsy.video_uploads), len(etsy.video_attaches), len(etsy.updated))

    assert not _videos_plan(ctx, lock).will_run
    _apply(ctx, lock)

    assert (len(etsy.video_uploads), len(etsy.video_attaches), len(etsy.updated)) == writes


def test_a_listing_without_videos_asks_nothing_of_the_stage(ctx, etsy) -> None:
    lock = _first_apply(ctx)

    assert "etsy_videos" not in lock.applied
    assert etsy.video_uploads == []


# ------------------------------------------------------------ layout changes


def test_swapping_the_videos_re_attaches_both_without_an_upload(ctx, etsy, workspace_root) -> None:
    edit_listing(workspace_root, media=TWO_VIDEOS)
    lock = _first_apply(ctx)
    ids = dict(lock.remote["etsy_video_ids"])

    swapped = [BLACK, SECOND, BLUE_JEAN, FEATURED, IVORY, MOSS]
    edit_listing(workspace_root, media=swapped)
    changes = _changes(_videos_plan(ctx, lock))
    lock = _apply(ctx, lock)

    # Refs, not prose: the deploy review reads New/Removed off these (PRD 71).
    assert changes == [("videos.featured", FEATURED, SECOND), ("videos.second", SECOND, FEATURED)]

    assert len(etsy.video_uploads) == 2, "a swap re-sends no bytes"
    assert lock.remote["etsy_video_ids"] == ids
    assert _gallery(etsy, lock) == _refs(*swapped)


def test_moving_the_second_video_re_attaches_it_after_its_new_anchor(
    ctx, etsy, workspace_root
) -> None:
    edit_listing(workspace_root, media=TWO_VIDEOS)
    lock = _first_apply(ctx)
    ids = dict(lock.remote["etsy_video_ids"])

    moved = [BLACK, FEATURED, BLUE_JEAN, IVORY, SECOND, MOSS]
    edit_listing(workspace_root, media=moved)
    stage_plan = _videos_plan(ctx, lock)
    lock = _apply(ctx, lock)

    assert _changes(stage_plan) == [("videos.second.after_images", 2, 3)]
    assert etsy.video_attaches == [ids[SECOND]], "only the second is touched, by id"
    assert len(etsy.video_uploads) == 2
    assert _gallery(etsy, lock) == _refs(*moved)


def test_replacing_a_files_bytes_uploads_that_one_again(ctx, etsy, workspace_root) -> None:
    edit_listing(workspace_root, media=TWO_VIDEOS)
    lock = _first_apply(ctx)
    replacement = (VIDEOS / "with-audio-3s-512.mp4").read_bytes()
    (workspace_root / FEATURED).write_bytes(replacement)

    stage_plan = _videos_plan(ctx, lock)
    lock = _apply(ctx, lock)

    [(path, before, after)] = _changes(stage_plan)
    assert path == "videos.featured.contents"
    assert str(before).startswith("sha256:") and str(after).startswith("sha256:")
    assert before != after
    assert etsy.video_uploads[-1] == replacement
    assert len(etsy.video_uploads) == 3, "the second is re-attached, not re-sent"
    assert _gallery(etsy, lock) == _refs(*TWO_VIDEOS)


def test_removing_the_videos_deletes_them_from_the_listing(ctx, etsy, workspace_root) -> None:
    edit_listing(workspace_root, media=TWO_VIDEOS)
    lock = _first_apply(ctx)

    edit_listing(workspace_root, media=[BLACK, BLUE_JEAN, IVORY, MOSS])
    changes = _changes(_videos_plan(ctx, lock))
    lock = _apply(ctx, lock)

    assert changes == [("videos.featured", FEATURED, None), ("videos.second", SECOND, None)]

    assert "video" not in [slot.kind for slot in etsy.gallery(ETSY_LISTING_ID)]
    assert lock.remote["etsy_video_ids"] == {}


# ------------------------------------------------------- foreign and drift


def test_a_foreign_video_never_makes_the_stage_run(ctx, etsy, workspace_root) -> None:
    edit_listing(workspace_root, media=TWO_VIDEOS)
    lock = _first_apply(ctx)
    etsy.seed_video(ETSY_LISTING_ID, video_state="inactive")

    stage_plan = _videos_plan(ctx, lock)

    assert not stage_plan.will_run
    assert stage_plan.drift == ()


@pytest.mark.parametrize("video_state", ["active", "inactive"])
def test_a_foreign_video_is_swept_when_the_stage_runs(
    ctx, etsy, workspace_root, video_state: str
) -> None:
    etsy.seed_video(ETSY_LISTING_ID, video_state=video_state)
    edit_listing(workspace_root, media=TWO_VIDEOS)

    lock = _first_apply(ctx)

    assert _gallery(etsy, lock) == _refs(*TWO_VIDEOS)
    live = etsy.get_listing(ETSY_LISTING_ID, include_videos=True)
    assert live is not None
    assert {v.video_id for v in live.videos} == set(lock.remote["etsy_video_ids"].values())


def test_one_of_ours_deleted_outside_is_drift_and_uploaded_again(ctx, etsy, workspace_root) -> None:
    edit_listing(workspace_root, media=TWO_VIDEOS)
    lock = _first_apply(ctx)
    featured_id = lock.remote["etsy_video_ids"][FEATURED]
    etsy.delete_listing_video(SHOP_ID, ETSY_LISTING_ID, featured_id)

    stage_plan = _videos_plan(ctx, lock)
    lock = _apply(ctx, lock)

    assert stage_plan.will_run
    assert [d.last_applied for d in stage_plan.drift] == [[FEATURED]]
    assert len(etsy.video_uploads) == 3
    assert lock.remote["etsy_video_ids"][FEATURED] != featured_id
    assert _gallery(etsy, lock) == _refs(*TWO_VIDEOS)


def test_one_of_ours_gone_inactive_is_drift_and_uploaded_again(ctx, etsy, workspace_root) -> None:
    """Etsy's legacy mode switches a video off without removing it (decision
    9). The tool never causes that, so it is staged as a seeded video the
    lockfile claims."""
    edit_listing(workspace_root, media=[BLACK, FEATURED, BLUE_JEAN, IVORY, MOSS])
    lock = _first_apply(ctx)
    etsy.delete_listing_video(SHOP_ID, ETSY_LISTING_ID, lock.remote["etsy_video_ids"][FEATURED])
    inactive = etsy.seed_video(ETSY_LISTING_ID, video_state="inactive")
    lock = lock.model_copy(
        update={"remote": {**lock.remote, "etsy_video_ids": {FEATURED: inactive.video_id}}}
    )

    stage_plan = _videos_plan(ctx, lock)
    lock = _apply(ctx, lock)

    assert stage_plan.drift
    assert len(etsy.video_uploads) == 2
    assert _gallery(etsy, lock) == _refs(BLACK, FEATURED, BLUE_JEAN, IVORY, MOSS)


# ---------------------------------------------------------------- swatches


def _seed_inventory(etsy: FakeEtsyListingClient) -> None:
    colour = [
        InventoryPropertyValue(
            property_id=513, property_name="Colors", value_ids=(100 + i,), values=(name,)
        )
        for i, name in enumerate(["Black", "Blue Jean", "Ivory", "Moss"])
    ]
    etsy.seed_inventory(
        ETSY_LISTING_ID,
        Inventory(products=tuple(InventoryProduct(property_values=(pv,)) for pv in colour)),
    )


def _swatches(etsy: FakeEtsyListingClient, lock: Lockfile) -> dict[int, str]:
    ref_by_image = {i: ref for ref, i in lock.remote["etsy_image_ids"].items()}
    links = etsy.get_listing_variation_images(SHOP_ID, ETSY_LISTING_ID)
    return {link.value_id: ref_by_image[link.image_id] for link in links}


ALL_SWATCHES = {100 + i: f"{TEMPLATE}:{c}" for i, c in enumerate(COLOURS)}


def test_swatches_are_re_set_after_the_cut_that_places_the_second(
    ctx, etsy, workspace_root
) -> None:
    """Cutting `image_ids` deletes the detached images' swatch links for good
    (decision 9, measured); the fake does the same."""
    _seed_inventory(etsy)
    edit_listing(workspace_root, media=TWO_VIDEOS, etsy={"variation_images": TEMPLATE})
    lock = _first_apply(ctx)
    assert _swatches(etsy, lock) == ALL_SWATCHES

    edit_listing(workspace_root, media=[BLACK, FEATURED, BLUE_JEAN, IVORY, SECOND, MOSS])
    lock = _apply(ctx, lock)

    assert _swatches(etsy, lock) == ALL_SWATCHES


def test_a_crash_between_the_cut_and_the_restore_heals_on_the_next_run(
    ctx, etsy, workspace_root, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_inventory(etsy)
    edit_listing(workspace_root, media=TWO_VIDEOS, etsy={"variation_images": TEMPLATE})
    lock = _first_apply(ctx)
    moved = [BLACK, FEATURED, BLUE_JEAN, IVORY, SECOND, MOSS]
    edit_listing(workspace_root, media=moved)

    def crash(*args: object) -> None:
        raise RuntimeError("the connection dropped")

    with monkeypatch.context() as patched:
        patched.setattr(etsy, "attach_listing_video", crash)
        with pytest.raises(RuntimeError):
            _apply(ctx, lock)
    live = etsy.get_listing(ETSY_LISTING_ID, include_images=True)
    assert live is not None
    assert len(live.images) == 3, "the crash left the listing cut short"

    lock = _apply(ctx, lock)

    assert _gallery(etsy, lock) == _refs(*moved)
    assert _swatches(etsy, lock) == ALL_SWATCHES


# ------------------------------------------------------------ budget (A29)

OTHER = "second-hike"
OTHER_LISTING_ID = 4572550920


def test_a_spent_budget_fails_this_listing_keeps_its_images_and_the_batch_goes_on(
    workspace_root, ctx, etsy, clock: Clock
) -> None:
    """Ten associations per listing per day (decision 9). The refusal is a
    `UserFacingError`, so the batch reports this listing and carries on (PRD
    16), and `etsy_media`'s ids are already on disk (A29): tomorrow's run
    re-uploads no image."""
    workspace = ctx.workspace
    shutil.copytree(workspace.listing_dir(LISTING), workspace.listing_dir(OTHER))
    for colour in COLOURS:
        path = workspace.render_file(OTHER, TEMPLATE, colour)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png-bytes" + colour.encode())
    etsy.seed_listing(OTHER_LISTING_ID, shop_id=SHOP_ID)
    a_lock(remote={"etsy_listing_id": ETSY_LISTING_ID}).write(workspace.lock_file(LISTING))
    a_lock(remote={"etsy_listing_id": OTHER_LISTING_ID}).write(workspace.lock_file(OTHER))
    for _ in range(10):
        clip = etsy.upload_listing_video(SHOP_ID, ETSY_LISTING_ID, file_name="x.mp4", contents=b"")
        etsy.delete_listing_video(SHOP_ID, ETSY_LISTING_ID, clip.video_id)
    edit_listing(workspace_root, media=TWO_VIDEOS)

    report = apply_listings(ctx, [LISTING, OTHER], STAGES)

    failed, other = report.outcomes
    assert "10 video uploads or re-attaches per listing in 24 hours" in str(failed.error)
    assert other.ok
    written = Lockfile.read(workspace.lock_file(LISTING))
    assert written is not None
    assert len(written.remote["etsy_image_ids"]) == 4
    assert "etsy_videos" not in written.applied

    clock.now += DAY_SECONDS
    uploads = len(etsy.uploads)
    report = apply_listings(ctx, [LISTING], STAGES)

    assert report.outcomes[0].ok, report.outcomes[0].error
    assert len(etsy.uploads) == uploads
    written = Lockfile.read(workspace.lock_file(LISTING))
    assert written is not None
    assert _gallery(etsy, written) == _refs(*TWO_VIDEOS)


# ------------------------------------------------------------------ reporting


def test_plan_output_shows_the_videos_under_etsy_media(ctx, workspace_root) -> None:
    edit_listing(workspace_root, media=TWO_VIDEOS)

    output = format_plan(_plan(ctx, a_lock(remote={"etsy_listing_id": ETSY_LISTING_ID})).plan)

    assert "  + etsy_media/etsy_videos (2 video(s), never uploaded)" in output
    assert "  ~ etsy_media/etsy_videos: FieldChange(path='videos.featured'" in output


def test_the_stage_plan_carries_its_group_to_the_review(ctx, workspace_root) -> None:
    edit_listing(workspace_root, media=TWO_VIDEOS)

    stage_plan = _videos_plan(ctx, a_lock(remote={"etsy_listing_id": ETSY_LISTING_ID}))
    dto = stage_plan_dto(stage_plan)

    assert dto.stage == "etsy_videos"
    assert dto.group == "etsy_media"
    assert dto.snapshot is not None
    assert [(v.ref, v.after_images) for v in dto.snapshot.desired] == [
        (FEATURED, None),
        (SECOND, 2),
    ]


def test_a_second_video_at_the_end_is_placed_without_a_cut(ctx, etsy, workspace_root) -> None:
    at_the_end = [BLACK, FEATURED, BLUE_JEAN, IVORY, MOSS, SECOND]
    edit_listing(workspace_root, media=at_the_end)

    lock = _first_apply(ctx)

    assert _gallery(etsy, lock) == _refs(*at_the_end)
    assert [list(u) for u in etsy.updated] == [["image_ids"]], "etsy_media's order, no cut"


# ------------------------------------------------------------------ refusals


def test_a_video_etsy_would_reject_blocks_the_stage(ctx, etsy, workspace_root) -> None:
    shutil.copy(VIDEOS / "short-2s-512.mp4", workspace_root / FEATURED)
    edit_listing(workspace_root, media=TWO_VIDEOS)

    stage_plan = _videos_plan(ctx, a_lock(remote={"etsy_listing_id": ETSY_LISTING_ID}))

    assert stage_plan.blocked is not None
    assert FEATURED in stage_plan.blocked


def test_a_workspace_with_no_etsy_shop_blocks_only_a_listing_with_videos(
    ctx, workspace_root
) -> None:
    shop = workspace_root / "shop.yaml"
    shop.write_text(shop.read_text(encoding="utf-8").replace(str(SHOP_ID), "null"), "utf-8")
    lock = a_lock()

    assert _videos_plan(a_context(workspace_root), lock).blocked is None
    edit_listing(workspace_root, media=TWO_VIDEOS)
    blocked = _videos_plan(a_context(workspace_root), lock).blocked
    assert blocked is not None
    assert blocked.startswith("this listing's videos will not be uploaded to Etsy")
