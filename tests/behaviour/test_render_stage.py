"""Behaviour tests for the render stage through the real engine (plan + apply),
against the fixture workspace's fake catalog-free listing. No fakes needed
here -- the render stage is local-only, so there's no remote to fake."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from etsy_listings import __about__
from etsy_listings.catalog.fakes import FakeCatalogClient
from etsy_listings.engine.apply import execute
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import build_plan
from etsy_listings.engine.stages import STAGES
from etsy_listings.workspace.workspace import Workspace

LISTING = "take-a-hike"


def _ctx(workspace_root: Path) -> RunContext:
    workspace = Workspace.discover(root_override=workspace_root)
    return RunContext(workspace=workspace, catalog=FakeCatalogClient([], {}, {}))


def _empty_lock() -> Lockfile:
    return Lockfile.empty(tool_version=__about__.VERSION, applied_at=datetime.now(UTC).isoformat())


def test_first_plan_says_render_needs_to_run(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root)
    plan = build_plan(ctx, LISTING, _empty_lock(), STAGES)
    render_plan = next(sp for sp in plan.stage_plans if sp.stage == "render")
    assert render_plan.will_run is True
    assert render_plan.reason == "no previous render"


def test_apply_renders_a_file_per_colour(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root)
    plan = build_plan(ctx, LISTING, _empty_lock(), STAGES)
    lock = execute(ctx, plan, _empty_lock(), STAGES)

    renders_dir = workspace_root / ".cache" / "renders" / LISTING
    for colour in ("black", "blue-jean", "ivory", "moss"):
        assert (renders_dir / f"{colour}.png").is_file()

    assert "render" in lock.applied
    assert lock.stages_completed == ["render"]
    assert len(lock.outputs) == 4


def test_second_plan_after_apply_is_a_no_op(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root)
    first_plan = build_plan(ctx, LISTING, _empty_lock(), STAGES)
    lock = execute(ctx, first_plan, _empty_lock(), STAGES)

    second_plan = build_plan(ctx, LISTING, lock, STAGES)
    render_plan = next(sp for sp in second_plan.stage_plans if sp.stage == "render")
    assert render_plan.will_run is False


def test_apply_twice_produces_byte_identical_applied_subtree(workspace_root: Path) -> None:
    """The PRD's idempotency check: apply twice in a row, the second is a no-op
    -- here specifically, the lockfile's hashed `applied` subtree is unchanged."""
    ctx = _ctx(workspace_root)
    plan_a = build_plan(ctx, LISTING, _empty_lock(), STAGES)
    lock_a = execute(ctx, plan_a, _empty_lock(), STAGES)

    plan_b = build_plan(ctx, LISTING, lock_a, STAGES)
    lock_b = execute(ctx, plan_b, lock_a, STAGES)

    assert lock_a.input_hash() == lock_b.input_hash()


def test_changing_the_design_triggers_a_rerender(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root)
    plan_a = build_plan(ctx, LISTING, _empty_lock(), STAGES)
    lock_a = execute(ctx, plan_a, _empty_lock(), STAGES)

    design_path = workspace_root / "designs" / "take-a-hike.png"
    design_path.write_bytes(
        design_path.read_bytes() + b"\x00"
    )  # corrupt-but-still-different bytes...

    # A byte appended to a PNG doesn't change what PIL decodes, but the render
    # stage hashes the file's raw bytes (not decoded pixels) -- input_hash must
    # differ even though the pixels would render identically.
    plan_b = build_plan(ctx, LISTING, lock_a, STAGES)
    render_plan = next(sp for sp in plan_b.stage_plans if sp.stage == "render")
    assert render_plan.will_run is True
    assert render_plan.reason == "design or template changed"
