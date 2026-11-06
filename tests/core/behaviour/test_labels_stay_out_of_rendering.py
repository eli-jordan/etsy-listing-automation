"""A save that changes only labels changes nothing rendered: each state in the
spec's table (*Keeping labels out of rendering*), read through the real engine
and the real calibration save. The preparation queue's two rows are the save
route's, so ``tests/server/behaviour/test_template_labels_api.py`` proves them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from etsy_listings.core.application.mockup_templates import list_templates
from etsy_listings.core.engine.apply import execute
from etsy_listings.core.engine.plan import build_plan
from etsy_listings.core.engine.preview import lookup_preview
from etsy_listings.core.engine.stage import Blocked
from etsy_listings.core.engine.stages import STAGES
from etsy_listings.core.engine.stages.render import RenderDesired, RenderStage, scene_hash
from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.preparation.readiness import template_readiness
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock
from tests.support.marigold import listing_with_marigold

PHOTO_WARP = "flat-lay-01"
PREPARED = "shirt"

LABEL_EDITS = [("cosy",), ("cosy", "shot:flat lay"), ("shot:flat lay",), ()]
"""Adding, adding again, changing and removing, in turn."""


def relabel(workspace: Workspace, template: str, labels: tuple[str, ...], request: int = 0) -> None:
    store = CalibrationStore(workspace)
    saved = store.read(template)
    store.save(
        template,
        saved.config.model_copy(update={"labels": list(labels)}),
        expected_revision=saved.revision,
        request_id=f"labels-{request}-{labels}",
    )


def desired(root: Path) -> RenderDesired:
    resolved = RenderStage().desired(a_context(root), LISTING, None)
    assert not isinstance(resolved, Blocked), resolved
    return resolved


@dataclass(frozen=True)
class Hashes:
    template: dict[str, str]
    scenes: dict[str, str]
    input_hash: str


def hashes(root: Path) -> Hashes:
    current = desired(root)
    review = RenderStage().review_hash(current)
    assert review is not None
    return Hashes(
        dict(current.template_hash),
        {work.key: scene_hash(current, work) for work in current.works},
        review,
    )


@pytest.fixture
def photo_warp(workspace_root: Path) -> tuple[Workspace, str]:
    return Workspace.discover(root_override=workspace_root), PHOTO_WARP


@pytest.fixture
def prepared(workspace_root: Path) -> tuple[Workspace, str]:
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    return workspace, PREPARED


@pytest.fixture(params=["photo_warp", "prepared"])
def scene(request: pytest.FixtureRequest) -> tuple[Workspace, str]:
    return request.getfixturevalue(request.param)


def test_a_template_with_no_labels_hashes_as_its_raw_bytes(workspace_root: Path) -> None:
    """Computed here the way the render stage always did, so nothing
    re-renders when this ships."""
    workspace = Workspace.discover(root_override=workspace_root)
    raw = workspace.template_config_file(PHOTO_WARP).read_bytes()

    assert desired(workspace_root).template_hash[PHOTO_WARP] == (
        f"sha256:{hashlib.sha256(raw).hexdigest()}"
    )


def test_label_edits_leave_the_render_hashes_alone(scene: tuple[Workspace, str]) -> None:
    workspace, template = scene
    before = hashes(workspace.root)

    for step, labels in enumerate(LABEL_EDITS):
        relabel(workspace, template, labels, step)

        assert hashes(workspace.root) == before, labels


def test_label_edits_keep_a_preview_current(scene: tuple[Workspace, str]) -> None:
    workspace, template = scene
    ctx = a_context(workspace.root)
    planned = build_plan(ctx, LISTING, a_lock(), STAGES)
    state = next(s for s in planned.states if s.stage.name == "render")
    assert isinstance(state.stage, RenderStage)
    state.stage.preview(ctx, state.desired, state.live)
    work = next(w for w in state.desired.works if w.template == template)
    assert lookup_preview(ctx, LISTING, template, work.colour).miss is None

    for step, labels in enumerate(LABEL_EDITS):
        relabel(workspace, template, labels, step)

        assert lookup_preview(ctx, LISTING, template, work.colour).miss is None, labels


def test_label_edits_leave_map_readiness_alone(
    prepared: tuple[Workspace, str],
) -> None:
    workspace, template = prepared
    artifacts = Artifacts(workspace)
    inputs = artifacts.saved_inputs(template)
    readiness = template_readiness(workspace, template, workspace.load_template_config(template))
    assert readiness.can_render

    for step, labels in enumerate(LABEL_EDITS):
        relabel(workspace, template, labels, step)

        assert artifacts.saved_inputs(template) == inputs
        config = workspace.load_template_config(template)
        assert template_readiness(workspace, template, config) == readiness


def test_label_edits_leave_the_calibration_status_alone(scene: tuple[Workspace, str]) -> None:
    workspace, template = scene

    def status() -> tuple[str | None, bool]:
        overview = next(t for t in list_templates(workspace) if t.name == template)
        return overview.status_reason, overview.calibrated

    before = status()

    for step, labels in enumerate(LABEL_EDITS):
        relabel(workspace, template, labels, step)

        assert status() == before


def test_plan_reports_no_changes_after_label_edits(scene: tuple[Workspace, str]) -> None:
    workspace, template = scene
    ctx = a_context(workspace.root)
    lock = execute(ctx, build_plan(ctx, LISTING, a_lock(), STAGES), a_lock())
    before = build_plan(ctx, LISTING, lock, STAGES).plan

    for step, labels in enumerate(LABEL_EDITS):
        relabel(workspace, template, labels, step)

        after = build_plan(ctx, LISTING, lock, STAGES).plan
        assert after == before, labels
        render = next(sp for sp in after.stage_plans if sp.stage == "render")
        assert render.will_run is False


# -------------------------------------------------- what the hash still sees


def config_file(root: Path) -> Path:
    return Workspace.discover(root_override=root).template_config_file(PHOTO_WARP)


def template_hash(root: Path) -> str:
    return desired(root).template_hash[PHOTO_WARP]


def test_a_real_edit_to_a_labelled_template_still_moves_the_hash(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    relabel(workspace, PHOTO_WARP, ("cosy",))
    before = template_hash(workspace_root)
    path = config_file(workspace_root)

    path.write_bytes(path.read_bytes().replace(b"opacity: 0.6", b"opacity: 0.7"))

    assert template_hash(workspace_root) != before


def test_a_comment_on_a_labelled_template_still_moves_the_hash(workspace_root: Path) -> None:
    """The narrow exception: only the key goes. An edit a parser would round-
    trip away is still a change, as it is on a file with no labels."""
    workspace = Workspace.discover(root_override=workspace_root)
    relabel(workspace, PHOTO_WARP, ("cosy",))
    before = template_hash(workspace_root)
    path = config_file(workspace_root)

    path.write_bytes(b"# a note\n" + path.read_bytes())

    assert template_hash(workspace_root) != before


@pytest.mark.parametrize(
    "key",
    [
        b"labels: []\n",
        b"labels: [Bad_Label!, 'hand written']\n",
        b"labels:\n- one\n- two\n",
        b"labels:\n  - indented\n",
    ],
    ids=["empty", "flow", "block", "indented"],
)
def test_a_hand_written_labels_key_is_left_out_of_the_hash(
    workspace_root: Path, key: bytes
) -> None:
    path = config_file(workspace_root)
    source = path.read_bytes()
    before = template_hash(workspace_root)

    path.write_bytes(key.replace(b"\n", b"\r\n" if b"\r\n" in source else b"\n") + source)

    assert template_hash(workspace_root) == before


def test_the_word_labels_elsewhere_in_the_file_hashes_as_raw_bytes(workspace_root: Path) -> None:
    path = config_file(workspace_root)
    path.write_bytes(path.read_bytes() + b"# labels: none yet\n")

    assert template_hash(workspace_root) == (
        f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    )


def test_a_key_that_cannot_be_removed_falls_back_to_the_raw_bytes(workspace_root: Path) -> None:
    """Another value shares the label through a YAML alias, so taking the key
    out would leave a dangling alias. A label edit there costs a re-render."""
    path = config_file(workspace_root)
    source = path.read_bytes().replace(b"type: photo-warp", b"type: *shared")
    path.write_bytes(b"labels: [&shared photo-warp]\n" + source)

    assert template_hash(workspace_root) == (
        f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    )


def test_a_labelled_file_that_does_not_parse_blocks_as_any_broken_template(
    workspace_root: Path,
) -> None:
    config_file(workspace_root).write_bytes(b"labels: [unclosed\n")

    blocked = RenderStage().desired(a_context(workspace_root), LISTING, None)

    assert isinstance(blocked, Blocked)
