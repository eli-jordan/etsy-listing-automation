"""Staging loose PNGs (batch plan PR 2; spec *Accepted input*, *Frozen
staging*, *Staging validation and naming*; A38, A45, A46).

Through the `batches` package against a writable fixture workspace: what a
session holds after an upload, what a refusal leaves on disk (nothing), and
the names the review shows.
"""

from __future__ import annotations

import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings import batches
from etsy_listings.batches import StagingRefused, StagingStore, review, stage_pngs
from etsy_listings.workspace.workspace import Workspace

from tests.support.batches import a_listing_template, png, uploads

NOW = datetime(2026, 9, 27, 11, 42, tzinfo=UTC)


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    workspace = Workspace.discover(root_override=workspace_root)
    a_listing_template(workspace)
    return workspace


@pytest.fixture
def store(workspace: Workspace) -> StagingStore:
    return StagingStore(workspace)


def _stage(workspace: Workspace, store: StagingStore, *files: tuple[str, bytes]):  # noqa: ANN202
    return stage_pngs(workspace, store, "heavyweight-tee", uploads(*files), now=NOW)


def _staging_left(workspace: Workspace) -> list[Path]:
    directory = workspace.cache("staging")
    return sorted(directory.rglob("*")) if directory.is_dir() else []


def _rows(workspace: Workspace, store: StagingStore, session_id: str) -> dict[str, dict]:
    session = store.load(session_id)
    assert session is not None
    return {row.sources[0]: row.__dict__ for row in review(workspace, session).rows}


