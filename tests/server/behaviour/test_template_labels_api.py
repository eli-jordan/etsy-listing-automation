"""Labels over the calibrator's save route: they travel in the ordinary config
save, its refusals reach the seller, and a save that changes only labels queues
no preparation work (spec *Saving*, *Refusals*, and the table in *Keeping labels
out of rendering*). Every template here goes through the real queue."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from etsy_listings.core.render.positions import Pose, compose
from etsy_listings.core.workspace.template_state import template_state
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.builders import edit_listing
from tests.support.marigold import (
    PreparationRuntime,
    covered_small_print,
    listing_with_prepared_marigold,
)

COLON = "Use one colon with text on both sides, like theme:christmas"


def config_url(template: str) -> str:
    return f"/api/templates/{template}/config"


def put_config(
    client: TestClient, template: str, request_id: str = "save", **changes: Any
) -> Response:
    loaded = client.get(config_url(template))
    assert loaded.status_code == 200, loaded.text
    mask_edits = changes.pop("mask_edits", [])
    return client.put(
        config_url(template),
        headers={"If-Match": loaded.headers["etag"]},
        json={
            "request_id": request_id,
            "config": {**loaded.json(), **changes},
            "mask_edits": mask_edits,
        },
    )


def summary(client: TestClient, template: str) -> dict[str, Any]:
    return next(t for t in client.get("/api/templates").json() if t["name"] == template)


@pytest.fixture
def client(workspace_root: Path) -> TestClient:
    return TestClient(create_app(Workspace.discover(root_override=workspace_root)))


def test_a_template_with_no_labels_answers_an_empty_list(client: TestClient) -> None:
    assert summary(client, "flat-lay-01")["labels"] == []
    assert client.get(config_url("flat-lay-01")).json()["labels"] == []


def test_an_uncalibrated_template_answers_an_empty_list(
    client: TestClient, workspace_root: Path
) -> None:
    (workspace_root / "mockup-templates" / "not-calibrated-yet").mkdir()

    assert summary(client, "not-calibrated-yet")["labels"] == []


def test_a_saved_label_comes_back_tidied_on_every_read(client: TestClient) -> None:
    saved = put_config(client, "flat-lay-01", labels=["  Theme:Christmas ", "theme:christmas"])

    assert saved.status_code == 200, saved.text
    assert saved.json()["labels"] == ["theme:christmas"]
    assert client.get(config_url("flat-lay-01")).json()["labels"] == ["theme:christmas"]
    assert summary(client, "flat-lay-01")["labels"] == ["theme:christmas"]


def test_a_label_breaking_a_rule_is_a_422_naming_it(client: TestClient) -> None:
    refused = put_config(client, "flat-lay-01", labels=["theme:"])

    assert refused.status_code == 422
    assert refused.json() == {"detail": COLON}
    assert client.get(config_url("flat-lay-01")).json()["labels"] == []


def test_a_stale_label_save_is_a_412(client: TestClient) -> None:
    loaded = client.get(config_url("flat-lay-01"))
    assert put_config(client, "flat-lay-01", "first", labels=["cosy"]).status_code == 200

    stale = client.put(
        config_url("flat-lay-01"),
        headers={"If-Match": loaded.headers["etag"]},
        json={"request_id": "second", "config": {**loaded.json(), "labels": ["warm"]}},
    )

    assert stale.status_code == 412


def test_labels_that_are_not_strings_are_a_422(client: TestClient) -> None:
    assert put_config(client, "flat-lay-01", labels=[7]).status_code == 422


def test_labels_move_with_a_template_rename(client: TestClient) -> None:
    assert put_config(client, "flat-lay-01", labels=["cosy"]).status_code == 200

    renamed = client.post("/api/templates/flat-lay-01/rename", json={"new_name": "flat-lay-02"})

    assert renamed.status_code == 200, renamed.text
    assert summary(client, "flat-lay-02")["labels"] == ["cosy"]


def test_a_preview_takes_a_labelled_config_as_the_client_spreads_it(client: TestClient) -> None:
    assert put_config(client, "flat-lay-01", labels=["cosy"]).status_code == 200
    config = client.get(config_url("flat-lay-01")).json()

    response = client.post("/api/templates/flat-lay-01/preview", json={**config, "colour": "black"})

    assert response.status_code == 200, response.text


# ---------------------------------------------------------- the preparation queue


def jobs(app: FastAPI) -> list[tuple[str, str, str]]:
    return [(job.id, job.kind, job.phase) for job in app.state.preparations.list_jobs()]


def queued_kinds(app: FastAPI) -> list[str]:
    return [kind for _, kind, phase in jobs(app) if phase == "queued"]


def position(workspace: Workspace, template: str) -> None:
    box = compose(template_state(workspace, template).require().bounding_box, Pose(rotation=5))
    edit_listing(
        workspace.root,
        media=[{"template": template}],
        template_positions={template: {"bounding_box": [p.model_dump() for p in box]}},
    )


def prepared(root: Path) -> tuple[Workspace, str]:
    return listing_with_prepared_marigold(root), "shirt"


def positioned_and_covered(root: Path) -> tuple[Workspace, str]:
    workspace = covered_small_print(root)
    position(workspace, "tee")
    return workspace, "tee"


def positioned_short_of_coverage(root: Path) -> tuple[Workspace, str]:
    """Wider limits than its evidence reaches, and no job waiting: saving this
    template's geometry would queue coverage, but a label is not the explicit
    request that inference needs (ADR-0058)."""
    workspace, template = positioned_and_covered(root)
    limits = {"scale": {"max": 1.25}, "rotation": 25}
    workspace.settings_file().write_text(
        yaml.safe_dump({"template_positions": limits}), encoding="utf-8"
    )
    return workspace, template


def prepared_with_stale_maps(root: Path) -> tuple[Workspace, str]:
    """A hand edit moved the box, so a save would rebuild the maps from the
    evidence still in hand."""
    workspace, template = prepared(root)
    path = workspace.template_config_file(template)
    path.write_bytes(path.read_bytes().replace(b"x: 51", b"x: 50"))
    return workspace, template


@pytest.mark.parametrize(
    "arrange",
    [prepared, positioned_and_covered, positioned_short_of_coverage, prepared_with_stale_maps],
)
@pytest.mark.parametrize("labels", [["cosy"], ["cosy", "shot:flat lay"]], ids=["one", "two"])
def test_a_label_save_queues_nothing(workspace_root: Path, arrange, labels: list[str]) -> None:
    workspace, template = arrange(workspace_root)
    app = create_app(workspace, preparation_runtime=PreparationRuntime())
    client = TestClient(app)
    before = jobs(app)

    added = put_config(client, template, "add", labels=labels)
    removed = put_config(client, template, "remove", labels=[])

    assert (added.status_code, removed.status_code) == (200, 200), added.text
    assert jobs(app) == before


def moved(config: dict[str, Any]) -> list[dict[str, float]]:
    return [{"x": p["x"] + 14, "y": p["y"] + 14} for p in config["bounding_box"]]


def test_a_label_sharing_a_save_with_geometry_still_queues_its_work(workspace_root: Path) -> None:
    """Quick edits land together (spec *Saving*): the gate is on what the save
    changed, not on whether it carried a label."""
    workspace, template = positioned_and_covered(workspace_root)
    app = create_app(workspace, preparation_runtime=PreparationRuntime())
    client = TestClient(app)
    config = client.get(config_url(template)).json()

    saved = put_config(client, template, labels=["cosy"], bounding_box=moved(config))

    assert saved.status_code == 200, saved.text
    assert "coverage" in queued_kinds(app)


def test_a_save_with_no_change_still_reconciles_as_it_always_did(workspace_root: Path) -> None:
    """Only a label edit is exempt: the editor's Approve saves an unchanged draft."""
    workspace, template = positioned_short_of_coverage(workspace_root)
    app = create_app(workspace, preparation_runtime=PreparationRuntime())

    saved = put_config(TestClient(app), template)

    assert saved.status_code == 200, saved.text
    assert queued_kinds(app) == ["coverage"]


