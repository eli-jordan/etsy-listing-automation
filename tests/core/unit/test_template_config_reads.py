"""A template's state: what each one reads as, what a caller gets from it, and
that reads stay fresh and isolated when parsing is reused."""

import os
from contextlib import suppress

import pytest

from etsy_listings.core.errors import ConflictError, MissingError, UserFacingError
from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.preparation.readiness import saved_preparation_facts
from etsy_listings.core.render import MultipleTemplate
from etsy_listings.core.workspace.calibration import CalibrationStore
from etsy_listings.core.workspace.template_state import (
    CalibrationRepairRequiredError,
    TemplateAbsent,
    TemplateConfigMissingError,
    TemplateConfigUnreadableError,
    TemplateLoaded,
    TemplateNeedsRepair,
    TemplateUnreadable,
    template_state,
)
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.marigold import interrupted_save, marigold_template


@pytest.mark.parametrize("padding", [0, 70_000])
def test_repeated_reads_do_not_share_mutable_placement_lists(workspace_root, padding):
    workspace = marigold_template(workspace_root, "multiple")
    if padding:
        path = workspace.template_config_file("shirt")
        path.write_text(
            "#" + "x" * padding + chr(10) + path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    first = template_state(workspace, "shirt").require()
    assert isinstance(first, MultipleTemplate)
    count = len(first.placements)
    first.placements.pop()
    second = template_state(workspace, "shirt").require()
    assert isinstance(second, MultipleTemplate)
    assert len(second.placements) == count


def test_same_size_same_mtime_external_edit_is_read_and_invalidity_keeps_its_path(workspace_root):
    workspace = marigold_template(workspace_root)
    path = workspace.template_config_file("shirt")
    original = path.read_text(encoding="utf-8")
    initial = template_state(workspace, "shirt").require()
    stamp = path.stat()
    changed = original.replace("fabric_texture: 0.25", "fabric_texture: 0.75")
    assert changed != original
    assert len(changed) == len(original)
    path.write_text(changed, encoding="utf-8")
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    current = template_state(workspace, "shirt").require()
    assert current != initial
    assert current.renderer.config.appearance.fabric_texture == 0.75
    path.write_text(chr(10).join(["kind: single", "renderer: invalid"]), encoding="utf-8")
    state = template_state(workspace, "shirt")
    assert isinstance(state, TemplateUnreadable)
    assert str(path) in state.reason


def test_a_loaded_template_has_a_config_and_no_reason(workspace_root):
    workspace = marigold_template(workspace_root)

    state = template_state(workspace, "shirt")

    assert isinstance(state, TemplateLoaded)
    assert state.config == state.require()
    assert state.reason is None


def test_a_folder_with_no_file_is_absent_and_requiring_it_is_a_missing_refusal(workspace_root):
    workspace = Workspace.discover(root_override=workspace_root)
    workspace.template_dir("fresh").mkdir()

    state = template_state(workspace, "fresh")

    assert isinstance(state, TemplateAbsent)
    assert state.config is None
    assert "no template.yaml for 'fresh'" in state.reason
    with pytest.raises(TemplateConfigMissingError) as refused:
        state.require()
    assert isinstance(refused.value, MissingError)


@pytest.mark.parametrize(
    ("content", "says"),
    [
        (b"kind: [unclosed", "not valid YAML"),
        (b"kind: single\nrenderer: invalid\n", "invalid configuration"),
        (b"", "invalid configuration"),
        (b"\xff\xfe not utf-8", "cannot be read"),
    ],
)
def test_a_file_that_will_not_load_is_unreadable_naming_it(workspace_root, content, says):
    """A hand edit makes these, and callers that skip an unloadable template
    must not meet a bare parser error."""
    workspace = marigold_template(workspace_root)
    path = workspace.template_config_file("shirt")
    path.write_bytes(content)

    state = template_state(workspace, "shirt")

    assert isinstance(state, TemplateUnreadable)
    assert state.config is None
    assert str(path) in state.reason
    assert says in state.reason
    with pytest.raises(TemplateConfigUnreadableError, match=says) as refused:
        state.require()
    assert isinstance(refused.value, ConflictError)


def test_the_observer_reads_a_transaction_as_needing_repair_and_leaves_it(workspace_root):
    """The CLI's refusal: the transaction may be a live server save."""
    workspace = marigold_template(workspace_root)
    transaction = interrupted_save(workspace)

    state = template_state(workspace, "shirt")

    assert isinstance(state, TemplateNeedsRepair)
    assert transaction.exists()
    with pytest.raises(CalibrationRepairRequiredError, match="retry after server recovery"):
        state.require()


def test_the_owner_rolls_an_interrupted_transaction_forward(workspace_root):
    workspace = marigold_template(workspace_root)
    transaction = interrupted_save(workspace)

    state = CalibrationStore(workspace).state("shirt")

    assert isinstance(state, TemplateLoaded)
    assert not transaction.exists()


def test_the_owner_reads_a_transaction_it_cannot_trust_as_needing_repair(workspace_root):
    workspace = marigold_template(workspace_root)
    transaction = interrupted_save(workspace)
    (transaction / "payload-0").write_bytes(b"corrupted")

    state = CalibrationStore(workspace).state("shirt")

    assert isinstance(state, TemplateNeedsRepair)
    assert "repair" in state.reason
    assert transaction.exists()


def _prepared_inputs(workspace: Workspace) -> object:
    return Artifacts(workspace).saved_inputs("shirt")


def _saved_facts(workspace: Workspace) -> object:
    return saved_preparation_facts(workspace, "shirt")


def _saved_mask(workspace: Workspace) -> object:
    return CalibrationStore(workspace).mask("shirt")


@pytest.mark.parametrize("read", [_prepared_inputs, _saved_facts, _saved_mask])
def test_what_the_engine_reads_never_finishes_a_transaction(workspace_root, read):
    """``plan`` reaches these from the CLI, where the transaction may be a live
    server save: they refuse or report it, and it stays."""
    workspace = marigold_template(workspace_root)
    transaction = interrupted_save(workspace)

    with suppress(UserFacingError):
        read(workspace)

    assert transaction.exists()
