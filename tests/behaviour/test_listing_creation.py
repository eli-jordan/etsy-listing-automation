"""Creating a listing, and the pricing-plan reads both creation paths share,
called directly -- no ``TestClient``, no ``CliRunner`` (module-structure plan,
PR 6).

The listings editor's ``POST /api/listings`` and the ``new`` wizard both end
here: one interpretation of which plans exist and suit a garment, one way a
``listing.yaml`` is first written. The HTTP status codes these refusals
become are the listings API tests' business.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from etsy_listings.core.application.listing_creation import create_listing, write_listing
from etsy_listings.core.application.pricing_plans import (
    load_candidate_pricing_plans,
    pricing_plan_options,
    pricing_plan_ref,
)
from etsy_listings.core.application.refusals import InvalidListing, ListingNameTaken
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.config.money import Money
from etsy_listings.core.config.pricing_plan import PricingPlan
from etsy_listings.core.workspace.workspace import InvalidNameError, Workspace

from tests.support.builders import FIXTURE_LISTING


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def a_document(**over: Any) -> dict[str, Any]:  # noqa: ANN401
    document: dict[str, Any] = {
        "garment_profile": "comfort-colors-1717",
        "design": "designs/take-a-hike.png",
        "colors": ["black"],
        "brief": "",
        "prices": {"S": "349 NOK"},
        "media": [],
    }
    document.update(over)
    return document


class TestCreateListing:
    def test_writes_the_document_it_was_given(self, workspace: Workspace) -> None:
        outcome = create_listing(workspace, "my-new-shirt", a_document(), locks=WorkspaceLocks())

        assert outcome is None
        written = yaml.safe_load(workspace.listing_file("my-new-shirt").read_text(encoding="utf-8"))
        assert written == a_document()

    def test_an_incomplete_document_is_still_written(self, workspace: Workspace) -> None:
        """ADR-0043: no price source is incompleteness, which blocks a deploy
        and does not withhold the file."""
        outcome = create_listing(
            workspace,
            "half-done",
            a_document(prices={}, pricing_plan=None, colors=[]),
            locks=WorkspaceLocks(),
        )

        assert outcome is None
        assert workspace.listing_file("half-done").is_file()

    def test_a_malformed_document_is_refused_with_field_errors_and_writes_nothing(
        self, workspace: Workspace
    ) -> None:
        """The other side of ADR-0043's line: a bare number is not a price."""
        outcome = create_listing(
            workspace, "bad-money", a_document(prices={"S": 349}), locks=WorkspaceLocks()
        )

        assert isinstance(outcome, InvalidListing)
        assert any(key.startswith("prices") for key in outcome.field_errors)
        assert not workspace.listing_dir("bad-money").exists()

    def test_refuses_a_name_already_in_use(self, workspace: Workspace) -> None:
        before = workspace.listing_file(FIXTURE_LISTING).read_bytes()

        with pytest.raises(ListingNameTaken) as refused:
            create_listing(workspace, FIXTURE_LISTING, a_document(), locks=WorkspaceLocks())

        assert refused.value.name == FIXTURE_LISTING
        assert workspace.listing_file(FIXTURE_LISTING).read_bytes() == before

    def test_refuses_a_leftover_directory_with_no_listing_file(self, workspace: Workspace) -> None:
        """Writing into it would hand the new listing the old one's remote ids."""
        leftover = workspace.listing_dir("half-deleted")
        leftover.mkdir(parents=True)
        (leftover / "state.lock.json").write_text("{}", encoding="utf-8")

        with pytest.raises(ListingNameTaken):
            create_listing(workspace, "half-deleted", a_document(), locks=WorkspaceLocks())

        assert not workspace.listing_file("half-deleted").exists()

    def test_a_name_taken_is_checked_before_the_document(self, workspace: Workspace) -> None:
        """A taken name is the refusal, whatever the document says."""
        with pytest.raises(ListingNameTaken):
            create_listing(
                workspace, FIXTURE_LISTING, a_document(prices={"S": 349}), locks=WorkspaceLocks()
            )

    def test_refuses_a_name_that_is_not_a_path_segment(self, workspace: Workspace) -> None:
        with pytest.raises(InvalidNameError):
            create_listing(workspace, "../escape", a_document(), locks=WorkspaceLocks())

    def test_holds_the_new_names_write_lock(self, workspace: Workspace) -> None:
        held: list[tuple[str, ...]] = []

        class Recording(WorkspaceLocks):
            def listing(self, name: str, *more: str):  # type: ignore[override]  # noqa: ANN202
                held.append((name, *more))
                return super().listing(name, *more)

        create_listing(workspace, "my-new-shirt", a_document(), locks=Recording())

        assert held == [("my-new-shirt",)]


class TestWriteListing:
    def test_refuses_to_overwrite_an_existing_listing(self, workspace: Workspace) -> None:
        with pytest.raises(FileExistsError):
            write_listing(workspace, FIXTURE_LISTING, a_document())

    def test_creates_the_listing_directory(self, workspace: Workspace) -> None:
        path = write_listing(workspace, "fresh", a_document())

        assert path == workspace.listing_file("fresh")
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["colors"] == ["black"]


def _plan(garment_profile: str) -> PricingPlan:
    return PricingPlan(garment_profile=garment_profile, prices={"S": Money.parse("100 NOK")})


class TestPricingPlans:
    def test_options_put_plans_for_this_garment_first(self, tmp_path: Path) -> None:
        plans = [
            (tmp_path / "b-other.yaml", _plan("a-different-profile")),
            (tmp_path / "Z-matching.yaml", _plan("comfort-colors-1717")),
            (tmp_path / "a-matching.yaml", _plan("comfort-colors-1717")),
        ]

        options = pricing_plan_options(plans, "comfort-colors-1717")

        assert [(o.path.stem, o.compatible) for o in options] == [
            ("a-matching", True),
            ("Z-matching", True),
            ("b-other", False),
        ]
        assert options[0].plan.garment_profile == "comfort-colors-1717"

    def test_no_garment_marks_no_plan_compatible(self, tmp_path: Path) -> None:
        options = pricing_plan_options([(tmp_path / "x.yaml", _plan("comfort-colors-1717"))], "")

        assert [o.compatible for o in options] == [False]

    def test_a_broken_plan_is_skipped_not_fatal(self, workspace_root: Path) -> None:
        plans_dir = workspace_root / "pricing-plans"
        plans_dir.mkdir()
        (plans_dir / "good.yaml").write_text(
            "garment_profile: comfort-colors-1717\nprices:\n  S: 100 NOK\n", encoding="utf-8"
        )
        (plans_dir / "bad.yaml").write_text(
            "garment_profile: x\nprices:\n  S: 100\n", encoding="utf-8"
        )

        workspace = Workspace.discover(root_override=workspace_root)

        assert [path.stem for path, _ in load_candidate_pricing_plans(workspace)] == ["good"]

    def test_a_ref_is_written_from_the_workspace_root(self, tmp_path: Path) -> None:
        # ADR-0046: no prefix is the workspace root, whichever listing stores it.
        flat = tmp_path / "pricing-plans" / "launch-low.yaml"
        assert pricing_plan_ref(flat, root=tmp_path) == "pricing-plans/launch-low.yaml"

        nested = tmp_path / "pricing-plans" / "comfort-colors-1717" / "launch-low.yaml"
        assert (
            pricing_plan_ref(nested, root=tmp_path)
            == "pricing-plans/comfort-colors-1717/launch-low.yaml"
        )
