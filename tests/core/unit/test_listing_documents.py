"""``listing.yaml``'s one reader and writer, and the listing's lock.

Every writer of a listing document takes this lock. Competing writers are
made to overlap with threads and a held lock, not left to timing.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from etsy_listings.core.workspace.listing_documents import (
    Document,
    ListingDocuments,
    ListingMissing,
    ListingNameTaken,
)
from etsy_listings.core.workspace.workspace import InvalidNameError, Workspace

from tests.support.builders import FIXTURE_LISTING as NAME
from tests.support.refusals import refuse_reads


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def documents(workspace: Workspace) -> ListingDocuments:
    return ListingDocuments(workspace)


def a_document(**over: Any) -> dict[str, Any]:  # noqa: ANN401
    document: dict[str, Any] = {
        "garment_profile": "comfort-colors-1717",
        "design": {"default": "designs/take-a-hike.png"},
        "colors": ["black"],
        "brief": "",
        "prices": {"S": "349 NOK"},
        "media": [],
    }
    document.update(over)
    return document


def _on_disk(workspace: Workspace, name: str = NAME) -> Document:
    loaded: Document = yaml.safe_load(workspace.listing_file(name).read_text(encoding="utf-8"))
    return loaded


class TestQuestions:
    def test_a_saved_listing_exists_and_its_name_is_taken(
        self, documents: ListingDocuments
    ) -> None:
        assert documents.exists(NAME)
        assert not documents.is_free(NAME)

    def test_a_leftover_directory_is_no_listing_but_its_name_is_taken(
        self, workspace: Workspace, documents: ListingDocuments
    ) -> None:
        """A new listing there would inherit the old one's remote ids."""
        leftover = workspace.listing_dir("half-deleted")
        leftover.mkdir(parents=True)
        (leftover / "state.lock.json").write_text("{}", encoding="utf-8")

        assert not documents.exists("half-deleted")
        assert not documents.is_free("half-deleted")

    def test_an_unknown_name_is_free(self, documents: ListingDocuments) -> None:
        assert not documents.exists("never-made")
        assert documents.is_free("never-made")


