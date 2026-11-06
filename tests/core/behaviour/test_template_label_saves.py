"""Saving a template's labels through the calibration store: the rules apply
to what is new, and ``template.yaml`` stays the seller's text (spec *Storage*,
*Saving*; ADR-0055). The expected texts are written out by hand, never derived
by dumping."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.template_labels import TemplateLabelRefusedError
from etsy_listings.core.render.config import AnyTemplate
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import (
    CalibrationChangedError,
    CalibrationStore,
)

from tests.support.source_files import crlf

SOURCE = """\
# Shot in the garage, north light.
kind: single
colour: Black   # the only black tee we own
bounding_box:
- {x: 0, y: 0}
- {x: 32, y: 0}
- {x: 32, y: 32}
- {x: 0, y: 32}
renderer:
  type: photo-warp

# Keep this note at the end.
"""

LABELLED = """\
# Shot in the garage, north light.
kind: single
colour: Black   # the only black tee we own
bounding_box:
- {x: 0, y: 0}
- {x: 32, y: 0}
- {x: 32, y: 32}
- {x: 0, y: 32}
renderer:
  type: photo-warp
labels:
- shot:flat lay
- cosy

# Keep this note at the end.
"""

HAND_EDITED = SOURCE.replace(
    "  type: photo-warp\n",
    "  type: photo-warp\nlabels: [Bad_Label!, 'way too long to ever be saved by the app']\n",
)


def a_store(root: Path, source: str | bytes = SOURCE) -> tuple[CalibrationStore, Path]:
    workspace = Workspace.discover(root_override=root)
    workspace.template_dir("example").mkdir(parents=True)
    Image.new("RGB", (32, 32), "white").save(workspace.template_dir("example") / "scene.png")
    path = workspace.template_config_file("example")
    path.write_bytes(source if isinstance(source, bytes) else source.encode("utf-8"))
    return CalibrationStore(workspace), path


def with_labels(config: AnyTemplate, *labels: str) -> AnyTemplate:
    return config.model_copy(update={"labels": list(labels)})


def save_labels(store: CalibrationStore, *labels: str, request_id: str = "labels") -> AnyTemplate:
    saved = store.read("example")
    return store.save(
        "example",
        with_labels(saved.config, *labels),
        expected_revision=saved.revision,
        request_id=request_id,
    ).config


def test_a_new_label_is_saved_tidied(workspace_root: Path) -> None:
    store, _ = a_store(workspace_root)

    assert save_labels(store, "  Shot:Flat   Lay ").labels == ["shot:flat lay"]
    assert store.read("example").config.labels == ["shot:flat lay"]


def test_saving_labels_keeps_the_sellers_comments_and_formatting(workspace_root: Path) -> None:
    store, path = a_store(workspace_root)

    save_labels(store, "shot:flat lay", "cosy")

    assert path.read_text(encoding="utf-8") == LABELLED


def test_saving_labels_keeps_crlf_line_endings(workspace_root: Path) -> None:
    store, path = a_store(workspace_root, crlf(SOURCE).encode("utf-8"))

    save_labels(store, "shot:flat lay", "cosy")

    assert path.read_bytes() == crlf(LABELLED).encode("utf-8")


@pytest.mark.parametrize(
    "source",
    [
        SOURCE.encode("utf-8"),
        crlf(SOURCE).encode("utf-8"),
        SOURCE.removesuffix("\n# Keep this note at the end.\n").encode("utf-8"),
        SOURCE.removesuffix("\n\n# Keep this note at the end.\n").encode("utf-8"),
        crlf(SOURCE.removesuffix("\n\n# Keep this note at the end.\n")).encode("utf-8"),
    ],
    ids=["lf", "crlf", "final-newline", "no-final-newline", "crlf-no-final-newline"],
)
def test_removing_the_last_label_restores_the_file(workspace_root: Path, source: bytes) -> None:
    store, path = a_store(workspace_root, source)
    save_labels(store, "cosy", request_id="add")
    assert path.read_bytes() != source

    save_labels(store, request_id="remove")

    assert path.read_bytes() == source


def test_a_template_with_no_labels_saves_no_key(workspace_root: Path) -> None:
    store, path = a_store(workspace_root)

    save_labels(store)

    assert path.read_text(encoding="utf-8") == SOURCE


def test_a_refused_label_names_the_rule_and_writes_nothing(workspace_root: Path) -> None:
    store, path = a_store(workspace_root)

    with pytest.raises(TemplateLabelRefusedError, match="Use one colon with text on both sides"):
        save_labels(store, "a:b:c")

    assert path.read_text(encoding="utf-8") == SOURCE


def test_a_stale_save_answers_as_stale_before_its_labels_are_read(workspace_root: Path) -> None:
    """The seller's draft is out of date, so reloading comes first: its bad
    label may not even be in the template they reload."""
    store, _ = a_store(workspace_root)
    config = store.read("example").config

    with pytest.raises(CalibrationChangedError):
        store.save(
            "example", with_labels(config, "a:b:c"), expected_revision="old", request_id="stale"
        )


def test_a_retried_save_answers_as_the_first_did(workspace_root: Path) -> None:
    store, _ = a_store(workspace_root)
    before = store.read("example")
    request = with_labels(before.config, "Cosy")

    first = store.save(
        "example", request, expected_revision=before.revision, request_id="same-request"
    )
    retried = store.save(
        "example", request, expected_revision=before.revision, request_id="same-request"
    )

    assert retried.config.labels == ["cosy"]
    assert retried.revision == first.revision


def test_a_hand_edited_label_breaking_the_rules_loads_and_survives_an_unrelated_save(
    workspace_root: Path,
) -> None:
    store, path = a_store(workspace_root, HAND_EDITED)
    saved = store.read("example")
    assert saved.config.labels[0] == "Bad_Label!"
    moved = saved.config.model_copy(update={"colour": "White"})

    store.save("example", moved, expected_revision=saved.revision, request_id="unrelated")

    assert path.read_text(encoding="utf-8") == HAND_EDITED.replace("Black ", "White ")


def test_a_hand_edited_label_does_not_stop_a_new_one_and_can_be_removed(
    workspace_root: Path,
) -> None:
    store, _ = a_store(workspace_root, HAND_EDITED)
    held = store.read("example").config.labels

    assert save_labels(store, *held, "New One", request_id="add").labels == [*held, "new one"]
    assert save_labels(store, "new one", request_id="remove").labels == ["new one"]


def test_labels_that_are_not_a_list_fail_to_load(workspace_root: Path) -> None:
    store, _ = a_store(workspace_root, SOURCE + "labels: cosy\n")

    with pytest.raises(ConfigLoadError, match="labels"):
        store.read("example")


def test_switching_renderer_keeps_labels(workspace_root: Path) -> None:
    """Switching renderer rebuilds the config from its dump."""
    store, _ = a_store(workspace_root)
    save_labels(store, "cosy", request_id="add")
    saved = store.read("example")

    switched = store.select_renderer(
        "example", "marigold", expected_revision=saved.revision, request_id="switch"
    )

    assert switched.config.labels == ["cosy"]


def test_labels_move_the_calibration_revision_and_no_labels_leave_it(workspace_root: Path) -> None:
    """The save fence covers the whole config (spec *Saving*), and a file with
    no labels keeps the revision it had before labels existed."""
    store, _ = a_store(workspace_root)
    unlabelled = store.read("example").revision

    save_labels(store, "cosy", request_id="add")
    assert store.read("example").revision != unlabelled

    save_labels(store, request_id="remove")
    assert store.read("example").revision == unlabelled
