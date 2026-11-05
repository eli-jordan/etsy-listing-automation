"""Renaming a mockup template: what follows it, what refuses it, and that a
deployed listing sends nothing to Etsy because of it."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from etsy_listings.core.application.refusals import (
    TemplateInUseError,
    TemplateMissingError,
    TemplateNameTakenError,
)
from etsy_listings.core.application.template_rename import (
    RenameHosts,
    TemplateRename,
    rename_template,
)
from etsy_listings.core.batches.records import (
    BatchRecords,
    BatchStore,
    StagingSession,
    StagingStore,
)
from etsy_listings.core.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.core.engine.apply import execute
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.plan import build_plan
from etsy_listings.core.engine.run import preview_listing
from etsy_listings.core.engine.stages.etsy_media import IMAGE_IDS_KEY, EtsyMediaStage
from etsy_listings.core.engine.stages.render import RenderStage
from etsy_listings.core.workspace.workspace import InvalidNameError, Workspace

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import (
    a_context,
    a_lock,
    edit_garment_profile,
    edit_listing,
    listing_file,
    set_etsy_shop_id,
)

OLD = "flat-lay-01"
NEW = "cc1717-flat-lay"
PROFILE = "comfort-colors-1717"
ETSY_LISTING_ID = 4572550919
SHOP_ID = 12345678
STAGES = [RenderStage(), EtsyMediaStage()]


class Mover:
    """The preparation queue when no job is in the way."""

    def rename_template(self, old: str, new: str, move: Callable[[], None]) -> None:
        del old, new
        move()


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def records(workspace: Workspace) -> BatchRecords:
    return BatchRecords(StagingStore(workspace), BatchStore(workspace))


def _rename(
    workspace: Workspace,
    records: BatchRecords,
    new: str = NEW,
    *,
    old: str = OLD,
    deploying: bool = False,
) -> TemplateRename:
    hosts = RenameHosts(Mover(), records, lambda: deploying)
    return rename_template(workspace, old, new, hosts)


def _box() -> list[list[int]]:
    """A new one each time: a shared list would dump as a YAML alias."""
    return [[0, 0], [10, 0], [10, 10], [0, 10]]


def _listing(root: Path) -> dict:
    return yaml.safe_load(listing_file(root).read_text(encoding="utf-8"))


def test_the_directory_moves_with_its_calibration(
    workspace: Workspace, records: BatchRecords
) -> None:
    before = workspace.template_config_file(OLD).read_bytes()

    _rename(workspace, records)

    assert not workspace.has_template(OLD)
    assert workspace.template_config_file(NEW).read_bytes() == before


def test_a_listing_follows_everywhere_it_names_the_template(
    workspace: Workspace, records: BatchRecords
) -> None:
    edit_listing(
        workspace.root,
        etsy={**_listing(workspace.root)["etsy"], "variation_images": OLD},
        template_positions={
            OLD: {"bounding_box": _box()},
            "colour-chart-01": {"bounding_box": _box()},
        },
    )

    done = _rename(workspace, records)

    listing = _listing(workspace.root)
    assert {entry["template"] for entry in listing["media"]} == {NEW}
    assert listing["etsy"]["variation_images"] == NEW
    assert set(listing["template_positions"]) == {NEW, "colour-chart-01"}
    assert f"listings/{LISTING}/listing.yaml" in done.updated
    assert done.unresolved == ()


def test_a_listing_keeps_the_sellers_comments(workspace: Workspace, records: BatchRecords) -> None:
    path = listing_file(workspace.root)
    source = path.read_text(encoding="utf-8")
    path.write_text(source.replace("media:", "# the hero shot leads\nmedia:"), encoding="utf-8")

    _rename(workspace, records)

    assert "# the hero shot leads\nmedia:" in path.read_text(encoding="utf-8")


def test_a_listing_naming_another_template_is_left_alone(
    workspace: Workspace, records: BatchRecords
) -> None:
    path = listing_file(workspace.root)
    before = path.read_bytes()

    done = _rename(workspace, records, old="colour-chart-01")

    assert path.read_bytes() == before
    assert done.updated == ()


def test_a_garment_profile_follows(workspace: Workspace, records: BatchRecords) -> None:
    edit_garment_profile(workspace.root, PROFILE, preview_template=OLD)

    done = _rename(workspace, records)

    assert workspace.load_garment_profile(PROFILE).preview_template == NEW
    assert f"garment-profiles/{PROFILE}.yaml" in done.updated


def test_a_listing_template_follows(workspace: Workspace, records: BatchRecords) -> None:
    path = workspace.listing_template_file("everyday")
    path.parent.mkdir(parents=True)
    path.write_text(f"media:\n  - template: {OLD}\n    colour: black\n", encoding="utf-8")

    done = _rename(workspace, records)

    assert yaml.safe_load(path.read_text(encoding="utf-8"))["media"][0]["template"] == NEW
    assert "listing-templates/everyday/template.yaml" in done.updated


def test_a_frozen_batch_document_follows(workspace: Workspace, records: BatchRecords) -> None:
    now = datetime.now(UTC)
    records.staging.save(
        StagingSession(
            id="session",
            listing_template="everyday",
            template={"media": [{"template": OLD, "colour": "black"}]},
            template_saved_at=now,
            label="November",
            created_at=now,
            updated_at=now,
            rows=[],
        )
    )

    _rename(workspace, records)

    session = records.staging.load("session")
    assert session is not None
    assert session.template["media"] == [{"template": NEW, "colour": "black"}]


def test_the_listing_caches_move(workspace: Workspace, records: BatchRecords) -> None:
    render = workspace.render_file(LISTING, OLD, "black")
    render.parent.mkdir(parents=True)
    render.write_bytes(b"pixels")
    preview = workspace.preview_file(LISTING, OLD, "black", "abc")
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"pixels")

    _rename(workspace, records)

    assert workspace.render_file(LISTING, NEW, "black").read_bytes() == b"pixels"
    assert workspace.preview_file(LISTING, NEW, "black", "abc").read_bytes() == b"pixels"
    assert not render.parent.exists()
    assert not preview.parent.exists()


def test_an_unreadable_listing_is_reported_and_stops_nothing(
    workspace: Workspace, records: BatchRecords
) -> None:
    edit_garment_profile(workspace.root, PROFILE, preview_template=OLD)
    listing_file(workspace.root).write_text("media: [unclosed", encoding="utf-8")

    done = _rename(workspace, records)

    assert done.unresolved == (f"listings/{LISTING}/listing.yaml",)
    assert workspace.load_garment_profile(PROFILE).preview_template == NEW
    assert workspace.has_template(NEW)


def test_renaming_to_the_same_name_changes_nothing(
    workspace: Workspace, records: BatchRecords
) -> None:
    assert _rename(workspace, records, OLD) == TemplateRename()
    assert workspace.has_template(OLD)


@pytest.mark.parametrize("name", ["a/b", "..", "a:b", "trailing.", " spaced "])
def test_an_unusable_name_is_refused(
    workspace: Workspace, records: BatchRecords, name: str
) -> None:
    with pytest.raises(InvalidNameError):
        _rename(workspace, records, name)
    assert workspace.has_template(OLD)


def test_a_taken_name_is_refused_with_nothing_changed(
    workspace: Workspace, records: BatchRecords
) -> None:
    before = listing_file(workspace.root).read_bytes()

    with pytest.raises(TemplateNameTakenError):
        _rename(workspace, records, "colour-chart-01")

    assert workspace.has_template(OLD)
    assert listing_file(workspace.root).read_bytes() == before


def test_a_listing_held_by_a_yaml_alias_is_reported(
    workspace: Workspace, records: BatchRecords
) -> None:
    """ADR-0055: an edit through an alias cannot be spliced, so it is left for
    the seller rather than rewritten into something else."""
    shared = _box()
    edit_listing(
        workspace.root,
        template_positions={OLD: {"bounding_box": shared}, "other": {"bounding_box": shared}},
    )

    done = _rename(workspace, records)

    assert done.unresolved == (f"listings/{LISTING}/listing.yaml",)


def test_a_missing_template_is_refused(workspace: Workspace, records: BatchRecords) -> None:
    with pytest.raises(TemplateMissingError):
        _rename(workspace, records, old="no-such-template")


def test_a_running_deploy_refuses_with_nothing_changed(
    workspace: Workspace, records: BatchRecords
) -> None:
    with pytest.raises(TemplateInUseError):
        _rename(workspace, records, deploying=True)
    assert workspace.has_template(OLD)


def test_a_file_held_open_refuses_with_nothing_changed(
    workspace: Workspace, records: BatchRecords, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = listing_file(workspace.root).read_bytes()

    def held_open(_self: Path, _target: Path) -> None:
        raise PermissionError

    monkeypatch.setattr(Path, "rename", held_open)

    with pytest.raises(TemplateInUseError):
        _rename(workspace, records)
    assert listing_file(workspace.root).read_bytes() == before


# ------------------------------------------------------------ a deployed listing


@pytest.fixture
def ctx(workspace_root: Path) -> RunContext:
    set_etsy_shop_id(workspace_root, SHOP_ID)
    etsy = FakeEtsyListingClient()
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=SHOP_ID)
    return a_context(workspace_root, etsy=etsy)


def _deployed(ctx: RunContext) -> Lockfile:
    lock = a_lock(remote={"etsy_listing_id": ETSY_LISTING_ID})
    applied = execute(ctx, build_plan(ctx, LISTING, lock, STAGES), lock)
    applied.write(ctx.workspace.lock_file(LISTING))
    return applied


def _rename_deployed(ctx: RunContext, records: BatchRecords) -> Lockfile:
    _rename(ctx.workspace, records)
    lock = Lockfile.read(ctx.workspace.lock_file(LISTING))
    assert lock is not None
    return lock


def test_a_rename_keeps_the_etsy_image_ids(ctx: RunContext, records: BatchRecords) -> None:
    ids = _deployed(ctx).remote[IMAGE_IDS_KEY]

    lock = _rename_deployed(ctx, records)

    assert lock.remote[IMAGE_IDS_KEY] == {
        ref.replace(OLD, NEW): image for ref, image in ids.items()
    }


def test_once_previewed_only_the_local_render_has_work(
    ctx: RunContext, records: BatchRecords
) -> None:
    """The render hash spells the name, so the scene re-renders. Its preview
    proves the pixels match what Etsy has, as for any identical re-render."""
    _deployed(ctx)
    lock = _rename_deployed(ctx, records)
    preview_listing(ctx, build_plan(ctx, LISTING, lock, STAGES))

    stages = {p.stage: p.will_run for p in build_plan(ctx, LISTING, lock, STAGES).plan.stage_plans}

    assert stages == {"render": True, "etsy_media": False}


def test_applying_after_a_rename_uploads_nothing(ctx: RunContext, records: BatchRecords) -> None:
    _deployed(ctx)
    assert isinstance(ctx.etsy, FakeEtsyListingClient)
    uploads = len(ctx.etsy.uploads)
    lock = _rename_deployed(ctx, records)

    applied = execute(ctx, build_plan(ctx, LISTING, lock, STAGES), lock)

    assert len(ctx.etsy.uploads) == uploads
    assert set(applied.remote[IMAGE_IDS_KEY].values()) == set(lock.remote[IMAGE_IDS_KEY].values())
    assert not any(p.will_run for p in build_plan(ctx, LISTING, applied, STAGES).plan.stage_plans)
