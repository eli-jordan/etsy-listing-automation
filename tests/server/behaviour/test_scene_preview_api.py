"""``GET /api/listings/{name}/scene-preview`` (A35, multi-artwork plan PR 2):
a listing's scene, rendered with each layer's artwork resolved from the
*saved* listing -- the picture the Variants stage and Listing Images show.

The expected image is composed here from render primitives and the file the
test names for each colour, never by asking the resolver: a test that
resolved through ``config/artwork.py`` to check an endpoint that resolves
through ``config/artwork.py`` would agree with any bug in it.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image

from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app
from etsy_listings.server.api.imagecache import LIVE_ARTWORK_EDGE

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_garment_profile, edit_listing
from tests.support.scenes import expected_scene

PROFILE = "comfort-colors-1717"


def _design(root: Path, name: str, rgb: tuple[int, int, int]) -> str:
    path = root / "designs" / f"{name}.png"
    Image.new("RGBA", (240, 300), (*rgb, 255)).save(path)
    return f"designs/{name}.png"


@pytest.fixture
def client(workspace_root: Path) -> TestClient:
    return TestClient(create_app(Workspace.discover(root_override=workspace_root)))


def _get(client: TestClient, **params: str) -> bytes:
    response = client.get(f"/api/listings/{LISTING}/scene-preview", params=params)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    return response.content


class TestResolvesFromTheSavedListing:
    def test_a_colour_prints_its_tone_slot(self, workspace_root: Path, client: TestClient) -> None:
        light, dark = (
            _design(workspace_root, "dark-ink", (200, 30, 30)),
            _design(workspace_root, "light-ink", (30, 30, 200)),
        )
        edit_listing(workspace_root, design={"on-light": light, "on-dark": dark})

        ivory = _get(client, template="flat-lay-01", colour="ivory")
        black = _get(client, template="flat-lay-01", colour="black")

        assert ivory == expected_scene(workspace_root, "flat-lay-01", "ivory", {"ivory": light})
        assert black == expected_scene(workspace_root, "flat-lay-01", "black", {"black": dark})

    def test_each_placement_of_a_multiple_scene_prints_its_own_file(
        self, workspace_root: Path, client: TestClient
    ) -> None:
        """colour-chart-01 depicts black and moss. With moss marked light,
        the two placements print the two base files."""
        edit_garment_profile(
            workspace_root,
            PROFILE,
            colors={"black": "dark", "blue-jean": "dark", "ivory": "light", "moss": "light"},
        )
        light, dark = (
            _design(workspace_root, "dark-ink", (200, 30, 30)),
            _design(workspace_root, "light-ink", (30, 30, 200)),
        )
        edit_listing(workspace_root, design={"on-light": light, "on-dark": dark})

        chart = _get(client, template="colour-chart-01")

        assert chart == expected_scene(
            workspace_root, "colour-chart-01", None, {"black": dark, "moss": light}
        )
        assert chart != expected_scene(
            workspace_root, "colour-chart-01", None, {"black": dark, "moss": dark}
        )

    def test_a_layer_that_does_not_resolve_shows_the_bare_garment(
        self, workspace_root: Path, client: TestClient
    ) -> None:
        """A partial pair: ivory needs the empty light slot, so its scene is
        the photo with nothing printed rather than an error or a guess."""
        dark = _design(workspace_root, "light-ink", (30, 30, 200))
        edit_listing(workspace_root, design={"on-light": None, "on-dark": dark})

        ivory = _get(client, template="flat-lay-01", colour="ivory")

        assert ivory == expected_scene(workspace_root, "flat-lay-01", "ivory", {})

    def test_no_design_at_all_is_the_bare_garment(
        self, workspace_root: Path, client: TestClient
    ) -> None:
        edit_listing(workspace_root, design={})

        assert _get(client, template="flat-lay-01", colour="black") == expected_scene(
            workspace_root, "flat-lay-01", "black", {}
        )

    def test_a_design_file_that_is_gone_is_the_bare_garment(
        self, workspace_root: Path, client: TestClient
    ) -> None:
        edit_listing(workspace_root, design={"default": "designs/deleted.png"})

        assert _get(client, template="flat-lay-01", colour="black") == expected_scene(
            workspace_root, "flat-lay-01", "black", {}
        )

    def test_the_editor_scale_is_a_smaller_webp(self, client: TestClient) -> None:
        response = client.get(
            f"/api/listings/{LISTING}/scene-preview",
            params={"template": "flat-lay-01", "colour": "black", "scale": "editor"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"

    def test_the_version_parameter_is_accepted_and_ignored(
        self, workspace_root: Path, client: TestClient
    ) -> None:
        """``v`` is the editor's signature of the saved design map: a new
        value is a new URL once a save lands, and nothing else."""
        plain = _get(client, template="flat-lay-01", colour="black")

        assert _get(client, template="flat-lay-01", colour="black", v="abc123") == plain


class TestRefusals:
    def test_a_listing_that_will_not_load_is_404(
        self, workspace_root: Path, client: TestClient
    ) -> None:
        (workspace_root / "listings" / LISTING / "listing.yaml").write_text(
            "design: [not, a, map]\n", encoding="utf-8"
        )
        response = client.get(
            f"/api/listings/{LISTING}/scene-preview", params={"template": "flat-lay-01"}
        )
        assert response.status_code == 404

    def test_a_ref_that_escapes_its_root_is_the_bare_garment(
        self, workspace_root: Path, client: TestClient
    ) -> None:
        edit_listing(workspace_root, design={"default": "../outside.png"})

        assert _get(client, template="flat-lay-01", colour="black") == expected_scene(
            workspace_root, "flat-lay-01", "black", {}
        )

    def test_an_unknown_listing_is_404(self, client: TestClient) -> None:
        response = client.get(
            "/api/listings/nope/scene-preview", params={"template": "flat-lay-01"}
        )
        assert response.status_code == 404

    def test_an_unknown_template_is_404(self, client: TestClient) -> None:
        response = client.get(
            f"/api/listings/{LISTING}/scene-preview", params={"template": "no-such-template"}
        )
        assert response.status_code == 404

    def test_a_colour_with_no_photo_is_404(self, client: TestClient) -> None:
        response = client.get(
            f"/api/listings/{LISTING}/scene-preview",
            params={"template": "flat-lay-01", "colour": "not-a-colour"},
        )
        assert response.status_code == 404

    def test_a_colour_is_ignored_for_a_kind_with_no_per_colour_photo(
        self, client: TestClient
    ) -> None:
        response = client.get(
            f"/api/listings/{LISTING}/scene-preview",
            params={"template": "colour-chart-01", "colour": "not-a-colour"},
        )
        assert response.status_code == 200

    def test_the_full_render_is_the_photos_own_size(
        self, workspace_root: Path, client: TestClient
    ) -> None:
        png = _get(client, template="flat-lay-01", colour="black")
        with Image.open(BytesIO(png)) as image:
            size = image.size
        with Image.open(workspace_root / "mockup-templates" / "flat-lay-01" / "black.png") as photo:
            assert size == photo.size
        assert np.asarray(Image.open(BytesIO(png))).ndim == 3


class TestSceneArtwork:
    """``GET .../scene-artwork``: the file a layer prints, for Position mode to
    draw itself, resolved as the scene preview resolves it."""

    def _get(self, client: TestClient, **params: str) -> Response:
        return client.get(f"/api/listings/{LISTING}/scene-artwork", params=params)

    def _colour(self, response: Response) -> tuple[int, ...]:
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/webp"
        with Image.open(BytesIO(response.content)) as image:
            return tuple(image.convert("RGBA").getpixel((10, 10)))

    def test_a_colour_gets_the_file_its_tone_slot_prints(
        self, workspace_root: Path, client: TestClient
    ) -> None:
        light = _design(workspace_root, "dark-ink", (200, 30, 30))
        dark = _design(workspace_root, "light-ink", (30, 30, 200))
        edit_listing(workspace_root, design={"on-light": light, "on-dark": dark})

        ivory = self._colour(self._get(client, template="flat-lay-01", colour="ivory"))
        black = self._colour(self._get(client, template="flat-lay-01", colour="black"))

        assert ivory[0] > ivory[2]
        assert black[2] > black[0]

    def test_each_placement_gets_its_own_file(
        self, workspace_root: Path, client: TestClient
    ) -> None:
        edit_garment_profile(
            workspace_root,
            PROFILE,
            colors={"black": "dark", "blue-jean": "dark", "ivory": "light", "moss": "light"},
        )
        light = _design(workspace_root, "dark-ink", (200, 30, 30))
        dark = _design(workspace_root, "light-ink", (30, 30, 200))
        edit_listing(workspace_root, design={"on-light": light, "on-dark": dark})
        config = yaml.safe_load(
            (workspace_root / "mockup-templates" / "colour-chart-01" / "template.yaml").read_text(
                encoding="utf-8"
            )
        )
        by_colour = {p["colour"]: p["id"] for p in config["placements"]}

        moss = self._colour(
            self._get(client, template="colour-chart-01", placement=by_colour["moss"])
        )
        black = self._colour(
            self._get(client, template="colour-chart-01", placement=by_colour["black"])
        )

        assert moss[0] > moss[2]
        assert black[2] > black[0]

    def test_it_keeps_transparency_and_never_exceeds_the_live_edge(
        self, workspace_root: Path, client: TestClient
    ) -> None:
        path = workspace_root / "designs" / "large.png"
        Image.new("RGBA", (LIVE_ARTWORK_EDGE * 2, LIVE_ARTWORK_EDGE), (0, 0, 0, 0)).save(path)
        edit_listing(workspace_root, design={"default": "designs/large.png"})

        response = self._get(client, template="flat-lay-01", colour="black")

        assert self._colour(response)[3] == 0
        with Image.open(BytesIO(response.content)) as image:
            assert image.size == (LIVE_ARTWORK_EDGE, LIVE_ARTWORK_EDGE // 2)

    def test_a_layer_that_prints_nothing_is_not_found(
        self, workspace_root: Path, client: TestClient
    ) -> None:
        edit_listing(workspace_root, design={"default": None})

        assert self._get(client, template="flat-lay-01", colour="black").status_code == 404

    def test_a_placement_the_template_does_not_have_is_not_found(self, client: TestClient) -> None:
        response = self._get(client, template="colour-chart-01", placement="nowhere")

        assert response.status_code == 404
