"""Saving, reading, renaming and deleting listing templates, called directly
-- no ``TestClient`` (module-structure plan, PR 7; ADR-0047, template
completeness).

Each write takes the template's write lock and re-checks it is still there
once held, so a create and a rename to one name cannot both win and an edit
queued behind a rename cannot recreate the old name. A refused save writes
nothing. What each outcome becomes on the wire (404, 409, 422, a 200 with
``saved: false``) is the listing-templates API tests' business; the
conversion rules themselves are ``listing_templates``' and unit-tested there.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from PIL import Image

from etsy_listings.core.application.listing_template_library import (
    TemplateSave,
    create_listing_template,
    delete_listing_template,
    draft_listing_template,
    edit_listing_template,
    list_listing_templates,
    read_listing_template,
    rename_listing_template,
)
from etsy_listings.core.application.refusals import (
    ListingMissing,
    ListingTemplateMissing,
    ListingTemplateSourceRefused,
    ReservedListingTemplateName,
)
from etsy_listings.core.batches import Batch, BatchStore, StagingStore, stage_pngs
from etsy_listings.core.listing_templates import ListingTemplateExistsError
from etsy_listings.core.workspace.workspace import InvalidNameError, Workspace
from etsy_listings.server.workspace_locks import WorkspaceLocks

from tests.support.batches import png, small_print_area, uploads
from tests.support.builders import FIXTURE_LISTING, edit_listing

NAME = "heavyweight-tee"
BLACK = {"template": "flat-lay-01", "colour": "black"}


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def locks() -> WorkspaceLocks:
    return WorkspaceLocks()


def _create(
    workspace: Workspace,
    name: str = NAME,
    *,
    locks: WorkspaceLocks | None = None,
    document: dict[str, Any] | None = None,
    **source: str,
) -> TemplateSave:
    return create_listing_template(
        workspace,
        name,
        from_listing=source.get("from_listing", None if source else FIXTURE_LISTING),
        from_template=source.get("from_template"),
        document=document,
        locks=locks or WorkspaceLocks(),
    )


def _local_picture(workspace: Workspace, ref: str = "./shots/back.png") -> None:
    path = workspace.listing_dir(FIXTURE_LISTING) / ref.removeprefix("./")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 300), (200, 180, 150)).save(path)
    edit_listing(workspace.root, media=[BLACK, ref])


def _document(workspace: Workspace, name: str = NAME) -> dict[str, Any]:
    return workspace.load_listing_template(name).model_dump(mode="json")


class TestCreate:
    def test_saving_a_listing_writes_the_template_and_answers_it(
        self, workspace: Workspace
    ) -> None:
        outcome = _create(workspace)

        assert outcome.saved and outcome.template is not None
        assert outcome.template.name == NAME
        assert outcome.template.template.colors == ["black", "blue-jean", "ivory", "moss"]
        assert outcome.template.modified_at is not None
        assert workspace.listing_template_names() == [NAME]

    def test_a_taken_name_is_refused_never_suffixed_and_nothing_is_written(
        self, workspace: Workspace
    ) -> None:
        _create(workspace)
        before = workspace.listing_template_file(NAME).read_bytes()
        edit_listing(workspace.root, colors=["black"], media=[BLACK])

        with pytest.raises(ListingTemplateExistsError, match=NAME):
            _create(workspace)
        assert workspace.listing_template_file(NAME).read_bytes() == before
        assert workspace.listing_template_names() == [NAME]

    def test_an_incomplete_listing_answers_its_issues_and_writes_nothing(
        self, workspace: Workspace
    ) -> None:
        edit_listing(workspace.root, colors=[], media=["common-media/size-guide.png"])

        outcome = _create(workspace)

        assert not outcome.saved and outcome.template is None
        assert (outcome.issues[0].severity, outcome.issues[0].where) == (
            "block",
            "Variants › Colours",
        )
        assert not workspace.listing_template_dir(NAME).exists()

    def test_an_unreadable_local_file_refuses_naming_the_ref(self, workspace: Workspace) -> None:
        edit_listing(workspace.root, media=[BLACK, "./shots/gone.png"])

        with pytest.raises(ListingTemplateSourceRefused, match=r"\./shots/gone\.png"):
            _create(workspace)
        assert not workspace.listing_templates_dir().exists()

    def test_a_source_must_exist(self, workspace: Workspace) -> None:
        with pytest.raises(ListingMissing):
            _create(workspace, from_listing="no-such-listing")
        with pytest.raises(ListingTemplateMissing, match="no listing template 'no-such'"):
            _create(workspace, from_template="no-such")

    def test_exactly_one_source(self, workspace: Workspace) -> None:
        with pytest.raises(ListingTemplateSourceRefused, match="exactly one"):
            _create(workspace, from_listing=FIXTURE_LISTING, from_template=NAME)
        with pytest.raises(ListingTemplateSourceRefused, match="exactly one"):
            create_listing_template(
                workspace, NAME, from_listing=None, from_template=None, locks=WorkspaceLocks()
            )

    def test_an_unusable_or_reserved_name_is_refused_before_any_source_is_read(
        self, workspace: Workspace
    ) -> None:
        with pytest.raises(InvalidNameError):
            _create(workspace, "../escape", from_listing="no-such-listing")
        with pytest.raises(ReservedListingTemplateName, match="'draft' is reserved"):
            _create(workspace, "draft", from_listing="no-such-listing")
        assert not workspace.listing_templates_dir().exists()

    def test_edits_made_before_naming_are_what_is_written(self, workspace: Workspace) -> None:
        """A file the edit dropped is not copied."""
        _local_picture(workspace)
        draft = draft_listing_template(workspace, from_listing=FIXTURE_LISTING, from_template=None)
        document = {**draft.template.model_dump(mode="json"), "colors": ["black"], "media": [BLACK]}

        assert _create(workspace, document=document).saved
        assert workspace.load_listing_template(NAME).colors == ["black"]
        assert not workspace.listing_template_assets_dir(NAME).exists()

    def test_an_edited_document_is_checked_like_an_edit(self, workspace: Workspace) -> None:
        draft = draft_listing_template(workspace, from_listing=FIXTURE_LISTING, from_template=None)
        document = draft.template.model_dump(mode="json")

        incomplete = _create(
            workspace, document={**document, "colors": [], "media": ["common-media/size-guide.png"]}
        )
        malformed = _create(workspace, document={**document, "brief": "no"})
        with pytest.raises(ListingTemplateSourceRefused, match=r"\./assets/elsewhere\.png"):
            _create(workspace, document={**document, "media": [BLACK, "./assets/elsewhere.png"]})

        assert not incomplete.saved
        assert not malformed.saved and "brief" in malformed.field_errors
        assert not workspace.listing_templates_dir().exists()

    def test_a_clone_is_created_from_another_template(self, workspace: Workspace) -> None:
        _create(workspace)
        assert _create(workspace, "everyday-tee", from_template=NAME).saved
        assert workspace.listing_template_names() == ["everyday-tee", NAME]


class TestDraftAndRead:
    def test_the_draft_is_the_template_as_it_would_be_saved_and_writes_nothing(
        self, workspace: Workspace
    ) -> None:
        _local_picture(workspace)
        edit_listing(
            workspace.root,
            etsy={"title": "Take A Hike", "description": {"lead": "Retro.", "text": "Cotton."}},
        )

        draft = draft_listing_template(workspace, from_listing=FIXTURE_LISTING, from_template=None)

        assert draft.name == "" and draft.modified_at is None
        assert draft.source is not None
        assert (draft.source.kind, draft.source.name) == ("listing", FIXTURE_LISTING)
        assert draft.template.media[1] == "./assets/shots/back.png"
        assert [(a.ref, a.source_ref) for a in draft.assets] == [
            ("./assets/shots/back.png", "./shots/back.png")
        ]
        assert draft.garment == "Comfort Colors 1717"
        assert draft.description_composed == "Cotton."
        assert not workspace.listing_templates_dir().exists()

    def test_a_clone_s_draft_names_its_source(self, workspace: Workspace) -> None:
        _create(workspace)
        clone = draft_listing_template(workspace, from_listing=None, from_template=NAME)
        assert clone.source is not None
        assert (clone.source.kind, clone.source.name) == ("listing-template", NAME)

    def test_a_template_reads_back_with_what_the_listing_editor_s_tabs_show(
        self, workspace: Workspace
    ) -> None:
        edit_listing(workspace.root, etsy={"description": {"lead": "", "text": "Cotton."}})
        _create(workspace)

        view = read_listing_template(workspace, NAME)

        assert [(p.size, str(p.amount)) for p in view.resolved_prices[:2]] == [
            ("S", "349 NOK"),
            ("M", "349 NOK"),
        ]
        assert view.garment_profile is not None
        assert view.garment_profile.materials == ["cotton"]
        assert view.description_composed == "Cotton."
        assert view.pricing_plan_name is None
        with pytest.raises(ListingTemplateMissing):
            read_listing_template(workspace, "nothing-here")

    def test_the_index_has_what_a_card_shows_and_counts_batches_made_from_it(
        self, workspace: Workspace
    ) -> None:
        _create(workspace)
        batches = BatchStore(workspace)
        batches.save(_batch(NAME))
        (workspace.listing_templates_dir() / "broken").mkdir()
        (workspace.listing_templates_dir() / "broken" / "template.yaml").write_text(
            "colors: 7\n", "utf-8"
        )

        [card] = list_listing_templates(workspace, batches=batches)

        assert (card.name, card.garment, card.batch_count) == (NAME, "Comfort Colors 1717", 1)
        assert len(card.template.colors) == 4
        assert card.design_minimum is not None


class TestEdit:
    def test_an_incomplete_document_is_not_saved_and_the_file_is_untouched(
        self, workspace: Workspace, locks: WorkspaceLocks
    ) -> None:
        _create(workspace)
        before = workspace.listing_template_file(NAME).read_bytes()

        outcome = edit_listing_template(
            workspace,
            NAME,
            {**_document(workspace), "colors": [], "media": ["common-media/size-guide.png"]},
            locks=locks,
        )

        assert not outcome.saved and outcome.issues[0].where == "Variants › Colours"
        assert workspace.listing_template_file(NAME).read_bytes() == before

    def test_a_malformed_document_is_not_saved(
        self, workspace: Workspace, locks: WorkspaceLocks
    ) -> None:
        _create(workspace)
        before = workspace.listing_template_file(NAME).read_bytes()

        outcome = edit_listing_template(
            workspace, NAME, {**_document(workspace), "brief": "no"}, locks=locks
        )

        assert not outcome.saved and "brief" in outcome.field_errors
        assert workspace.listing_template_file(NAME).read_bytes() == before

    def test_a_complete_document_is_written_and_answered(
        self, workspace: Workspace, locks: WorkspaceLocks
    ) -> None:
        _create(workspace)
        outcome = edit_listing_template(
            workspace,
            NAME,
            {**_document(workspace), "colors": ["black"], "media": [BLACK]},
            locks=locks,
        )
        assert outcome.saved and outcome.template is not None
        assert outcome.template.template.colors == ["black"]
        assert workspace.load_listing_template(NAME).colors == ["black"]

    def test_a_missing_template_is_refused(
        self, workspace: Workspace, locks: WorkspaceLocks
    ) -> None:
        with pytest.raises(ListingTemplateMissing):
            edit_listing_template(workspace, "gone", {}, locks=locks)
        assert not workspace.listing_template_dir("gone").exists()


class TestRenameAndDelete:
    def test_rename_moves_the_template_and_its_own_files(
        self, workspace: Workspace, locks: WorkspaceLocks
    ) -> None:
        _local_picture(workspace)
        _create(workspace)

        rename_listing_template(
            workspace,
            NAME,
            "everyday-tee",
            locks=locks,
            staging=StagingStore(workspace),
            batches=BatchStore(workspace),
        )

        assert workspace.listing_template_names() == ["everyday-tee"]
        assert workspace.listing_template_media_file(
            "everyday-tee", "assets/shots/back.png"
        ).is_file()

    def test_batches_and_staging_made_from_it_follow_by_name_and_keep_their_frozen_copy(
        self, workspace: Workspace, locks: WorkspaceLocks
    ) -> None:
        _create(workspace)
        batches, staging = BatchStore(workspace), StagingStore(workspace)
        batches.save(_batch(NAME))
        small_print_area(workspace.root)
        session = stage_pngs(workspace, staging, NAME, uploads(("night-hike.png", png(1))))

        rename_listing_template(
            workspace, NAME, "everyday-tee", locks=locks, staging=staging, batches=batches
        )

        record = batches.load("b1")
        assert record is not None
        assert record.listing_template == "everyday-tee"
        assert record.template == {"frozen": True}
        staged = staging.load(session.id)
        assert staged is not None and staged.listing_template == "everyday-tee"

    def test_a_taken_name_is_refused_and_nothing_moves(
        self, workspace: Workspace, locks: WorkspaceLocks
    ) -> None:
        _create(workspace)
        _create(workspace, "everyday-tee", from_template=NAME)

        with pytest.raises(ListingTemplateExistsError):
            _rename(workspace, NAME, "everyday-tee", locks)
        assert workspace.listing_template_names() == ["everyday-tee", NAME]

    def test_the_same_name_changes_nothing(
        self, workspace: Workspace, locks: WorkspaceLocks
    ) -> None:
        _create(workspace)
        _rename(workspace, NAME, NAME, locks)
        assert workspace.listing_template_names() == [NAME]

    def test_bad_names_and_missing_templates_are_refused(
        self, workspace: Workspace, locks: WorkspaceLocks
    ) -> None:
        _create(workspace)
        with pytest.raises(InvalidNameError):
            _rename(workspace, NAME, "../escape", locks)
        with pytest.raises(ReservedListingTemplateName):
            _rename(workspace, NAME, "draft", locks)
        with pytest.raises(ListingTemplateMissing):
            _rename(workspace, "gone", "x", locks)

    def test_delete_removes_the_template_whatever_was_made_from_it(
        self, workspace: Workspace, locks: WorkspaceLocks
    ) -> None:
        _create(workspace)
        BatchStore(workspace).save(_batch(NAME))

        delete_listing_template(workspace, NAME, locks=locks)

        assert not workspace.listing_template_dir(NAME).exists()
        with pytest.raises(ListingTemplateMissing):
            delete_listing_template(workspace, NAME, locks=locks)


# ------------------------------------------------------- competing writes


@pytest.fixture
def slow_renames(monkeypatch: pytest.MonkeyPatch) -> None:
    real = Path.rename

    def slow(self: Path, target: Any) -> Path:  # noqa: ANN401
        time.sleep(0.3)
        return real(self, target)

    monkeypatch.setattr(Path, "rename", slow)


@pytest.fixture
def slow_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    real = yaml.safe_dump

    def slow(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        time.sleep(0.3)
        return real(*args, **kwargs)

    monkeypatch.setattr(yaml, "safe_dump", slow)


def _together(*calls: Callable[[], object]) -> list[object]:
    """Each call a moment after the one before; a refusal in its place."""

    def outcome(call: Callable[[], object]) -> object:
        try:
            return call()
        except (ListingTemplateMissing, ListingTemplateExistsError) as exc:
            return exc

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = []
        for call in calls:
            futures.append(pool.submit(outcome, call))
            time.sleep(0.1)
        return [future.result() for future in futures]


class TestCompetingWrites:
    def test_an_edit_queued_behind_a_rename_finds_the_template_gone(
        self, workspace: Workspace, locks: WorkspaceLocks, slow_renames: None
    ) -> None:
        """It must not write a fresh ``template.yaml`` under the old name."""
        _create(workspace)
        document = {**_document(workspace), "colors": ["black"], "media": [BLACK]}

        rename, edit = _together(
            lambda: _rename(workspace, NAME, "everyday-tee", locks),
            lambda: edit_listing_template(workspace, NAME, document, locks=locks),
        )

        assert rename is None
        assert isinstance(edit, ListingTemplateMissing)
        assert not workspace.listing_template_dir(NAME).exists()
        assert len(workspace.load_listing_template("everyday-tee").colors) == 4

    def test_a_create_and_a_rename_to_the_same_name_do_not_both_win(
        self, workspace: Workspace, locks: WorkspaceLocks, slow_renames: None
    ) -> None:
        _create(workspace)

        outcomes = _together(
            lambda: _rename(workspace, NAME, "everyday-tee", locks),
            lambda: _create(workspace, "everyday-tee", locks=locks, from_template=NAME),
        )

        assert outcomes[0] is None
        assert isinstance(outcomes[1], ListingTemplateMissing | ListingTemplateExistsError)
        assert workspace.listing_template_names() == ["everyday-tee"]

    def test_two_creates_of_one_name_write_it_once(
        self, workspace: Workspace, locks: WorkspaceLocks, slow_writes: None
    ) -> None:
        first, second = _together(
            lambda: _create(workspace, locks=locks),
            lambda: _create(workspace, locks=locks),
        )

        assert isinstance(first, TemplateSave) and first.saved
        assert isinstance(second, ListingTemplateExistsError)
        assert workspace.listing_template_names() == [NAME]


def _rename(workspace: Workspace, old: str, new: str, locks: WorkspaceLocks) -> None:
    rename_listing_template(
        workspace,
        old,
        new,
        locks=locks,
        staging=StagingStore(workspace),
        batches=BatchStore(workspace),
    )


def _batch(template: str) -> Batch:
    now = datetime(2026, 9, 27, 11, 42, tzinfo=UTC)
    return Batch(
        id="b1",
        listing_template=template,
        template={"frozen": True},
        template_saved_at=now,
        label=f"{template} · 27 Sep 11:42",
        created_at=now,
        rows=[],
    )
