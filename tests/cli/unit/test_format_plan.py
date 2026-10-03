"""`format_plan` over typed :class:`Plan` values: the terminal text for each
stage outcome, drift and group, with no engine run behind it. Moved from the
`plan` command's tests (test-suite quality plan, PR 9), which keep the
command's own output witnesses."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from etsy_listings.cli.render import format_plan
from etsy_listings.core.engine.change import Action, Drift, Plan, StagePlan

from tests.support.builders import FIXTURE_LISTING as LISTING


def test_a_drift_with_labels_shows_names_not_ids(workspace_root: Path) -> None:
    """ADR-0038: a stage that could resolve a name for a drifted id shows it,
    rather than only the id `format_plan` printed before this PR."""
    plan = Plan(
        listing="take-a-hike",
        is_live=False,
        etsy_listing_id=None,
        stage_plans=(
            StagePlan.no_work(
                "etsy_listing",
                drift=(
                    Drift(
                        path="shipping_profile_id",
                        last_applied=1,
                        live=999,
                        last_applied_label="NOK standard tee",
                        live_label="US origin",
                    ),
                ),
            ),
        ),
    )

    output = format_plan(plan)

    assert "was NOK standard tee, Etsy now says US origin" in output
    assert "999" not in output, "the raw id has a name now, so it need not appear"


def test_a_drift_with_no_label_still_shows_the_raw_values(workspace_root: Path) -> None:
    """Every drift before this PR, and every one whose sides are plain text
    already -- a title, a description -- has no label at all, and `plan`
    must go on printing exactly what it printed before."""
    plan = Plan(
        listing="take-a-hike",
        is_live=False,
        etsy_listing_id=None,
        stage_plans=(
            StagePlan.no_work(
                "etsy_listing",
                drift=(Drift(path="title", last_applied="Old Title", live="New Title"),),
            ),
        ),
    )

    output = format_plan(plan)

    assert "etsy_listing.title was edited outside this tool" in output
    assert "(was" not in output


def test_a_grouped_stage_is_named_under_its_group(workspace_root: Path) -> None:
    """ADR-0045: one gallery, two stages -- a stage the engine groups under
    another is shown under it on every line that names it."""
    grouped = replace(
        StagePlan.work(
            "etsy_videos",
            "the videos in media: changed",
            drift=(Drift(path="videos", last_applied=["a.mp4"], live="missing"),),
        ),
        group="etsy_media",
    )
    plan = Plan(listing=LISTING, is_live=False, etsy_listing_id=None, stage_plans=(grouped,))

    output = format_plan(plan)

    assert "  + etsy_media/etsy_videos (the videos in media: changed)" in output
    assert "! drift  etsy_media/etsy_videos.videos was edited" in output


# ------------------------------------------------------------ blocked stages
#
# The `plan` command's tests used to reach each of these by planning the
# fixture listing through the real pipeline, so every formatting rule also
# re-ran the engine's diff. Which stages block, and with what sentence, is the
# engine's and the stages' to prove (`tests/core/behaviour/test_run.py`,
# `test_printify_product_stage.py`); the shape of the report is this module's.

NO_SHOP = (
    "this listing will not be uploaded to Printify: no Printify shop is configured.\n"
    "Run `etsy-listings setup` to point it at one."
)
"""A two-line stage message: the consequence, then the remedy."""
EMPTY_TITLE = "etsy.title is empty, and Printify requires it"
RENDER = StagePlan.work(
    "render",
    "2 mockups to render",
    actions=(
        Action(
            description="render flat-lay-01 in black",
            inputs=("designs/take-a-hike.png", "mockup-templates/flat-lay-01"),
            outputs=(".cache/renders/black.png",),
            missing_outputs=(".cache/renders/black.png",),
        ),
        Action(description="render flat-lay-01 in ivory"),
    ),
)


def _plan(*stage_plans: StagePlan) -> Plan:
    return Plan(listing=LISTING, is_live=False, etsy_listing_id=None, stage_plans=stage_plans)


def test_a_blocked_stage_is_a_marked_warning_with_its_remedy_indented_under_it() -> None:
    """The stage's first line is the consequence, in the user's terms, marked
    `!` -- a listing silently not reaching Printify is not a note. The remedy
    and the stage name sit indented beneath it."""
    output = format_plan(_plan(StagePlan.block("printify_product", NO_SHOP)))

    assert output.splitlines()[2:5] == [
        "  ! this listing will not be uploaded to Printify: no Printify shop is configured.",
        "      Run `etsy-listings setup` to point it at one.",
        "      (printify_product will not run)",
    ]


def test_blocked_stages_lead_the_work_whatever_order_the_engine_planned_them() -> None:
    """What a run will *not* do is the more surprising half. Reporting the
    work first and qualifying it afterwards is how this was missed."""
    lines = format_plan(_plan(RENDER, StagePlan.block("printify_product", NO_SHOP))).splitlines()

    warning = next(i for i, line in enumerate(lines) if line.startswith("  ! this listing"))
    work = next(i for i, line in enumerate(lines) if line.startswith("  + render"))
    assert warning < work


def test_a_refusal_and_an_unconfigured_stage_read_the_same_way() -> None:
    """One vocabulary: a gate refusal and an opted-out stage are both reasons a
    stage cannot run, so both get the same `!` line and the same count."""
    output = format_plan(
        _plan(
            StagePlan.block("printify_product", EMPTY_TITLE),
            StagePlan.block("etsy_listing", NO_SHOP),
        )
    )

    assert f"  ! {EMPTY_TITLE}\n      (printify_product will not run)" in output
    assert "      (etsy_listing will not run)" in output
    assert output.endswith("  0 to run, 0 to change, 2 blocked, 0 drift warning(s)")


def test_a_blocked_stage_is_counted_apart_from_the_work_beside_it() -> None:
    """Blocked is not "to run" -- nothing will happen to it -- and the work
    the other stages can do stays on screen beside it."""
    output = format_plan(_plan(RENDER, StagePlan.block("printify_product", EMPTY_TITLE)))

    assert "  + render (2 mockups to render)" in output
    assert output.endswith("  1 to run (2 actions), 0 to change, 1 blocked, 0 drift warning(s)")


def test_a_plan_with_nothing_blocked_has_no_warning_and_no_blocked_count() -> None:
    output = format_plan(_plan(RENDER, StagePlan.no_work("printify_product")))

    assert "!" not in output
    assert output.endswith("  1 to run (2 actions), 0 to change, 0 drift warning(s)")


def test_a_run_lists_each_action_with_what_it_reads_and_writes() -> None:
    output = format_plan(_plan(RENDER))

    assert output.splitlines()[2:8] == [
        "  + render (2 mockups to render)",
        "      render flat-lay-01 in black",
        "        in   designs/take-a-hike.png",
        "             mockup-templates/flat-lay-01",
        "        out  .cache/renders/black.png   (missing)",
        "      render flat-lay-01 in ivory",
    ]


def test_one_action_is_counted_in_the_singular() -> None:
    one = StagePlan.work("render", "1 mockup", actions=(Action(description="render"),))

    assert format_plan(_plan(one)).endswith(
        "  1 to run (1 action), 0 to change, 0 drift warning(s)"
    )


def test_only_blocked_stages_still_say_there_are_no_changes() -> None:
    output = format_plan(_plan(StagePlan.block("printify_product", EMPTY_TITLE)))

    assert "  No changes." in output


def test_a_plan_with_no_stages_says_none_are_configured() -> None:
    assert "  (no stages configured)" in format_plan(_plan())


def test_a_live_listing_is_called_out_in_the_header() -> None:
    plan = Plan(listing=LISTING, is_live=True, etsy_listing_id=42, stage_plans=())

    assert format_plan(plan).splitlines()[0] == f"{LISTING}  [LIVE — etsy listing 42]"
