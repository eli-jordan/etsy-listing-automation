"""Confirming a staging session (batch plan PR 2; spec *Confirming a batch*,
*Frozen staging*; A38, A39, A46).

What is on disk afterwards is the assertion: the listings, their designs and
their files. A crash is simulated by failing the atomic rename every durable
write ends in, which is the one place a crash can split two steps.
"""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from etsy_listings.batches import (
    Batch,
    BatchStore,
    ConfirmRefused,
    StagingStore,
    confirm,
    retry_row,
    stage_pngs,
)
from etsy_listings.workspace.workspace import Workspace

from tests.support.batches import LOCAL_PICTURE, a_listing_template, png, uploads
from tests.support.builders import FIXTURE_LISTING, copy_listing

NOW = datetime(2026, 9, 27, 11, 42, tzinfo=UTC)
DESIGNS = (("Night Hike Club.png", png(1)), ("cedar-trail.png", png(2)), ("lake_loop.png", png(3)))
NAMES = ["night-hike-club", "cedar-trail", "lake-loop"]


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    workspace = Workspace.discover(root_override=workspace_root)
    a_listing_template(workspace)
    return workspace


@pytest.fixture
def staging(workspace: Workspace) -> StagingStore:
    return StagingStore(workspace)


@pytest.fixture
def batches(workspace: Workspace) -> BatchStore:
    return BatchStore(workspace)


def _stage(workspace: Workspace, staging: StagingStore, *files: tuple[str, bytes]) -> str:
    return stage_pngs(workspace, staging, "heavyweight-tee", uploads(*files), now=NOW).id


def _confirm(workspace: Workspace, staging: StagingStore, batches: BatchStore, id_: str) -> Batch:
    return confirm(workspace, staging, batches, id_, now=NOW)


def _listing(workspace: Workspace, name: str) -> dict:
    return yaml.safe_load(workspace.listing_file(name).read_text(encoding="utf-8"))


def _created(workspace: Workspace) -> list[str]:
    return [name for name in workspace.listing_names() if name != FIXTURE_LISTING]


