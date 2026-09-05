"""Behaviour tests for the render stage through the real engine (plan + apply),
against the fixture workspace's fake catalog-free listing. No fakes needed
here -- the render stage is local-only, so there's no remote to fake."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from etsy_listings import __about__
from etsy_listings.catalog.fakes import FakeCatalogClient
from etsy_listings.engine.apply import execute
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import build_plan
from etsy_listings.engine.stages import STAGES
from etsy_listings.engine.stages.render import ArtworkResolutionError, TemplateNotFoundError
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

    renders_dir = workspace_root / ".cache" / "renders" / LISTING / "flat-lay-01"
    for colour in ("black", "blue-jean", "ivory", "moss"):
        assert (renders_dir / f"{colour}.png").is_file()

    assert "render" in lock.applied
    assert lock.stages_completed == ["render"]
    assert len(lock.outputs) == 4


def test_apply_only_renders_scenes_referenced_by_media(workspace_root: Path) -> None:
    """Rendering is media-driven (item 4): dropping a colour's media entry
    means it doesn't render, even though it's still in `colors:`."""
    listing_path = workspace_root / "listings" / LISTING / "listing.yaml"
    text = listing_path.read_text(encoding="utf-8")
    listing_path.write_text(
        text.replace("  - { template: flat-lay-01, colour: moss }\n", ""), encoding="utf-8"
    )

    ctx = _ctx(workspace_root)
    plan = build_plan(ctx, LISTING, _empty_lock(), STAGES)
    lock = execute(ctx, plan, _empty_lock(), STAGES)

    renders_dir = workspace_root / ".cache" / "renders" / LISTING / "flat-lay-01"
    for colour in ("black", "blue-jean", "ivory"):
        assert (renders_dir / f"{colour}.png").is_file()
    assert not (renders_dir / "moss.png").is_file()
    assert len(lock.outputs) == 3


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


def test_media_referencing_a_template_with_no_directory_names_it(workspace_root: Path) -> None:
    """There is no profile-level registry of available templates -- any
    template a listing's media references must simply exist on disk. A typo
    or a not-yet-created template fails loudly, naming the template and where
    it looked, rather than a raw pathlib FileNotFoundError."""
    listing_path = workspace_root / "listings" / LISTING / "listing.yaml"
    text = listing_path.read_text(encoding="utf-8")
    listing_path.write_text(
        text.replace(
            "  - { template: flat-lay-01, colour: moss }\n",
            "  - { template: flat-lay-01, colour: moss }\n  - { template: does-not-exist }\n",
        ),
        encoding="utf-8",
    )

    ctx = _ctx(workspace_root)
    with pytest.raises(TemplateNotFoundError, match="does-not-exist"):
        build_plan(ctx, LISTING, _empty_lock(), STAGES)


def test_apply_renders_a_multiple_kind_scene_as_one_composite(workspace_root: Path) -> None:
    """`colour-chart-01` (multiple kind) exists in the fixture workspace but
    isn't referenced by take-a-hike's media by default -- add a reference and
    confirm it renders to exactly one file, not one per placement. There is
    no profile-level declaration needed: any listing may reference any
    template that actually exists on disk."""
    listing_path = workspace_root / "listings" / LISTING / "listing.yaml"
    text = listing_path.read_text(encoding="utf-8")
    listing_path.write_text(
        text.replace(
            "  - { template: flat-lay-01, colour: moss }\n",
            "  - { template: flat-lay-01, colour: moss }\n  - { template: colour-chart-01 }\n",
        ),
        encoding="utf-8",
    )

    ctx = _ctx(workspace_root)
    plan = build_plan(ctx, LISTING, _empty_lock(), STAGES)
    lock = execute(ctx, plan, _empty_lock(), STAGES)

    chart_file = workspace_root / ".cache" / "renders" / LISTING / "colour-chart-01" / "scene.png"
    assert chart_file.is_file()
    assert len(lock.outputs) == 5  # 4 colour-matrix outputs + 1 chart composite


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


@pytest.mark.parametrize("colour", ["black", "moss"])
def test_replacing_any_colours_photo_triggers_a_rerender(workspace_root: Path, colour: str) -> None:
    """Every colour's photo is an input, not just the first one.

    `template_hash` used to be one digest per *template*, built with
    `setdefault` while looping over (template, colour) pairs -- so a
    colour-matrix set hashed its template.yaml concatenated with whichever
    colour happened to come first, and the other photos entered no hash at
    all. Replacing `moss.png` therefore changed nothing `plan` looked at: it
    reported "No changes." and left the stale render sitting in the cache.
    Photos are now hashed per scene (`base_hash`), so both cases re-run.
    """
    ctx = _ctx(workspace_root)
    lock = execute(ctx, build_plan(ctx, LISTING, _empty_lock(), STAGES), _empty_lock(), STAGES)

    photo = workspace_root / "mockup-templates" / "flat-lay-01" / f"{colour}.png"
    photo.write_bytes(photo.read_bytes() + b"\x00")

    render_plan = next(
        sp for sp in build_plan(ctx, LISTING, lock, STAGES).stage_plans if sp.stage == "render"
    )
    assert render_plan.will_run is True
    assert render_plan.reason == "design or template changed"


# --- artwork resolution errors point at the right file -----------------------


def test_an_unsatisfiable_template_override_names_the_key_and_its_source() -> None:
    """A `single` template carrying `artwork: on-light` over a single-file
    design used to report only "colour 'white' needs an artwork but none
    resolves" -- which reads as a problem with the colour or the listing,
    while the demand came from the template and `on-light` appeared nowhere
    in the message."""
    error = ArtworkResolutionError(
        "white",
        None,
        ["default"],
        wanted="on-light",
        source="the template's own artwork: override",
    )
    message = str(error)

    assert "on-light" in message  # the key that was asked for
    assert "template" in message  # where the demand came from
    assert "['default']" in message  # what the design actually offers


def test_an_unresolvable_artwork_still_reports_the_old_way() -> None:
    """Nothing asked for a specific key -- a multi-key design with no tone,
    no override and no sole key to fall back on."""
    message = str(ArtworkResolutionError("moss", "dark", ["on-dark", "on-light"]))
    assert "none resolves" in message
    assert "tone: dark" in message