class TestRead:
    def test_reads_the_document_as_written(
        self, workspace: Workspace, documents: ListingDocuments
    ) -> None:
        assert documents.read(NAME) == _on_disk(workspace)

    def test_a_missing_listing_is_refused(self, documents: ListingDocuments) -> None:
        with pytest.raises(ListingMissing):
            documents.read("never-made")

    def test_waits_out_a_replace_in_progress(
        self, documents: ListingDocuments, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Windows refuses to open a file mid-replace. A read lands on the
        editor's autosave often enough that it must retry, not fail."""
        sleeps = refuse_reads(monkeypatch, times=2)

        assert documents.read(NAME)["colors"]
        assert len(sleeps) == 2


class TestEdit:
    def test_writes_what_the_change_returns(
        self, workspace: Workspace, documents: ListingDocuments
    ) -> None:
        written = documents.edit(NAME, lambda raw: {**raw, "brief": "A sunset hike."})

        assert written is not None and written["brief"] == "A sunset hike."
        assert _on_disk(workspace)["brief"] == "A sunset hike."

    def test_a_declined_change_writes_nothing(
        self, workspace: Workspace, documents: ListingDocuments
    ) -> None:
        before = workspace.listing_file(NAME).read_bytes()

        assert documents.edit(NAME, lambda raw: None) is None
        assert workspace.listing_file(NAME).read_bytes() == before

    def test_a_raising_change_writes_nothing(
        self, workspace: Workspace, documents: ListingDocuments
    ) -> None:
        before = workspace.listing_file(NAME).read_bytes()

        def refuse(raw: Document) -> Document:
            raise ValueError("no")

        with pytest.raises(ValueError, match="no"):
            documents.edit(NAME, refuse)
        assert workspace.listing_file(NAME).read_bytes() == before

    def test_a_missing_listing_is_refused_and_not_recreated(
        self, workspace: Workspace, documents: ListingDocuments
    ) -> None:
        with pytest.raises(ListingMissing):
            documents.edit("never-made", lambda raw: raw)
        assert not workspace.listing_dir("never-made").exists()

    def test_keeps_non_ascii_text_readable(
        self, workspace: Workspace, documents: ListingDocuments
    ) -> None:
        """A seller opens ``listing.yaml`` by hand; ``Ærø`` must not become
        an escape sequence there."""
        documents.edit(NAME, lambda raw: {**raw, "brief": "Hike on Ærø"})

        assert "Hike on Ærø" in workspace.listing_file(NAME).read_text(encoding="utf-8")

    def test_an_edit_waiting_for_the_lock_reads_what_the_holder_wrote(
        self, workspace: Workspace, documents: ListingDocuments
    ) -> None:
        """Two read-merge-writes interleaved would lose the first. The second
        must read inside the lock, after the first has written."""
        finished = threading.Event()

        def second() -> None:
            documents.edit(
                NAME, lambda raw: {**raw, "etsy": {**raw["etsy"], "title": "Take A Hike Tee"}}
            )
            finished.set()

        with documents.lock(NAME):
            waiting = threading.Thread(target=second)
            waiting.start()
            assert not finished.wait(0.2), "the edit did not wait for the lock"
            documents.edit(NAME, lambda raw: {**raw, "brief": "A sunset hike."})
        waiting.join(timeout=5)

        written = _on_disk(workspace)
        assert written["brief"] == "A sunset hike."
        assert written["etsy"]["title"] == "Take A Hike Tee"


class TestCreate:
    def test_writes_a_new_listing_and_answers_its_path(
        self, workspace: Workspace, documents: ListingDocuments
    ) -> None:
        path = documents.create("fresh", a_document())

        assert path == workspace.listing_file("fresh")
        assert _on_disk(workspace, "fresh") == a_document()

    def test_refuses_a_taken_name_before_looking_at_the_document(
        self, workspace: Workspace, documents: ListingDocuments
    ) -> None:
        before = workspace.listing_file(NAME).read_bytes()

        with pytest.raises(ListingNameTaken):
            documents.create(NAME, a_document(prices={"S": 349}))
        assert workspace.listing_file(NAME).read_bytes() == before

    def test_refuses_a_malformed_document_and_writes_nothing(
        self, workspace: Workspace, documents: ListingDocuments
    ) -> None:
        with pytest.raises(ValidationError):
            documents.create("bad-money", a_document(prices={"S": 349}))
        assert not workspace.listing_dir("bad-money").exists()

    def test_refuses_a_name_that_is_not_a_path_segment(self, documents: ListingDocuments) -> None:
        with pytest.raises(InvalidNameError):
            documents.create("../escape", a_document())


class TestWrite:
    def test_replaces_a_document_already_there(
        self, workspace: Workspace, documents: ListingDocuments
    ) -> None:
        documents.write(NAME, a_document(brief="Rewritten."))

        assert _on_disk(workspace)["brief"] == "Rewritten."


class TestLock:
    def test_every_documents_over_one_workspace_shares_the_lock(self, workspace_root: Path) -> None:
        """The engine, the editor and batch creation each make their own."""
        one = ListingDocuments(Workspace.discover(root_override=workspace_root))
        other = ListingDocuments(Workspace.discover(root_override=workspace_root))
        entered = threading.Event()

        def take() -> None:
            with other.lock(NAME):
                entered.set()

        with one.lock(NAME):
            waiting = threading.Thread(target=take)
            waiting.start()
            assert not entered.wait(0.2)
        waiting.join(timeout=5)
        assert entered.is_set()

    def test_names_differing_only_in_case_share_a_lock(self, documents: ListingDocuments) -> None:
        """Windows makes them one directory."""
        entered = threading.Event()

        def take() -> None:
            with documents.lock(NAME.upper()):
                entered.set()

        with documents.lock(NAME):
            waiting = threading.Thread(target=take)
            waiting.start()
            assert not entered.wait(0.2)
        waiting.join(timeout=5)
        assert entered.is_set()

    def test_a_holder_may_take_it_again(self, documents: ListingDocuments) -> None:
        """A rename holds the lock and moves the proposal, whose store takes
        it too."""
        with documents.lock(NAME), documents.lock(NAME, "hike-away"):
            documents.edit(NAME, lambda raw: {**raw, "brief": "Nested."})

        assert documents.read(NAME)["brief"] == "Nested."

    def test_refuses_a_name_that_is_not_a_path_segment(self, documents: ListingDocuments) -> None:
        with pytest.raises(InvalidNameError), documents.lock("../escape"):
            pass