class TestConfirm:
    def test_each_design_becomes_an_ordinary_listing_and_staging_goes(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        id_ = _stage(workspace, staging, *DESIGNS)

        batch = _confirm(workspace, staging, batches, id_)

        assert [(row.name, row.creation) for row in batch.rows] == [
            (name, "created") for name in NAMES
        ]
        assert sorted(_created(workspace)) == sorted(NAMES)
        listing = _listing(workspace, "night-hike-club")
        assert listing["design"] == {"default": "designs/night-hike-club.png"}
        assert listing["brief"] == ""
        assert listing["etsy"]["title"] == ""
        assert listing["etsy"]["tags"] == []
        assert listing["colors"] == ["black", "blue-jean", "ivory", "moss"]
        assert workspace.design_file("night-hike-club").read_bytes() == png(1)
        local = workspace.listing_dir("night-hike-club") / "assets/shots/size-chart.png"
        assert local.is_file()
        assert (
            workspace.load_listing("night-hike-club").media[-1] == "./assets/shots/size-chart.png"
        )
        assert not workspace.staging_dir(id_).exists()
        assert batches.load(id_) is not None

    def test_invalid_rows_are_left_out_and_do_not_block(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        id_ = _stage(workspace, staging, DESIGNS[0], ("sketch.png", png(9, mode="RGB")))

        batch = _confirm(workspace, staging, batches, id_)

        assert [row.name for row in batch.rows] == ["night-hike-club"]
        assert _created(workspace) == ["night-hike-club"]

    def test_a_name_problem_refuses_with_nothing_written(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        id_ = _stage(workspace, staging, DESIGNS[0], ("★★★.png", png(8)))

        with pytest.raises(ConfirmRefused, match="Fix 1 name to"):
            _confirm(workspace, staging, batches, id_)

        assert _created(workspace) == []
        assert batches.load(id_) is None

    def test_two_name_problems_are_counted_in_the_plural(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        id_ = _stage(workspace, staging, ("★★★.png", png(8)), ("☆☆☆.png", png(9)))

        with pytest.raises(ConfirmRefused, match="Fix 2 names to create the listings."):
            _confirm(workspace, staging, batches, id_)

    def test_a_name_claimed_between_staging_and_confirm_gets_a_fresh_suffix(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        id_ = _stage(workspace, staging, *DESIGNS)
        copy_listing(workspace.root, "cedar-trail")

        batch = _confirm(workspace, staging, batches, id_)

        assert [row.name for row in batch.rows] == ["night-hike-club", "cedar-trail-2", "lake-loop"]
        assert _listing(workspace, "cedar-trail-2")["design"] == {
            "default": "designs/cedar-trail-2.png"
        }
        assert _listing(workspace, "cedar-trail")["design"] == "designs/take-a-hike.png"


class TestDesignReuse:
    """Identical bytes already under ``designs/`` are reused, not written again
    (spec, *Content deduplication*; A39; batch plan PR 7)."""

    def test_a_design_already_in_designs_is_referenced_under_the_staged_name(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        workspace.design_file("fjord-mornings").write_bytes(png(4))
        id_ = _stage(workspace, staging, ("fjord-mornings-final.png", png(4)), DESIGNS[1])

        batch = _confirm(workspace, staging, batches, id_)

        assert [(row.name, row.design) for row in batch.rows] == [
            ("fjord-mornings-final", "fjord-mornings"),
            ("cedar-trail", "cedar-trail"),
        ]
        assert _listing(workspace, "fjord-mornings-final")["design"] == {
            "default": "designs/fjord-mornings.png"
        }
        assert not workspace.design_file("fjord-mornings-final").exists()

    def test_the_same_artwork_in_a_second_batch_makes_a_new_suffixed_listing(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        _confirm(workspace, staging, batches, _stage(workspace, staging, DESIGNS[1]))

        again = _confirm(workspace, staging, batches, _stage(workspace, staging, DESIGNS[1]))

        (row,) = again.rows
        assert (row.name, row.design, row.creation) == ("cedar-trail-2", "cedar-trail", "created")
        assert _listing(workspace, "cedar-trail-2")["design"] == {
            "default": "designs/cedar-trail.png"
        }
        assert sorted(_created(workspace)) == ["cedar-trail", "cedar-trail-2"]
        assert not workspace.design_file("cedar-trail-2").exists()

    def test_a_reusing_row_that_must_be_suffixed_at_confirm_keeps_the_design(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        workspace.design_file("fjord-mornings").write_bytes(png(4))
        id_ = _stage(workspace, staging, ("fjord-mornings-final.png", png(4)))
        copy_listing(workspace.root, "fjord-mornings-final")

        (row,) = _confirm(workspace, staging, batches, id_).rows

        assert (row.name, row.design) == ("fjord-mornings-final-2", "fjord-mornings")


class TestFailureAndRetry:
    def test_a_write_failure_on_one_row_leaves_the_others_and_retry_creates_it(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        id_ = _stage(workspace, staging, *DESIGNS)
        # A directory where the design file goes: a real filesystem refusal.
        blocker = workspace.design_file("cedar-trail")
        blocker.mkdir(parents=True)

        batch = _confirm(workspace, staging, batches, id_)

        states = {row.name: row.creation for row in batch.rows}
        assert states == {
            "night-hike-club": "created",
            "cedar-trail": "failed",
            "lake-loop": "created",
        }
        failed = batch.rows[1]
        assert failed.error is not None
        assert failed.error.startswith("Couldn't write designs/cedar-trail.png: ")
        # The input moved beside the batch, so staging could go (A46).
        assert not workspace.staging_dir(id_).exists()

        blocker.rmdir()
        batch = retry_row(workspace, staging, batches, id_, failed.id)

        assert batch.rows[1].creation == "created"
        assert workspace.design_file("cedar-trail").read_bytes() == png(2)
        assert sorted(_created(workspace)) == sorted(NAMES)

    # Sixteen durable writes for three rows: the batch record, then per row
    # the claim, the design, the owned picture, listing.yaml and "created".
    @pytest.mark.parametrize("crash_at", range(1, 17))
    def test_confirming_again_after_a_crash_at_any_write_never_duplicates_a_listing(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        monkeypatch: pytest.MonkeyPatch,
        crash_at: int,
    ) -> None:
        id_ = _stage(workspace, staging, *DESIGNS[:3])
        real_replace = os.replace
        calls = 0

        class Crash(BaseException):
            pass

        def replace(source: str, target: str) -> None:
            nonlocal calls
            calls += 1
            if calls == crash_at:
                raise Crash
            real_replace(source, target)

        monkeypatch.setattr(os, "replace", replace)
        with contextlib.suppress(Crash):
            _confirm(workspace, staging, batches, id_)
        monkeypatch.setattr(os, "replace", real_replace)

        batch = _confirm(workspace, staging, batches, id_)
        batch = retry_row(workspace, staging, batches, id_, batch.rows[0].id)

        assert [row.creation for row in batch.rows] == ["created"] * 3
        assert sorted(_created(workspace)) == sorted(NAMES)
        assert sorted(p.name for p in workspace.designs_dir().iterdir()) == sorted(
            [f"{name}.png" for name in NAMES] + ["take-a-hike.png"]
        )


class TestFrozenTemplate:
    def test_an_edit_after_staging_does_not_reach_the_listings(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        id_ = _stage(workspace, staging, DESIGNS[0])
        path = workspace.listing_template_file("heavyweight-tee")
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        document["colors"] = ["black"]
        document["media"] = [{"template": "flat-lay-01", "colour": "black"}]
        path.write_text(yaml.safe_dump(document), encoding="utf-8")

        _confirm(workspace, staging, batches, id_)

        assert _listing(workspace, "night-hike-club")["colors"] == [
            "black",
            "blue-jean",
            "ivory",
            "moss",
        ]

    def test_deleting_the_listing_template_does_not_break_confirm(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        id_ = _stage(workspace, staging, DESIGNS[0])
        workspace.remove_listing_template("heavyweight-tee")

        batch = _confirm(workspace, staging, batches, id_)

        assert batch.rows[0].creation == "created"
        local = workspace.listing_dir("night-hike-club") / "assets" / LOCAL_PICTURE[2:]
        assert local.is_file()

    def test_a_shared_ref_that_broke_since_staging_refuses_confirm(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        id_ = _stage(workspace, staging, DESIGNS[0])
        (workspace.root / "garment-profiles" / "comfort-colors-1717.yaml").unlink()

        with pytest.raises(ConfirmRefused, match="can no longer make listings"):
            _confirm(workspace, staging, batches, id_)

        assert _created(workspace) == []
