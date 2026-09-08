"""The render cache is gitignored and fully derivable, which makes it a
directory people delete -- and a plan that only compares hashes reported "No
changes." over a half-empty one, with `apply` then doing nothing to restore
it. These are the tests for the second axis: are the files the lockfile
claims were rendered still there?

Also covers what `plan` now reports about the work itself: the actions a stage
would take, the files each reads, and the files each writes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from etsy_listings import __about__
from etsy_listings.catalog.fakes import FakeCatalogClient
from etsy_listings.engine.apply import execute
from etsy_listings.engine.context import Event, RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import build_plan
from etsy_listings.engine.stages import STAGES
from etsy_listings.workspace.workspace import Workspace

LISTING = "take-a-hike"
RENDER_DIR = Path(".cache") / "renders" / LISTING / "flat-lay-01"


def _ctx(workspace_root: Path, events: list[Event] | None = None) -> RunContext:
    workspace = Workspace.discover(root_override=workspace_root)
    catalog = FakeCatalogClient([], {}, {})
    if events is None:
        return RunContext(workspace=workspace, catalog=catalog)
    return RunContext(workspace=workspace, catalog=catalog, on_event=events.append)


def _empty_lock() -> Lockfile:
    return Lockfile.empty(tool_version=__about__.VERSION, applied_at=datetime.now(UTC).isoformat())


def _applied(workspace_root: Path) -> Lockfile:
    ctx = _ctx(workspace_root)
    planned = build_plan(ctx, LISTING, _empty_lock(), STAGES)
    return execute(ctx, planned, _empty_lock())


def _render_plan(workspace_root: Path, lock: Lockfile):
    planned = build_plan(_ctx(workspace_root), LISTING, lock, STAGES)
    return next(sp for sp in planned.plan.stage_plans if sp.stage == "render")


def test_a_deleted_render_makes_plan_want_to_run_again(workspace_root: Path) -> None:
    lock = _applied(workspace_root)
    (workspace_root / RENDER_DIR / "black.png").unlink()

    stage_plan = _render_plan(workspace_root, lock)
    assert stage_plan.will_run is True
    assert stage_plan.reason == "1 rendered file missing from the cache"


def test_the_reason_counts_every_missing_file(workspace_root: Path) -> None:
    lock = _applied(workspace_root)
    (workspace_root / RENDER_DIR / "black.png").unlink()
    (workspace_root / RENDER_DIR / "moss.png").unlink()

    assert _render_plan(workspace_root, lock).reason == "2 rendered files missing from the cache"


def test_apply_actually_restores_the_deleted_render(workspace_root: Path) -> None:
    """The half of the bug that survived a `plan` fix on its own: `apply` has
    to put the file back, not just agree that it is gone."""
    lock = _applied(workspace_root)
    deleted = workspace_root / RENDER_DIR / "black.png"
    deleted.unlink()

    ctx = _ctx(workspace_root)
    execute(ctx, build_plan(ctx, LISTING, lock, STAGES), lock)

    assert deleted.is_file()


def test_an_emptied_cache_directory_is_fully_rebuilt(workspace_root: Path) -> None:
    lock = _applied(workspace_root)
    for png in (workspace_root / RENDER_DIR).glob("*.png"):
        png.unlink()

    ctx = _ctx(workspace_root)
    execute(ctx, build_plan(ctx, LISTING, lock, STAGES), lock)

    assert sorted(p.name for p in (workspace_root / RENDER_DIR).glob("*.png")) == [
        "black.png",
        "blue-jean.png",
        "ivory.png",
        "moss.png",
    ]


def test_an_intact_cache_still_plans_as_a_no_op(workspace_root: Path) -> None:
    """The check must not make every run want to re-render -- that would undo
    the idempotency the whole tool exists for."""
    lock = _applied(workspace_root)
    stage_plan = _render_plan(workspace_root, lock)
    assert stage_plan.will_run is False
    assert stage_plan.actions == ()


def test_plan_names_the_inputs_and_outputs_of_every_action(workspace_root: Path) -> None:
    stage_plan = _render_plan(workspace_root, _empty_lock())

    assert [action.description for action in stage_plan.actions] == [
        "render flat-lay-01/black",
        "render flat-lay-01/blue-jean",
        "render flat-lay-01/ivory",
        "render flat-lay-01/moss",
    ]
    first = stage_plan.actions[0]
    assert first.inputs == (
        "designs/take-a-hike.png",
        "mockup-templates/flat-lay-01/template.yaml",
        "mockup-templates/flat-lay-01/black.png",
    )
    assert first.outputs == (".cache/renders/take-a-hike/flat-lay-01/black.png",)


def test_only_the_missing_outputs_are_flagged_as_missing(workspace_root: Path) -> None:
    lock = _applied(workspace_root)
    (workspace_root / RENDER_DIR / "moss.png").unlink()

    stage_plan = _render_plan(workspace_root, lock)
    flagged = {action.description: bool(action.missing_outputs) for action in stage_plan.actions}
    assert flagged == {
        "render flat-lay-01/black": False,
        "render flat-lay-01/blue-jean": False,
        "render flat-lay-01/ivory": False,
        "render flat-lay-01/moss": True,
    }


def test_a_multiple_kind_scene_lists_every_artwork_it_reads(workspace_root: Path) -> None:
    listing_path = workspace_root / "listings" / LISTING / "listing.yaml"
    text = listing_path.read_text(encoding="utf-8")
    listing_path.write_text(
        text.replace(
            "  - { template: flat-lay-01, colour: moss }\n",
            "  - { template: flat-lay-01, colour: moss }\n  - { template: colour-chart-01 }\n",
        ),
        encoding="utf-8",
    )

    stage_plan = _render_plan(workspace_root, _empty_lock())
    chart = next(a for a in stage_plan.actions if a.description == "render colour-chart-01")
    assert chart.outputs == (".cache/renders/take-a-hike/colour-chart-01/scene.png",)
    assert "mockup-templates/colour-chart-01/scene.png" in chart.inputs
    assert "designs/take-a-hike.png" in chart.inputs


def test_every_render_event_carries_the_garment_colour(workspace_root: Path) -> None:
    """The swatch is what makes a run readable as a colour set rather than a
    column of slugs -- so the stage has to emit it, structured, not as an ANSI
    escape baked into the message."""
    events: list[Event] = []
    ctx = _ctx(workspace_root, events)
    execute(ctx, build_plan(ctx, LISTING, _empty_lock(), STAGES), _empty_lock())

    rendered = [event for event in events if event.message.startswith("rendered ")]
    assert len(rendered) == 4
    for event in rendered:
        assert len(event.swatches) == 1
        assert all(0 <= channel <= 255 for channel in event.swatches[0])

    by_scene = {event.message: event.swatches[0] for event in rendered}
    assert by_scene["rendered flat-lay-01/black"] != by_scene["rendered flat-lay-01/ivory"]


def test_a_multiple_kind_scene_emits_one_swatch_per_placement(workspace_root: Path) -> None:
    listing_path = workspace_root / "listings" / LISTING / "listing.yaml"
    text = listing_path.read_text(encoding="utf-8")
    listing_path.write_text(
        text.replace(
            "  - { template: flat-lay-01, colour: moss }\n",
            "  - { template: flat-lay-01, colour: moss }\n  - { template: colour-chart-01 }\n",
        ),
        encoding="utf-8",
    )

    events: list[Event] = []
    ctx = _ctx(workspace_root, events)
    execute(ctx, build_plan(ctx, LISTING, _empty_lock(), STAGES), _empty_lock())

    chart = next(e for e in events if e.message == "rendered colour-chart-01")
    assert len(chart.swatches) > 1
