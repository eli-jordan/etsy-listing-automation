"""Staging, confirming, retrying and reviewing a batch, called directly -- no
``TestClient`` (module-structure plan, PR 7; batch-creation spec; ADR-0048,
ADR-0051).

The upload validation, archive safety, name allocation and idempotent row
creation these operations coordinate are ``batches``' and tested beside it
(``test_batch_staging``, ``test_batch_archive``, ``test_batch_creation``);
here, that the operations around them refuse, lock, wake and steer the queue
as the batch pages expect. The queue is core's own, never started: what a
started one then dispatches is ``test_batch_queue``'s, so these read the rows
it would dispatch and whether it has a wake to answer. Whether AI could run
is the queue's answer from its providers, prompts and market access. What
each outcome becomes on the wire is the batches API tests' business.
"""

from __future__ import annotations

import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
import yaml

from etsy_listings.core.ai.listing_inputs import ListingAiInputs
from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application.ai.batch_queue import BatchQueue
from etsy_listings.core.application.ai.coordinator import AiCoordinator
from etsy_listings.core.application.batch_staging import (
    cancel_staging,
    edit_staging,
    read_staging,
    stage_upload,
    staged_upload,
)
from etsy_listings.core.application.batch_workflow import (
    batch_row_upload,
    cancel_batch,
    confirm_batch,
    delete_batch,
    listing_batch,
    mark_reviewed,
    read_batch,
    recent_batches,
    rename_batch,
    resume_batch,
    retry_batch,
    retry_batch_row,
    row_proposal,
)
from etsy_listings.core.application.refusals import (
    AiDraftingBlocked,
    BatchMissing,
    BatchRowMissing,
    BatchRowNotReviewable,
    BatchRowUploadMissing,
    ListingTemplateMissing,
    NothingToRetry,
    StagedRowMissing,
    StagingMissing,
)
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.batches import (
    Batch,
    BatchStore,
    ConfirmRefused,
    StagingRefused,
    StagingSession,
    StagingStore,
    Upload,
)
from etsy_listings.core.batches import staging as staging_module
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.workspace import InvalidNameError, Workspace

from tests.support.ai_runs import (
    ChainProvider,
    seed_prompts,
    seed_proposal,
    seeded_market,
    wait_for,
)
from tests.support.batches import (
    LISTING_TEMPLATE,
    a_listing_template,
    png,
    uploads,
)

NOW = datetime(2026, 9, 27, 11, 42, tzinfo=UTC)


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    seed_prompts(workspace_root)
    workspace = Workspace.discover(root_override=workspace_root)
    a_listing_template(workspace)
    return workspace


def _queue(workspace: Workspace, batches: BatchStore) -> BatchQueue:
    """A batch queue that could draft -- prompts, a ready provider and
    market access -- and is never started."""
    market = seeded_market()
    return AiCoordinator(
        workspace,
        locks=WorkspaceLocks(),
        proposals=ProposalStore(workspace),
        batches=batches,
        providers=lambda _workspace: [ChainProvider()],
        market_client=lambda _workspace: market,
    ).queue


def _woken(queue: BatchQueue) -> bool:
    """The queue has been asked to look again since it last answered."""
    return not queue.wait_idle(timeout=0)


def _ai(batches: BatchStore, batch: Batch) -> list[str | None]:
    loaded = batches.load(batch.id)
    assert loaded is not None
    return [row.ai for row in loaded.rows]


@pytest.fixture
def staging(workspace: Workspace) -> StagingStore:
    return StagingStore(workspace)


@pytest.fixture
def batches(workspace: Workspace) -> BatchStore:
    return BatchStore(workspace)


@pytest.fixture
def locks() -> WorkspaceLocks:
    return WorkspaceLocks()


@pytest.fixture
def queue(workspace: Workspace, batches: BatchStore) -> BatchQueue:
    """The queue under test, unwoken until the operation under test."""
    return _queue(workspace, batches)


def _stage(
    workspace: Workspace, staging: StagingStore, *files: tuple[str, bytes]
) -> StagingSession:
    return stage_upload(
        workspace, staging, LISTING_TEMPLATE, uploads(*files), locks=WorkspaceLocks()
    )


