"""Behaviour tests for the calibrator's FastAPI endpoints, run through the real
render pipeline against the fixture workspace's synthetic templates -- no
network, no browser."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace


@pytest.fixture
def client(workspace_root: Path) -> TestClient:
    workspace = Workspace.discover(root_override=workspace_root)
    return TestClient(create_app(workspace))


def test_list_templates_includes_fixture_templates_with_kind(client: TestClient) -> None:
    response = client.get("/api/templates")
    assert response.status_code == 200
    by_name = {t["name"]: t for t in response.json()}
    assert by_name["flat-lay-01"]["kind"] == "colour-matrix"
    assert by_name["colour-chart-01"]["kind"] == "multiple"


def test_list_templates_includes_a_directory_with_no_template_yaml(
    client: TestClient, workspace_root: Path
) -> None:
    """The calibrator is what writes template.yaml, so an uncalibrated
    directory has to be listable -- otherwise there is no way to select it and
    calibrate it."""
    (workspace_root / "mockup-templates" / "not-calibrated-yet").mkdir()
    by_name = {t["name"]: t for t in client.get("/api/templates").json()}
    assert by_name["not-calibrated-yet"] == {
        "name": "not-calibrated-yet",
        "kind": None,
        "colours": [],
        "has_config": False,
        "status": "needs-calibration",
        "status_reason": "no kind set",
    }


class TestCalibrationStatus:
    """The rail sorts uncalibrated templates to the top and explains why each
    one is not done, so `status` has to be *derived* -- there is no
    `calibrated:` flag in template.yaml and deliberately so, since that would
    be new persisted product state the PRD has not agreed. Everything here is
    computed from what the config already says.
    """

    def _status(self, client: TestClient, name: str) -> tuple[str, str | None]:
        by_name = {t["name"]: t for t in client.get("/api/templates").json()}
        return by_name[name]["status"], by_name[name]["status_reason"]

    def test_a_fully_configured_colour_matrix_is_calibrated(self, client: TestClient) -> None:
        assert self._status(client, "flat-lay-01") == ("calibrated", None)

    def test_a_multiple_with_every_box_coloured_is_calibrated(self, client: TestClient) -> None:
        assert self._status(client, "colour-chart-01") == ("calibrated", None)

    def test_a_directory_with_no_config_needs_a_kind(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        (workspace_root / "mockup-templates" / "fresh-upload").mkdir()
        assert self._status(client, "fresh-upload") == ("needs-calibration", "no kind set")

    def test_a_multiple_with_no_placements_needs_boxes(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """`MultipleTemplate(placements=[])` is exactly what an upload writes,
        so this is the state every fresh chart starts in."""
        config = client.get("/api/templates/colour-chart-01/config").json()
        config["placements"] = []
        client.put("/api/templates/colour-chart-01/config", json=config)
        assert self._status(client, "colour-chart-01") == ("needs-calibration", "no boxes")

    def test_a_multiple_with_an_uncoloured_box_says_how_many(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """Wireframe 2a: "1 box has no colour -- can't mark calibrated yet".
        The count matters; "some boxes" would not tell you when you were done."""
        config = client.get("/api/templates/colour-chart-01/config").json()
        config["placements"][0]["colour"] = ""
        client.put("/api/templates/colour-chart-01/config", json=config)
        assert self._status(client, "colour-chart-01") == (
            "needs-calibration",
            "1 box has no colour",
        )

    def test_the_uncoloured_box_count_is_plural_aware(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        config = client.get("/api/templates/colour-chart-01/config").json()
        for placement in config["placements"]:
            placement["colour"] = ""
        client.put("/api/templates/colour-chart-01/config", json=config)
        status, reason = self._status(client, "colour-chart-01")
        assert status == "needs-calibration"
        assert reason == "2 boxes have no colour"


class TestThumbnails:
    """The rail shows a photo per template. Rendering a full preview for each
    would mean running the real pipeline once per row on every page load; a
    thumbnail is the template's own scene photo, downscaled."""

    def test_thumbnail_returns_a_png_for_a_colour_matrix_template(self, client: TestClient) -> None:
        response = client.get("/api/templates/flat-lay-01/thumbnail")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG\r\n\x1a\n")

    def test_thumbnail_returns_a_png_for_a_scene_template(self, client: TestClient) -> None:
        response = client.get("/api/templates/colour-chart-01/thumbnail")
        assert response.status_code == 200
        assert response.content.startswith(b"\x89PNG\r\n\x1a\n")

    def test_thumbnail_is_much_smaller_than_the_source_photo(self, client: TestClient) -> None:
        """The point is the rail staying cheap -- a full-size photo per row
        would defeat it."""
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(client.get("/api/templates/flat-lay-01/thumbnail").content)) as img:
            assert max(img.size) <= 160

    def test_thumbnail_404s_for_a_template_with_no_photo(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        (workspace_root / "mockup-templates" / "photoless").mkdir()
        assert client.get("/api/templates/photoless/thumbnail").status_code == 404

    def test_thumbnail_rejects_a_name_that_escapes_the_workspace(self, client: TestClient) -> None:
        """Template names arrive from the URL, so this endpoint goes through
        the workspace accessors like every other one (A8)."""
        response = client.get("/api/templates/..%2F..%2Fetc/thumbnail")
        assert response.status_code in (400, 404)


class TestDesignLibrary:
    """A16: the test design is a library, not a fixed literal. The grid target
    answers "is the warp right?" and says nothing about how a real ink weight
    sits on a real garment, so the set has to be open."""

    def _png_bytes(self) -> bytes:
        from io import BytesIO

        from PIL import Image

        buffer = BytesIO()
        Image.new("RGBA", (64, 64), (200, 60, 60, 255)).save(buffer, format="PNG")
        return buffer.getvalue()

    def test_lists_the_bundled_designs_with_labels(self, client: TestClient) -> None:
        response = client.get("/api/designs")
        assert response.status_code == 200
        by_id = {d["id"]: d for d in response.json()}
        assert by_id["bundled-grid"]["label"] == "Grid / ruler target"
        assert by_id["bundled-on-light"]["label"] == "Sample art · light ink"
        assert by_id["bundled-on-dark"]["label"] == "Sample art · dark ink"
        assert {d["source"] for d in response.json()} == {"bundled"}

    def test_an_uploaded_design_joins_the_library(self, client: TestClient) -> None:
        upload = client.post(
            "/api/designs",
            files={"file": ("my-artwork.png", self._png_bytes(), "image/png")},
        )
        assert upload.status_code == 200
        assert upload.json()["id"] == "my-artwork"

        by_id = {d["id"]: d for d in client.get("/api/designs").json()}
        assert by_id["my-artwork"]["source"] == "upload"

    def test_an_uploaded_design_lands_in_the_workspace_not_the_repo(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        client.post(
            "/api/designs", files={"file": ("my-artwork.png", self._png_bytes(), "image/png")}
        )
        assert (workspace_root / "test-designs" / "my-artwork.png").is_file()

    def test_an_uploaded_design_can_be_previewed_through_the_real_renderer(
        self, client: TestClient
    ) -> None:
        client.post(
            "/api/designs", files={"file": ("my-artwork.png", self._png_bytes(), "image/png")}
        )
        config = client.get("/api/templates/flat-lay-01/config").json()
        response = client.post(
            "/api/templates/flat-lay-01/preview",
            json={**config, "colour": "black", "design": "my-artwork"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

    def test_an_unknown_design_is_a_400_not_a_crash(self, client: TestClient) -> None:
        """The id now comes from a list the client fetched, so a stale one is a
        client error rather than a KeyError escaping as a 500."""
        config = client.get("/api/templates/flat-lay-01/config").json()
        response = client.post(
            "/api/templates/flat-lay-01/preview",
            json={**config, "colour": "black", "design": "no-such-design"},
        )
        assert response.status_code == 400
        assert "no-such-design" in response.json()["detail"]

    def test_upload_rejects_a_name_that_escapes_the_workspace(self, client: TestClient) -> None:
        response = client.post(
            "/api/designs",
            files={"file": ("../../evil.png", self._png_bytes(), "image/png")},
        )
        assert response.status_code == 400

    def test_upload_rejects_a_file_that_is_not_an_image(self, client: TestClient) -> None:
        response = client.post(
            "/api/designs", files={"file": ("notes.txt", b"not a png", "text/plain")}
        )
        assert response.status_code == 400


def _png(colour: tuple[int, int, int] = (200, 60, 60)) -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (64, 80), colour).save(buffer, format="PNG")
    return buffer.getvalue()


class TestKindChosenAfterUpload:
    """Wireframe 2a asks what kind a template is *after* the photos are in,
    as the first calibration step, instead of demanding it at upload. You can
    see the photos by then, which is the only way the question is answerable
    for a set someone else assembled.
    """

    def _upload(self, client: TestClient, name: str, files: list[tuple[str, bytes]]):  # noqa: ANN202
        return client.post(
            "/api/templates",
            params={"name": name},
            files=[("files", (filename, data, "image/png")) for filename, data in files],
        )

    def test_upload_without_a_kind_stores_the_photos_and_no_config(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        response = self._upload(client, "fresh", [("black.png", _png()), ("ivory.png", _png())])
        assert response.status_code == 200
        assert response.json()["kind"] is None

        directory = workspace_root / "mockup-templates" / "fresh"
        assert sorted(p.name for p in directory.glob("*.png")) == ["black.png", "ivory.png"]
        assert not (directory / "template.yaml").exists()

    def test_such_a_template_is_listed_as_needing_a_kind(self, client: TestClient) -> None:
        self._upload(client, "fresh", [("black.png", _png())])
        by_name = {t["name"]: t for t in client.get("/api/templates").json()}
        assert by_name["fresh"]["status_reason"] == "no kind set"

    def test_assigning_colour_matrix_writes_a_config_with_a_starting_box(
        self, client: TestClient
    ) -> None:
        self._upload(client, "fresh", [("black.png", _png()), ("ivory.png", _png())])
        response = client.post("/api/templates/fresh/kind", json={"kind": "colour-matrix"})
        assert response.status_code == 200

        config = client.get("/api/templates/fresh/config").json()
        assert config["kind"] == "colour-matrix"
        assert len(config["bounding_box"]) == 4

    def test_assigning_colour_matrix_leaves_the_photos_named_as_colours(
        self, client: TestClient
    ) -> None:
        """PRD 7a: the filename *is* the colour, so nothing is renamed."""
        self._upload(client, "fresh", [("black.png", _png()), ("ivory.png", _png())])
        client.post("/api/templates/fresh/kind", json={"kind": "colour-matrix"})
        by_name = {t["name"]: t for t in client.get("/api/templates").json()}
        assert by_name["fresh"]["colours"] == ["black", "ivory"]

    def test_assigning_single_renames_the_lone_photo_to_the_scene(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """PRD 28: multiple/single kinds use a fixed scene.png -- there is no
        per-colour photo to name."""
        self._upload(client, "fresh", [("some-shot.png", _png())])
        assert client.post("/api/templates/fresh/kind", json={"kind": "single"}).status_code == 200

        directory = workspace_root / "mockup-templates" / "fresh"
        assert (directory / "scene.png").is_file()
        assert not (directory / "some-shot.png").exists()

    def test_assigning_multiple_starts_with_no_boxes(self, client: TestClient) -> None:
        self._upload(client, "fresh", [("chart.png", _png())])
        client.post("/api/templates/fresh/kind", json={"kind": "multiple"})
        assert client.get("/api/templates/fresh/config").json()["placements"] == []
        by_name = {t["name"]: t for t in client.get("/api/templates").json()}
        assert by_name["fresh"]["status_reason"] == "no boxes"

    def test_a_scene_kind_refuses_a_set_of_photos(self, client: TestClient) -> None:
        """One photo, one scene -- picking `single` for a four-photo colour set
        is a mistake worth reporting rather than silently keeping one."""
        self._upload(client, "fresh", [("a.png", _png()), ("b.png", _png())])
        response = client.post("/api/templates/fresh/kind", json={"kind": "single"})
        assert response.status_code == 400
        assert "one photo" in response.json()["detail"]

    def test_assigning_a_kind_to_an_already_configured_template_is_refused(
        self, client: TestClient
    ) -> None:
        """Changing kind would silently discard the calibration already done
        in the old shape's fields."""
        response = client.post("/api/templates/flat-lay-01/kind", json={"kind": "single"})
        assert response.status_code == 409

    def test_assigning_a_kind_to_an_unknown_template_404s(self, client: TestClient) -> None:
        assert client.post("/api/templates/nope/kind", json={"kind": "single"}).status_code == 404


class TestColourReport:
    """The kind picker shows what colour each photo will be taken as, before
    committing to `colour-matrix`. PRD 7a makes the filename the source of
    truth, so this only *reports* that rule -- there is no manual mapping.
    """

    def test_reports_the_colour_each_filename_yields(self, client: TestClient) -> None:
        response = client.get("/api/templates/flat-lay-01/colour-report")
        assert response.status_code == 200
        assert response.json() == [
            {"filename": "black.png", "colour": "black", "clean": True},
            {"filename": "blue-jean.png", "colour": "blue-jean", "clean": True},
            {"filename": "ivory.png", "colour": "ivory", "clean": True},
            {"filename": "moss.png", "colour": "moss", "clean": True},
        ]

    def test_flags_a_filename_that_is_not_already_a_slug(
        self, client: TestClient, workspace_root: Path
    ) -> None:
        """`Heather Grey.png` still yields a colour, but not the one on disk --
        the calibrator says so rather than quietly renaming the user's file."""
        (workspace_root / "mockup-templates" / "flat-lay-01" / "Heather Grey.png").write_bytes(
            _png()
        )
        by_filename = {
            row["filename"]: row
            for row in client.get("/api/templates/flat-lay-01/colour-report").json()
        }
        assert by_filename["Heather Grey.png"] == {
            "filename": "Heather Grey.png",
            "colour": "heather-grey",
            "clean": False,
        }

    def test_excludes_the_scene_photo(self, client: TestClient) -> None:
        """A scene is not a colour (PRD 28)."""
        rows = client.get("/api/templates/colour-chart-01/colour-report").json()
        assert all(row["filename"] != "scene.png" for row in rows)

    def test_404s_for_an_unknown_template(self, client: TestClient) -> None:
        assert client.get("/api/templates/nope/colour-report").status_code == 404


def test_get_config_returns_the_fixture_bounding_box(client: TestClient) -> None:
    response = client.get("/api/templates/flat-lay-01/config")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "colour-matrix"
    assert len(body["bounding_box"]) == 4
    assert set(body["bounding_box"][0]) == {"x", "y"}
    assert body["shade"]["enabled"] is True


def test_get_config_404s_for_unknown_template(client: TestClient) -> None:
    response = client.get("/api/templates/does-not-exist/config")
    assert response.status_code == 404


def test_put_config_updates_the_bounding_box(client: TestClient) -> None:
    current = client.get("/api/templates/flat-lay-01/config").json()
    new_box = [{"x": 10, "y": 10}, {"x": 200, "y": 10}, {"x": 200, "y": 200}, {"x": 10, "y": 200}]
    current["bounding_box"] = new_box

    put_response = client.put("/api/templates/flat-lay-01/config", json=current)
    assert put_response.status_code == 200
    assert put_response.json()["bounding_box"] == new_box

    get_response = client.get("/api/templates/flat-lay-01/config")
    assert get_response.json()["bounding_box"] == new_box


def test_preview_renders_a_real_png_through_the_renderer_for_colour_matrix(
    client: TestClient,
) -> None:
    config = client.get("/api/templates/flat-lay-01/config").json()
    response = client.post(
        "/api/templates/flat-lay-01/preview",
        json={"colour": "black", **config},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes


def test_preview_unknown_colour_404s(client: TestClient) -> None:
    config = client.get("/api/templates/flat-lay-01/config").json()
    response = client.post(
        "/api/templates/flat-lay-01/preview",
        json={"colour": "not-a-real-colour", **config},
    )
    assert response.status_code == 404


def test_preview_renders_the_full_composite_for_multiple_kind(client: TestClient) -> None:
    config = client.get("/api/templates/colour-chart-01/config").json()
    assert len(config["placements"]) == 2
    response = client.post("/api/templates/colour-chart-01/preview", json=config)
    assert response.status_code == 200
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_wrong_body_shape_for_kind_is_rejected(client: TestClient) -> None:
    """Posting a colour-matrix-shaped body at a multiple-kind template is a
    client error, not silently mis-rendered."""
    response = client.post(
        "/api/templates/colour-chart-01/preview",
        json={
            "colour": "black",
            "bounding_box": [
                {"x": 0, "y": 0},
                {"x": 100, "y": 0},
                {"x": 100, "y": 100},
                {"x": 0, "y": 100},
            ],
        },
    )
    assert response.status_code in (400, 422)


def test_upload_colour_matrix_creates_a_new_template_with_default_config(
    client: TestClient, tmp_path: Path
) -> None:
    from PIL import Image

    image_path = tmp_path / "teal.png"
    Image.new("RGB", (200, 240), (10, 100, 120)).save(image_path)

    with image_path.open("rb") as f:
        response = client.post(
            "/api/templates",
            params={"name": "brand-new-template", "kind": "colour-matrix"},
            files=[("files", ("teal.png", f, "image/png"))],
        )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "brand-new-template"
    assert body["kind"] == "colour-matrix"
    assert body["colours"] == ["teal"]

    config_response = client.get("/api/templates/brand-new-template/config")
    assert config_response.status_code == 200
    assert config_response.json()["kind"] == "colour-matrix"


def test_upload_single_kind_saves_scene_png_regardless_of_uploaded_filename(
    client: TestClient, tmp_path: Path
) -> None:
    from PIL import Image

    image_path = tmp_path / "lifestyle-shot.png"
    Image.new("RGB", (200, 240), (10, 100, 120)).save(image_path)

    with image_path.open("rb") as f:
        response = client.post(
            "/api/templates",
            params={"name": "lifestyle-01", "kind": "single"},
            files=[("files", ("lifestyle-shot.png", f, "image/png"))],
        )
    assert response.status_code == 200
    assert response.json()["kind"] == "single"

    config_response = client.get("/api/templates/lifestyle-01/config")
    assert config_response.json()["kind"] == "single"


def test_upload_multiple_kind_rejects_more_than_one_file(
    client: TestClient, tmp_path: Path
) -> None:
    from PIL import Image

    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.new("RGB", (100, 100), (0, 0, 0)).save(a)
    Image.new("RGB", (100, 100), (0, 0, 0)).save(b)

    with a.open("rb") as fa, b.open("rb") as fb:
        response = client.post(
            "/api/templates",
            params={"name": "two-photo-chart", "kind": "multiple"},
            files=[("files", ("a.png", fa, "image/png")), ("files", ("b.png", fb, "image/png"))],
        )
    assert response.status_code == 400


def test_traversal_template_name_is_rejected_not_resolved(client: TestClient) -> None:
    """Template names arrive from the URL. They go through the workspace's
    layout accessors, so a traversal attempt is refused by the same rule that
    guards every other path (A8) rather than by a check local to the web layer."""
    response = client.get("/api/templates/..%2F..%2Fetc/config")
    assert response.status_code in (400, 404)
    assert "shop.yaml" not in response.text


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
