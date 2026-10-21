"""Original artwork for the local placement overlay."""

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from etsy_listings.core.workspace import Workspace
from etsy_listings.server.api.app import create_app


def test_original_design_retains_alpha_and_full_resolution(workspace_root: Path) -> None:
    client = TestClient(create_app(Workspace.discover(root_override=workspace_root)))
    response = client.get("/api/designs/bundled-grid/image")
    assert response.status_code == 200
    image = Image.open(BytesIO(response.content))
    assert image.mode == "RGBA"
    assert min(image.size) > 160
    assert client.get("/api/designs/nonexistent/image").status_code == 400