class TestValidation:
    def test_opaque_and_undersized_pngs_are_not_created_rows_with_the_existing_message(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        session = _stage(
            workspace,
            store,
            ("Night Hike Club.png", png(1)),
            ("sketch-draft.png", png(2, mode="RGB")),
            ("tiny-logo.png", png(3, size=(40, 50))),
        )

        rows = _rows(workspace, store, session.id)
        assert rows["Night Hike Club.png"]["state"] == "ready"
        assert rows["sketch-draft.png"]["state"] == "invalid"
        assert rows["sketch-draft.png"]["message"].startswith(
            "sketch-draft.png has no alpha channel (mode 'RGB')."
        )
        assert rows["tiny-logo.png"]["state"] == "invalid"
        assert rows["tiny-logo.png"]["message"].startswith(
            "tiny-logo.png is 40x50, too small for this garment's 100x120 print area."
        )

    def test_a_file_that_is_not_a_png_refuses_the_upload(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        with pytest.raises(StagingRefused, match=r"readme\.txt is not a PNG"):
            _stage(workspace, store, ("a.png", png(1)), ("readme.txt", b"hello"))

        assert _staging_left(workspace) == []

    def test_a_zip_is_refused_until_zip_input_exists(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        with pytest.raises(StagingRefused, match="ZIP"):
            _stage(workspace, store, ("kittl-export.zip", b"PK\x03\x04rest"))

        assert _staging_left(workspace) == []


class TestLimits:
    def test_26_unique_pngs_are_refused_with_nothing_on_disk(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        files = [(f"design-{n}.png", png(n)) for n in range(26)]

        with pytest.raises(StagingRefused) as refused:
            _stage(workspace, store, *files)

        assert "26 different PNG designs" in str(refused.value)
        assert _staging_left(workspace) == []

    def test_26_files_that_collapse_to_25_are_accepted_as_one_merged_row(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        files = [(f"design-{n}.png", png(n)) for n in range(25)]
        files.append(("exports/design-0 copy.png", png(0)))

        session = _stage(workspace, store, *files)

        assert len(session.rows) == 25
        merged = review(workspace, session).rows[0]
        assert merged.sources == ["design-0.png", "exports/design-0 copy.png"]
        assert (
            merged.note == "2 identical files, staged once: design-0.png, exports/design-0 copy.png"
        )

    def test_a_png_over_the_per_file_limit_is_refused_with_nothing_on_disk(
        self, workspace: Workspace, store: StagingStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(batches.staging, "MAX_PNG_BYTES", 100)

        with pytest.raises(StagingRefused, match=r"big\.png is larger than"):
            _stage(workspace, store, ("big.png", png(1)))

        assert _staging_left(workspace) == []

    def test_an_upload_over_the_total_limit_is_refused_with_nothing_on_disk(
        self, workspace: Workspace, store: StagingStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(batches.staging, "MAX_UPLOAD_BYTES", len(png(1)) + 10)

        with pytest.raises(StagingRefused, match="together"):
            _stage(workspace, store, ("a.png", png(1)), ("b.png", png(2)))

        assert _staging_left(workspace) == []


class TestNames:
    def test_a_generated_name_that_is_taken_gets_the_next_suffix_and_says_so(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        session = _stage(workspace, store, ("Take a Hike.png", png(1)), ("take_a_hike.png", png(2)))

        rows = _rows(workspace, store, session.id)
        assert rows["Take a Hike.png"]["name"] == "take-a-hike-2"
        assert rows["Take a Hike.png"]["note"] == "take-a-hike is taken, so -2 was added"
        assert rows["take_a_hike.png"]["name"] == "take-a-hike-3"
        assert rows["take_a_hike.png"]["state"] == "ready"

    def test_a_name_with_no_letters_or_digits_must_be_typed(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        session = _stage(workspace, store, ("★★★.png", png(1)))

        row = _rows(workspace, store, session.id)["★★★.png"]
        assert row["state"] == "name"
        assert row["name"] == ""
        assert (
            row["message"]
            == "The file name has no letters or digits. Type a name for this listing."
        )

    def test_a_typed_name_that_is_taken_is_flagged_with_a_suggestion_not_changed(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        session = _stage(workspace, store, ("moss and miles.png", png(1)))
        row_id = session.rows[0].id

        store.save(session.renamed(row_id, "take-a-hike", now=NOW))

        row = _rows(workspace, store, session.id)["moss and miles.png"]
        assert row["name"] == "take-a-hike"
        assert row["state"] == "name"
        assert row["message"] == "take-a-hike is already a listing."
        assert row["suggestion"] == "take-a-hike-2"

    def test_a_typed_name_the_generated_names_avoid(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        session = _stage(workspace, store, ("lake-loop.png", png(1)), ("other.png", png(2)))
        typed = session.renamed(session.rows[1].id, "lake-loop", now=NOW)
        store.save(typed)

        rows = _rows(workspace, store, session.id)
        assert rows["other.png"]["name"] == "lake-loop"
        assert rows["other.png"]["state"] == "ready"
        assert rows["lake-loop.png"]["name"] == "lake-loop-2"


class TestFrozenTemplate:
    def test_staging_records_when_the_listing_template_was_saved(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        session = _stage(workspace, store, ("a.png", png(1)))

        saved = workspace.listing_template_file("heavyweight-tee").stat().st_mtime
        assert session.template_saved_at == datetime.fromtimestamp(saved, tz=UTC)
        assert re.fullmatch(r"heavyweight-tee · \d{1,2} Sep \d\d:\d\d", session.label)

    @pytest.mark.skipif(sys.platform == "win32", reason="time.tzset is POSIX-only")
    def test_the_default_label_is_in_local_time(
        self, workspace: Workspace, store: StagingStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TZ", "Europe/Oslo")
        time.tzset()
        try:
            session = _stage(workspace, store, ("a.png", png(1)))
        finally:
            monkeypatch.undo()
            time.tzset()

        assert session.label == "heavyweight-tee · 27 Sep 13:42"


class TestLifetime:
    def test_the_sweep_removes_a_session_seven_days_after_its_last_edit(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        session = _stage(workspace, store, ("a.png", png(1)))
        store.save(session.relabelled("Autumn", now=NOW + timedelta(days=2)))

        store.sweep(now=NOW + timedelta(days=8))
        assert store.load(session.id) is not None

        store.sweep(now=NOW + timedelta(days=9, seconds=1))
        assert store.load(session.id) is None
        assert _staging_left(workspace) == []

    def test_a_record_with_an_unknown_schema_is_absent(
        self, workspace: Workspace, store: StagingStore
    ) -> None:
        session = _stage(workspace, store, ("a.png", png(1)))
        file = workspace.staging_session_file(session.id)
        file.write_text(file.read_text().replace('"schema": 1', '"schema": 99'))

        assert store.load(session.id) is None
