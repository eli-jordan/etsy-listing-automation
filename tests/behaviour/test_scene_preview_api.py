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
from fastapi.testclient import TestClient
from PIL import Image

from etsy_listings.render import (
    ColourMatrixTemplate,
    Layer,
    MultipleTemplate,
    encode_png,
    load_design,
    load_template_base,
    luminance_map,
    render_scene,
)
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_garment_profile, edit_listing

PROFILE = "comfort-colors-1717"


def _design(root: Path, name: str, rgb: tuple[int, int, int]) -> str:
    path = root / "designs" / f"{name}.png"
    Image.new("RGBA", (240, 300), (*rgb, 255)).save(path)
    return f"designs/{name}.png"


def expected_scene(
    root: Path, template: str, colour: str | None, files: dict[str | None, str]
) -> bytes:
    """``template``'s scene at full size, each layer printing ``files`` for the
    colour it depicts; a colour ``files`` does not name is left bare."""
    workspace = Workspace.discover(root_override=root)
    config = workspace.load_template_config(template)
    if isinstance(config, MultipleTemplate):
        specs = [(p.colour, config.render_config_for(p)) for p in config.placements]
    else:
        specs = [
            (colour if isinstance(config, ColourMatrixTemplate) else None, config.render_config())
        ]
    base = load_template_base(workspace.scene_photo(template, colour).path)
    layers = [Layer(design=load_design(root / files[c]), cfg=cfg) for c, cfg in specs if c in files]
    assert not any(cfg.displace.enabled for _, cfg in specs)
    return encode_png(render_scene(base, layers, luminance=luminance_map(base)))


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
