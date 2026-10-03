"""`format_plan` over typed :class:`Plan` values: the terminal text for each
stage outcome, drift and group, with no engine run behind it. Moved from the
`plan` command's tests (test-suite quality plan, PR 9), which keep the
command's own output witnesses."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from etsy_listings.cli.render import format_plan
from etsy_listings.core.engine.change import Drift, Plan, StagePlan

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
