"""Save as listing template and Clone, through `listing_templates` (ADR-0047, template completeness;
spec *Creation and cloning*).

Conversion is a plan, not a write: `from_listing` and `from_template` answer
the template document and the files it would copy, and only `save` touches
the disk. The fixture workspace is copied per test, so every assertion about
what landed where reads real files.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from etsy_listings.config.listing_template import ListingTemplate
from etsy_listings.config.money import Money
from etsy_listings.listing_templates import (
    ListingTemplateExistsError,
    UnreadableAssetError,
    from_listing,
    from_template,
    save,
)
from etsy_listings.workspace.facts import WorkspaceFacts
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING, edit_listing

VIDEO = Path(__file__).parents[1] / "fixtures" / "video" / "valid-3s-512.mp4"


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def _save(workspace: Workspace, name: str, *, listing: str = FIXTURE_LISTING) -> list[Any]:
    return save(
        workspace, name, from_listing(workspace, listing), facts=WorkspaceFacts.gather(workspace)
    )


def _blocks(issues: list[Any]) -> list[Any]:
    """The fixture's garment profile classifies no colours, so every save
    carries that warning; only a block would have refused the write."""
    return [issue for issue in issues if issue.severity == "block"]


def _saved(workspace: Workspace, name: str) -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(
        workspace.listing_template_file(name).read_text(encoding="utf-8")
    )
    return document


def _local_file(workspace: Workspace, ref: str, content: bytes) -> None:
    path = workspace.listing_dir(FIXTURE_LISTING) / ref.removeprefix("./")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class TestWhatIsCopied:
    def test_every_production_field_is_copied(self, workspace: Workspace) -> None:
        edit_listing(
            workspace.root,
            price_overrides={"black": {"XL": "399 NOK"}},
            pricing_plan="pricing-plans/standard.yaml",
            etsy={
                "title": "Take A Hike Tee",
                "tags": ["hiking"],
                "description": {"lead": "Retro sunset.", "ref": "common-copy/care.md"},
                "renewal": "auto",
                "section": "Hiking tees",
                "shipping_profile": "NOK heavy tee",
                "variation_images": "flat-lay-01",
            },
        )

        template = from_listing(workspace, FIXTURE_LISTING).template

        assert template.garment_profile == "comfort-colors-1717"
        assert template.colors == ["black", "blue-jean", "ivory", "moss"]
        assert template.prices["XXXL"] == Money.parse("379 NOK")
        assert template.pricing_plan == "pricing-plans/standard.yaml"
        assert template.price_overrides == {"black": {"XL": Money.parse("399 NOK")}}
        assert [entry.colour for entry in template.media] == [  # type: ignore[union-attr]
            "black",
            "blue-jean",
            "ivory",
            "moss",
        ]
        assert template.etsy.description.ref == "common-copy/care.md"
        assert (
            template.etsy.renewal,
            template.etsy.section,
            template.etsy.shipping_profile,
            template.etsy.variation_images,
        ) == ("auto", "Hiking tees", "NOK heavy tee", "flat-lay-01")

    def test_inline_description_text_is_kept(self, workspace: Workspace) -> None:
        edit_listing(
            workspace.root,
            etsy={"description": {"lead": "Retro sunset.", "text": "Garment-dyed cotton."}},
        )

        template = from_listing(workspace, FIXTURE_LISTING).template

        assert template.etsy.description.text == "Garment-dyed cotton."

    def test_design_brief_artwork_copy_and_lifecycle_are_left_behind(
        self, workspace: Workspace
    ) -> None:
        edit_listing(
            workspace.root,
            artwork={"black": "default"},
            lifecycle="retired",
            etsy={
                "title": "Take A Hike Tee",
                "tags": ["hiking"],
                "description": {"lead": "Retro sunset."},
            },
        )

        assert _blocks(_save(workspace, "heavyweight-tee")) == []

        saved = _saved(workspace, "heavyweight-tee")
        for field in ("design", "brief", "artwork", "lifecycle"):
            assert field not in saved
        etsy = saved.get("etsy", {})
        assert "title" not in etsy
        assert "tags" not in etsy
        assert "lead" not in etsy.get("description", {})

    def test_no_applied_or_remote_state_is_copied(self, workspace: Workspace) -> None:
        workspace.lock_file(FIXTURE_LISTING).write_text('{"remote": {}}', encoding="utf-8")

        _save(workspace, "heavyweight-tee")

        directory = workspace.listing_template_dir("heavyweight-tee")
        assert [p.name for p in directory.iterdir()] == ["template.yaml"]


class TestFileRefs:
    def test_a_shared_ref_stays_shared(self, workspace: Workspace) -> None:
        shared = workspace.common_media_dir() / "size-guide.png"
        shared.parent.mkdir(parents=True)
        shared.write_bytes(b"chart")
        edit_listing(
            workspace.root,
            media=[{"template": "flat-lay-01", "colour": "black"}, "common-media/size-guide.png"],
        )

        draft = from_listing(workspace, FIXTURE_LISTING)

        assert draft.template.media[1] == "common-media/size-guide.png"
        assert draft.assets == ()

    def test_a_local_image_and_video_are_copied_and_rewritten(self, workspace: Workspace) -> None:
        _local_file(workspace, "./shots/back.png", b"back")
        _local_file(workspace, "./clip.mp4", VIDEO.read_bytes())
        edit_listing(
            workspace.root,
            media=[
                {"template": "flat-lay-01", "colour": "black"},
                "./clip.mp4",
                "./shots/back.png",
            ],
        )

        assert _blocks(_save(workspace, "heavyweight-tee")) == []

        assert _saved(workspace, "heavyweight-tee")["media"][1:] == [
            "./assets/clip.mp4",
            "./assets/shots/back.png",
        ]
        assets = workspace.listing_template_assets_dir("heavyweight-tee")
        assert (assets / "shots" / "back.png").read_bytes() == b"back"
        assert (assets / "clip.mp4").read_bytes() == VIDEO.read_bytes()

    def test_a_missing_local_file_refuses_naming_the_ref(self, workspace: Workspace) -> None:
        edit_listing(
            workspace.root,
            media=[{"template": "flat-lay-01", "colour": "black"}, "./shots/gone.png"],
        )

        with pytest.raises(UnreadableAssetError, match=r"\./shots/gone\.png"):
            from_listing(workspace, FIXTURE_LISTING)

    def test_a_local_pricing_plan_travels_with_the_template(self, workspace: Workspace) -> None:
        plan = workspace.listing_dir(FIXTURE_LISTING) / "plan.yaml"
        plan.write_text("garment_profile: comfort-colors-1717\nprices: {}\n", encoding="utf-8")
        edit_listing(workspace.root, pricing_plan="./plan.yaml")

        _save(workspace, "heavyweight-tee")

        assert _saved(workspace, "heavyweight-tee")["pricing_plan"] == "./assets/plan.yaml"
        copied = workspace.listing_template_assets_dir("heavyweight-tee") / "plan.yaml"
        assert copied.read_bytes() == plan.read_bytes()


class TestSaving:
    def test_a_saved_template_loads_back_as_it_was_converted(self, workspace: Workspace) -> None:
        draft = from_listing(workspace, FIXTURE_LISTING)

        save(workspace, "heavyweight-tee", draft, facts=WorkspaceFacts.gather(workspace))

        assert workspace.load_listing_template("heavyweight-tee") == draft.template
        assert workspace.listing_template_names() == ["heavyweight-tee"]

    def test_a_name_clash_is_refused_never_suffixed(self, workspace: Workspace) -> None:
        _save(workspace, "heavyweight-tee")
        before = workspace.listing_template_file("heavyweight-tee").read_bytes()
        edit_listing(workspace.root, colors=["black"], media=[])

        with pytest.raises(ListingTemplateExistsError, match="heavyweight-tee"):
            _save(workspace, "heavyweight-tee")

        assert workspace.listing_template_names() == ["heavyweight-tee"]
        assert workspace.listing_template_file("heavyweight-tee").read_bytes() == before

    def test_an_incomplete_template_is_refused_with_its_issues(self, workspace: Workspace) -> None:
        edit_listing(workspace.root, colors=[], media=["common-media/size-guide.png"])

        issues = _save(workspace, "heavyweight-tee")

        assert [(i.severity, i.where) for i in issues] == [("block", "Variants › Colours")]
        assert not workspace.listing_template_dir("heavyweight-tee").exists()

    def test_a_failed_copy_leaves_no_template_behind(
        self, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _local_file(workspace, "./shots/back.png", b"back")
        edit_listing(
            workspace.root,
            media=[{"template": "flat-lay-01", "colour": "black"}, "./shots/back.png"],
        )
        draft = from_listing(workspace, FIXTURE_LISTING)

        def fail(*_: object, **__: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(shutil, "copyfile", fail)
        with pytest.raises(OSError, match="disk full"):
            save(workspace, "heavyweight-tee", draft, facts=WorkspaceFacts.gather(workspace))

        assert not workspace.listing_template_dir("heavyweight-tee").exists()


class TestCloning:
    def test_a_clone_is_an_independent_copy_with_its_own_assets(self, workspace: Workspace) -> None:
        _local_file(workspace, "./shots/back.png", b"back")
        edit_listing(
            workspace.root,
            media=[{"template": "flat-lay-01", "colour": "black"}, "./shots/back.png"],
        )
        _save(workspace, "heavyweight-tee")

        draft = from_template(workspace, "heavyweight-tee")
        issues = save(workspace, "everyday-tee", draft, facts=WorkspaceFacts.gather(workspace))
        workspace.remove_listing_template("heavyweight-tee")

        assert _blocks(issues) == []
        clone: ListingTemplate = workspace.load_listing_template("everyday-tee")
        assert clone.media[1] == "./assets/shots/back.png"
        copied = workspace.listing_template_assets_dir("everyday-tee") / "shots" / "back.png"
        assert copied.read_bytes() == b"back"