def _confirm(
    workspace: Workspace,
    staging: StagingStore,
    batches: BatchStore,
    session_id: str,
    queue: BatchQueue | None = None,
) -> Batch:
    """Confirm through ``queue``, or through a queue of its own when the
    test is about what happens next."""
    return confirm_batch(
        workspace,
        staging,
        batches,
        session_id,
        locks=WorkspaceLocks(),
        queue=queue or _queue(workspace, batches),
    )


def _failed_batch(workspace: Workspace, staging: StagingStore, batches: BatchStore) -> Batch:
    """One row whose creation failed: its design path was a directory."""
    session = _stage(workspace, staging, ("a.png", png(1)))
    blocker = workspace.design_file("a")
    blocker.mkdir(parents=True)
    batch = _confirm(workspace, staging, batches, session.id)
    blocker.rmdir()
    assert batch.rows[0].creation == "failed"
    return batch


# ------------------------------------------------------------------ staging


class TestStage:
    def test_an_upload_is_staged_against_a_listing_template(
        self, workspace: Workspace, staging: StagingStore
    ) -> None:
        session = _stage(workspace, staging, ("Night Hike Club.png", png(1)))
        assert session.listing_template == LISTING_TEMPLATE
        assert read_staging(workspace, staging, session.id) == session

    def test_an_unknown_listing_template_is_refused_with_nothing_on_disk(
        self, workspace: Workspace, staging: StagingStore
    ) -> None:
        with pytest.raises(ListingTemplateMissing):
            stage_upload(
                workspace, staging, "nope", uploads(("a.png", png(1))), locks=WorkspaceLocks()
            )
        assert workspace.staging_ids() == []

    def test_the_design_and_size_limits_still_refuse_with_nothing_on_disk(
        self, workspace: Workspace, staging: StagingStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR-0051: the limits are batch creation's, unchanged by the move."""
        with pytest.raises(StagingRefused, match="26 different PNG designs"):
            _stage(workspace, staging, *[(f"d{n}.png", png(n)) for n in range(26)])
        monkeypatch.setattr(staging_module, "MAX_UPLOAD_BYTES", 100)
        with pytest.raises(StagingRefused, match="larger than"):
            _stage(workspace, staging, ("a.png", png(1)), ("b.png", png(2)))
        assert workspace.staging_ids() == []

    def test_an_archive_that_leaves_itself_is_refused_with_nothing_on_disk(
        self, workspace: Workspace, staging: StagingStore
    ) -> None:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../escape.png", png(1))
        with pytest.raises(StagingRefused):
            _stage(workspace, staging, ("export.zip", buffer.getvalue()))
        with pytest.raises(StagingRefused, match="2 ZIPs"):
            _stage(workspace, staging, ("a.zip", b"PK\x03\x04"), ("b.zip", b"PK\x03\x04"))
        assert workspace.staging_ids() == []

    def test_the_template_is_frozen_under_its_write_lock(
        self, workspace: Workspace, staging: StagingStore, locks: WorkspaceLocks
    ) -> None:
        """Capture waits for an edit holding the template's lock, so a batch
        never freezes a half-written template, and freezes what it wrote."""
        path = workspace.listing_template_file(LISTING_TEMPLATE)
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        staged: list[StagingSession] = []
        with locks.listing_template(LISTING_TEMPLATE):
            worker = threading.Thread(
                target=lambda: staged.append(
                    stage_upload(
                        workspace,
                        staging,
                        LISTING_TEMPLATE,
                        uploads(("a.png", png(1))),
                        locks=locks,
                    )
                )
            )
            worker.start()
            time.sleep(0.3)
            assert staged == []
            document["colors"] = ["black"]
            document["media"] = [
                ref for ref in document["media"] if isinstance(ref, str) or ref["colour"] == "black"
            ]
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
        worker.join(timeout=10)

        assert staged[0].template["colors"] == ["black"]


class TestEditAndCancel:
    def test_relabel_rename_and_remove_in_one_edit_move_the_expiry(
        self, workspace: Workspace, staging: StagingStore
    ) -> None:
        session = _stage(workspace, staging, ("a.png", png(1)), ("b.png", png(2)))
        first, second = (row.id for row in session.rows)
        later = session.expires_at + timedelta(days=1)

        edited = edit_staging(
            workspace,
            staging,
            session.id,
            label="  Autumn drop ",
            names={first: "take-a-hike"},
            remove=[second],
            now=later - timedelta(days=7),
        )

        assert edited.label == "Autumn drop"
        assert [(row.id, row.base, row.typed) for row in edited.rows] == [
            (first, "take-a-hike", True)
        ]
        assert edited.expires_at == later
        assert read_staging(workspace, staging, session.id) == edited

    def test_a_blank_label_keeps_the_one_it_had(
        self, workspace: Workspace, staging: StagingStore
    ) -> None:
        session = _stage(workspace, staging, ("a.png", png(1)))
        edited = edit_staging(workspace, staging, session.id, label="   ", names={}, remove=[])
        assert edited.label == session.label

    def test_an_unknown_row_refuses_the_whole_edit(
        self, workspace: Workspace, staging: StagingStore
    ) -> None:
        session = _stage(workspace, staging, ("a.png", png(1)))
        with pytest.raises(StagedRowMissing, match="no staged row 'nope'"):
            edit_staging(workspace, staging, session.id, label="New", names={}, remove=["nope"])
        assert read_staging(workspace, staging, session.id).label == session.label

    def test_cancel_removes_the_session_and_its_uploads(
        self, workspace: Workspace, staging: StagingStore
    ) -> None:
        session = _stage(workspace, staging, ("a.png", png(1)))
        cancel_staging(workspace, staging, session.id)
        assert workspace.staging_ids() == []
        with pytest.raises(StagingMissing):
            cancel_staging(workspace, staging, session.id)

    def test_an_unknown_or_unusable_session_id_is_refused(
        self, workspace: Workspace, staging: StagingStore
    ) -> None:
        with pytest.raises(StagingMissing, match="no staging session '0123abcd'"):
            read_staging(workspace, staging, "0123abcd")
        with pytest.raises(InvalidNameError):
            read_staging(workspace, staging, "a:b")

    def test_a_staged_row_s_upload(self, workspace: Workspace, staging: StagingStore) -> None:
        session = _stage(workspace, staging, ("a.png", png(1)))
        assert staged_upload(
            workspace, staging, session.id, session.rows[0].id
        ).read_bytes() == png(1)
        with pytest.raises(StagedRowMissing):
            staged_upload(workspace, staging, session.id, "nope")


# --------------------------------------------------------------- confirming


class TestConfirm:
    def test_confirming_creates_the_listings_and_wakes_the_queue(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
    ) -> None:
        session = _stage(
            workspace, staging, ("Night Hike Club.png", png(1)), ("lake_loop.png", png(2))
        )

        batch = _confirm(workspace, staging, batches, session.id, queue)

        assert [(r.name, r.creation, r.ai) for r in batch.rows] == [
            ("night-hike-club", "created", "queued"),
            ("lake-loop", "created", "queued"),
        ]
        assert _woken(queue)
        assert queue.order() == [(batch.id, row.id) for row in batch.rows]
        assert read_batch(workspace, batches, session.id) == batch

    def test_a_blocked_ai_refuses_a_new_batch_and_writes_nothing(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
    ) -> None:
        session = _stage(workspace, staging, ("a.png", png(1)))
        workspace.brief_prompt_file().unlink()

        with pytest.raises(AiDraftingBlocked) as refused:
            _confirm(workspace, staging, batches, session.id, queue)

        assert str(refused.value) == "AI drafting can't run yet. prompts/brief.md is missing."
        assert isinstance(refused.value, ConfirmRefused)
        assert workspace.batch_ids() == [] and workspace.listing_names() == ["take-a-hike"]
        assert read_staging(workspace, staging, session.id) == session
        assert not _woken(queue)

    def test_a_confirm_finishing_a_batch_is_not_asked_about_ai_again(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
    ) -> None:
        """Its listings are half made; a repeat (double click, a dropped
        response) finishes the same batch rather than making a second."""
        session = _stage(workspace, staging, ("a.png", png(1)))
        first = _confirm(workspace, staging, batches, session.id)
        workspace.brief_prompt_file().unlink()

        again = _confirm(workspace, staging, batches, session.id, queue)

        assert again.rows == first.rows
        assert workspace.listing_names() == ["a", "take-a-hike"]

    def test_two_confirms_at_once_make_one_batch_and_each_listing_once(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore, queue: BatchQueue
    ) -> None:
        session = _stage(workspace, staging, ("a.png", png(1)), ("b.png", png(2)))
        locks = WorkspaceLocks()

        def confirm() -> Batch:
            return confirm_batch(workspace, staging, batches, session.id, locks=locks, queue=queue)

        with ThreadPoolExecutor(max_workers=2) as pool:
            one, two = (f.result() for f in [pool.submit(confirm), pool.submit(confirm)])

        assert workspace.batch_ids() == [session.id]
        assert [r.name for r in one.rows] == [r.name for r in two.rows] == ["a", "b"]
        assert workspace.listing_names() == ["a", "b", "take-a-hike"]

    def test_a_name_to_fix_refuses_with_nothing_created(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
    ) -> None:
        session = _stage(workspace, staging, ("★★★.png", png(1)))
        with pytest.raises(ConfirmRefused, match="Fix 1 name to create the listings."):
            _confirm(workspace, staging, batches, session.id, queue)
        assert workspace.listing_names() == ["take-a-hike"] and not _woken(queue)

    def test_an_unknown_session_is_refused(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
    ) -> None:
        with pytest.raises(StagingMissing):
            _confirm(workspace, staging, batches, "0123abcd", queue)


# ----------------------------------------------------------------- retrying


class TestRetry:
    def test_a_failed_creation_is_created_and_the_queue_woken(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
        locks: WorkspaceLocks,
    ) -> None:
        batch = _failed_batch(workspace, staging, batches)

        retried = retry_batch_row(
            workspace, staging, batches, batch.id, batch.rows[0].id, locks=locks, queue=queue
        )

        assert (retried.rows[0].creation, retried.rows[0].ai) == ("created", "queued")
        assert _woken(queue)

    @pytest.mark.parametrize("ai", ["failed", "stopped", "cancelled", "cancelled_by_deploy"])
    def test_a_created_row_s_ai_is_requeued(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
        locks: WorkspaceLocks,
        ai: str,
    ) -> None:
        session = _stage(workspace, staging, ("a.png", png(1)))
        batch = _confirm(workspace, staging, batches, session.id)
        row = batch.rows[0]
        batch.rows[0] = row.model_copy(update={"ai": ai, "ai_error": "it broke"})
        batches.save(batch)

        retried = retry_batch_row(
            workspace, staging, batches, batch.id, row.id, locks=locks, queue=queue
        )

        assert (retried.rows[0].ai, retried.rows[0].ai_error) == ("queued", None)
        assert _woken(queue)

    @pytest.mark.parametrize(
        ("ai", "deleted"), [("queued", False), ("done", False), ("failed", True)]
    )
    def test_a_row_with_nothing_to_retry_is_refused(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
        locks: WorkspaceLocks,
        ai: str,
        deleted: bool,
    ) -> None:
        session = _stage(workspace, staging, ("a.png", png(1)))
        batch = _confirm(workspace, staging, batches, session.id)
        batch.rows[0] = batch.rows[0].model_copy(update={"ai": ai, "deleted": deleted})
        batches.save(batch)

        with pytest.raises(NothingToRetry, match="a has nothing to retry"):
            retry_batch_row(
                workspace, staging, batches, batch.id, batch.rows[0].id, locks=locks, queue=queue
            )
        assert _ai(batches, batch) == [ai] and not _woken(queue)

    def test_unknown_batches_and_rows_are_refused(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
        locks: WorkspaceLocks,
    ) -> None:
        batch = _failed_batch(workspace, staging, batches)
        with pytest.raises(BatchRowMissing, match="no batch row 'nope'"):
            retry_batch_row(workspace, staging, batches, batch.id, "nope", locks=locks, queue=queue)
        with pytest.raises(BatchMissing, match="no batch '0123abcd'"):
            retry_batch(workspace, staging, batches, "0123abcd", locks=locks, queue=queue)

    def test_retry_all_creates_failed_rows_then_requeues_failed_ai(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
        locks: WorkspaceLocks,
    ) -> None:
        session = _stage(workspace, staging, ("a.png", png(1)), ("b.png", png(2)))
        workspace.design_file("a").mkdir(parents=True)
        batch = _confirm(workspace, staging, batches, session.id)
        workspace.design_file("a").rmdir()
        batch.rows[1] = batch.rows[1].model_copy(update={"ai": "failed"})
        batches.save(batch)

        retried = retry_batch(workspace, staging, batches, batch.id, locks=locks, queue=queue)

        assert [(r.creation, r.ai) for r in retried.rows] == [
            ("created", "queued"),
            ("created", "queued"),
        ]
        assert _woken(queue)


# ------------------------------------------------- steering and the record


class TestSteerAndKeep:
    def test_cancel_stops_the_queued_rows_and_resume_queues_them_again(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
    ) -> None:
        batch = _confirm(
            workspace, staging, batches, _stage(workspace, staging, ("a.png", png(1))).id
        )

        cancelled = cancel_batch(workspace, batches, batch.id, queue=queue)
        assert [row.ai for row in cancelled.rows] == ["stopped"]
        resumed = resume_batch(workspace, batches, batch.id, queue=queue)

        assert [row.ai for row in resumed.rows] == ["queued"]
        assert _woken(queue)
        with pytest.raises(BatchMissing):
            cancel_batch(workspace, batches, "0123abcd", queue=queue)

    def test_delete_cancels_its_work_then_removes_only_the_record(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
    ) -> None:
        batch = _confirm(
            workspace, staging, batches, _stage(workspace, staging, ("a.png", png(1))).id
        )

        delete_batch(workspace, batches, batch.id, queue=queue)

        assert workspace.batch_ids() == [] and queue.order() == []
        assert _woken(queue)
        assert workspace.listing_file("a").is_file() and workspace.design_file("a").is_file()
        with pytest.raises(BatchMissing):
            delete_batch(workspace, batches, batch.id, queue=queue)

    def test_delete_stops_a_row_still_drafting(
        self, workspace: Workspace, staging: StagingStore, batches: BatchStore
    ) -> None:
        """The record goes, but the work it started must not carry on: a
        running row's run is asked to stop, which kills its provider call."""
        provider = ChainProvider()
        provider.gate("brief")
        market = seeded_market()
        ai = AiCoordinator(
            workspace,
            locks=WorkspaceLocks(),
            proposals=ProposalStore(workspace),
            batches=batches,
            providers=lambda _workspace: [provider],
            market_client=lambda _workspace: market,
        )
        ai.start()
        try:
            batch = _confirm(
                workspace,
                staging,
                batches,
                _stage(workspace, staging, ("a.png", png(1))).id,
                ai.queue,
            )
            wait_for(lambda: provider.started["brief"].is_set())
            run = ai.registry.latest("a")
            assert run is not None

            delete_batch(workspace, batches, batch.id, queue=ai.queue)

            wait_for(lambda: run.finished)
            assert (run.stop_reason, run.phase) == ("cancelled", "cancelled")
            assert provider.cancelled == ["brief"]
            assert workspace.batch_ids() == []
        finally:
            ai.stop()

    def test_rename_changes_the_label_only_and_a_blank_keeps_it(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
    ) -> None:
        batch = _confirm(
            workspace, staging, batches, _stage(workspace, staging, ("a.png", png(1))).id
        )

        renamed = rename_batch(workspace, batches, batch.id, " Autumn drop ")
        blank = rename_batch(workspace, batches, batch.id, "  ")

        assert (renamed.id, renamed.label) == (batch.id, "Autumn drop")
        assert blank.label == "Autumn drop"
        with pytest.raises(BatchMissing):
            rename_batch(workspace, batches, "0123abcd", "x")

    def test_mark_reviewed_only_where_there_is_a_listing_to_review(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
    ) -> None:
        batch = _confirm(
            workspace, staging, batches, _stage(workspace, staging, ("a.png", png(1))).id
        )
        row = batch.rows[0].id

        with pytest.raises(BatchRowNotReviewable, match="a has no listing to review yet"):
            mark_reviewed(workspace, batches, batch.id, row, reviewed=True)
        batch.rows[0] = batch.rows[0].model_copy(update={"ai": "stopped"})
        batches.save(batch)

        marked = mark_reviewed(workspace, batches, batch.id, row, reviewed=True)

        assert marked.rows[0].reviewed
        with pytest.raises(BatchRowMissing):
            mark_reviewed(workspace, batches, batch.id, "nope", reviewed=True)

    def test_a_never_created_row_shows_its_kept_upload(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
    ) -> None:
        batch = _failed_batch(workspace, staging, batches)
        row = batch.rows[0]
        assert workspace.staging_ids() == []

        assert batch_row_upload(workspace, batches, batch.id, row.id).read_bytes() == png(1)
        workspace.batch_upload_file(batch.id, row.sha256).unlink()
        with pytest.raises(BatchRowUploadMissing):
            batch_row_upload(workspace, batches, batch.id, row.id)
        with pytest.raises(BatchRowMissing):
            batch_row_upload(workspace, batches, batch.id, "nope")


# -------------------------------------------------------------------- reads


class TestReads:
    def test_recent_batches_lists_batches_and_unconfirmed_sessions_newest_first(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
    ) -> None:
        confirmed = _confirm(
            workspace, staging, batches, _stage(workspace, staging, ("a.png", png(1))).id, queue
        )
        waiting = _stage(workspace, staging, ("c.png", png(3)))
        stale = stage_upload(
            workspace,
            staging,
            LISTING_TEMPLATE,
            [Upload("d.png", BytesIO(png(4)))],
            locks=WorkspaceLocks(),
            now=datetime.now(UTC) - timedelta(days=8),
        )

        recent = recent_batches(workspace, staging, batches, now=datetime.now(UTC))

        assert [(entry.kind, entry.id) for entry in recent] == [
            ("staging", waiting.id),
            ("batch", confirmed.id),
        ]
        assert recent[0].standing is None and recent[0].expires_at == waiting.expires_at
        assert recent[1].standing is not None and recent[1].standing.listings == 1
        assert stale.id not in workspace.staging_ids()

    def test_a_session_kept_for_a_failed_row_is_listed_once_as_its_batch(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
    ) -> None:
        session = _stage(workspace, staging, ("a.png", png(1)), ("b.png", png(2)))
        workspace.design_file("a").mkdir(parents=True)
        _confirm(workspace, staging, batches, session.id, queue)
        staging.save(session)  # as if the failed row's upload could not be moved

        recent = recent_batches(workspace, staging, batches, now=datetime.now(UTC))

        assert [(entry.kind, entry.id) for entry in recent] == [("batch", session.id)]

    def test_a_listing_s_batch_is_the_newest_live_row_naming_it(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
    ) -> None:
        batch = _confirm(
            workspace, staging, batches, _stage(workspace, staging, ("a.png", png(1))).id, queue
        )

        found = listing_batch(workspace, batches, "a")

        assert found is not None
        assert (found.batch.id, found.row.id) == (batch.id, batch.rows[0].id)
        assert listing_batch(workspace, batches, "take-a-hike") is None
        batches.mark_deleted("a")
        assert listing_batch(workspace, batches, "a") is None
        with pytest.raises(InvalidNameError):
            listing_batch(workspace, batches, "a:b")

    def test_a_row_s_proposal_is_judged_as_the_editor_judges_it(
        self,
        workspace: Workspace,
        staging: StagingStore,
        batches: BatchStore,
        queue: BatchQueue,
    ) -> None:
        batch = _confirm(
            workspace, staging, batches, _stage(workspace, staging, ("a.png", png(1))).id, queue
        )
        proposals = ProposalStore(workspace)
        facts = WorkspaceFacts.gather(workspace)
        row = batch.rows[0]

        assert row_proposal(workspace, proposals, row, facts=facts) == (None, [])

        record = seed_proposal(workspace.root, "a")
        judged = ListingAiInputs.read(workspace, "a", facts=facts).judge(record)
        state, reasons = row_proposal(workspace, proposals, row, facts=facts)

        assert state == ("stale" if judged.stale.is_stale else "ready")
        assert reasons == (judged.stale.reasons if judged.stale.is_stale else [])
        deleted = row.model_copy(update={"deleted": True})
        assert row_proposal(workspace, proposals, deleted, facts=facts) == (None, [])