def test_a_label_save_is_allowed_while_a_preparation_job_waits(workspace_root: Path) -> None:
    """It cannot change what the job is doing (spec *Refusals*), and the job
    keeps its place."""
    workspace, template = positioned_short_of_coverage(workspace_root)
    app = create_app(workspace, preparation_runtime=PreparationRuntime())
    client = TestClient(app)
    assert put_config(client, template, "retry").status_code == 200
    assert queued_kinds(app) == ["coverage"]
    waiting = jobs(app)

    saved = put_config(client, template, "label", labels=["cosy"])

    assert saved.status_code == 200, saved.text
    assert jobs(app) == waiting


def editor_preview(client: TestClient, template: str, body: dict[str, Any]) -> Response:
    return client.post(f"/api/templates/{template}/preview?scale=editor", json=body)


def test_an_editor_preview_outlives_a_label_save(workspace_root: Path) -> None:
    """A preview names the revision its draft was read at, with that revision's
    labels. A label save moves the revision but nothing a preview draws, so the
    frame on screen, and one in flight as the save lands, stays good."""
    workspace, template = prepared(workspace_root)
    with TestClient(create_app(workspace, preparation_runtime=PreparationRuntime())) as client:
        loaded = client.get(config_url(template))
        body = {**loaded.json(), "calibration_revision": loaded.headers["etag"].strip('"')}
        before = editor_preview(client, template, body)
        assert before.status_code == 200, before.text

        assert put_config(client, template, "one", labels=["cosy"]).status_code == 200
        assert put_config(client, template, "two", labels=["cosy", "warm"]).status_code == 200

        after = editor_preview(client, template, body)
        assert after.status_code == 200, after.text
        assert after.content == before.content


def test_an_editor_preview_is_still_refused_after_any_other_save(workspace_root: Path) -> None:
    workspace, template = prepared(workspace_root)
    with TestClient(create_app(workspace, preparation_runtime=PreparationRuntime())) as client:
        loaded = client.get(config_url(template))
        body = {**loaded.json(), "calibration_revision": loaded.headers["etag"].strip('"')}

        saved = put_config(client, template, bounding_box=moved(loaded.json()), labels=["cosy"])
        assert saved.status_code == 200, saved.text

        assert editor_preview(client, template, body).status_code == 409


def test_an_editor_preview_naming_labels_its_revision_never_held_is_refused(
    workspace_root: Path,
) -> None:
    workspace, template = prepared(workspace_root)
    with TestClient(create_app(workspace, preparation_runtime=PreparationRuntime())) as client:
        loaded = client.get(config_url(template))
        body = {
            **loaded.json(),
            "labels": ["never held"],
            "calibration_revision": loaded.headers["etag"].strip('"'),
        }

        assert put_config(client, template, labels=["cosy"]).status_code == 200

        assert editor_preview(client, template, body).status_code == 409
