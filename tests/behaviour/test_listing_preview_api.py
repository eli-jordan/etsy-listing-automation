"""``GET /api/listings/{name}/previews/{template}[/{colour}]`` (A32/A33):
resolved through ``Workspace.preview_file`` and the *current* scene hash,
never through a path built from the URL -- CLAUDE.md's invariant on
``workspace`` owning the layout is explicit that this is exactly the kind of
endpoint it exists to guard.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from etsy_listings.clients.printify.fakes import FakeCatalogClient
from etsy_listings.engine.context import EventSink, RunContext
from etsy_listings.engine.plan import build_plan
from etsy_listings.engine.run import preview_listing
from etsy_listings.engine.stages.render import RenderStage
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_lock, edit_listing, write_design


def _context_factory(workspace: Workspace, on_event: EventSink | None) -> RunContext:
    kwargs = {"on_event": on_event} if on_event is not None else {}
    return RunContext(
        workspace=workspace,
        catalog=FakeCatalogClient([], {}, {}),
        printify=None,
        etsy=None,
        **kwargs,
    )


def _client(workspace_root: Path) -> TestClient:
    workspace = Workspace.discover(root_override=workspace_root)
    return TestClient(create_app(workspace, context_factory=_context_factory))


def _render_previews(workspace_root: Path) -> None:
    """Seed a real preview file the way a plan run's `previewing` phase
    would, without going through the executor -- this endpoint only needs the
    file to exist, not a full run."""
    workspace = Workspace.discover(root_override=workspace_root)
    ctx = _context_factory(workspace, None)
    planned = build_plan(ctx, LISTING, a_lock(), [RenderStage()])
    preview_listing(ctx, planned)


class TestNotFound:
    def test_unknown_listing_is_404(self, workspace_root: Path) -> None:
        client = _client(workspace_root)

        response = client.get("/api/listings/nope/previews/flat-lay-01/black")

        assert response.status_code == 404

    def test_no_garment_profile_chosen_is_404(self, workspace_root: Path) -> None:
        edit_listing(workspace_root, garment_profile="")
        client = _client(workspace_root)

        response = client.get(f"/api/listings/{LISTING}/previews/flat-lay-01/black")

        assert response.status_code == 404

    def test_a_scene_never_referenced_by_media_is_404(self, workspace_root: Path) -> None:
        client = _client(workspace_root)

        response = client.get(f"/api/listings/{LISTING}/previews/flat-lay-01/mint")

        assert response.status_code == 404

    def test_a_referenced_scene_with_no_preview_rendered_yet_is_404(
        self, workspace_root: Path
    ) -> None:
        client = _client(workspace_root)

        response = client.get(f"/api/listings/{LISTING}/previews/flat-lay-01/black")

        assert response.status_code == 404

    def test_the_no_colour_route_is_404_for_a_colour_matrix_template(
        self, workspace_root: Path
    ) -> None:
        """`flat-lay-01` is `colour-matrix`-kind, so every scene needs a
        colour -- the bare route must not accidentally match one anyway."""
        client = _client(workspace_root)

        response = client.get(f"/api/listings/{LISTING}/previews/flat-lay-01")

        assert response.status_code == 404


class TestServesTheCurrentPreview:
    def test_a_rendered_preview_is_served_as_a_png(self, workspace_root: Path) -> None:
        _render_previews(workspace_root)
        client = _client(workspace_root)

        response = client.get(f"/api/listings/{LISTING}/previews/flat-lay-01/black")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        workspace = Workspace.discover(root_override=workspace_root)
        expected = next(
            p for p in (workspace.preview_dir(LISTING) / "flat-lay-01").glob("black-*.png")
        )
        assert response.content == expected.read_bytes()

    def test_every_referenced_colour_gets_its_own_file(self, workspace_root: Path) -> None:
        _render_previews(workspace_root)
        client = _client(workspace_root)

        black = client.get(f"/api/listings/{LISTING}/previews/flat-lay-01/black").content
        ivory = client.get(f"/api/listings/{LISTING}/previews/flat-lay-01/ivory").content

        assert black != ivory

    def test_a_stale_preview_from_before_an_edit_is_not_served(self, workspace_root: Path) -> None:
        """Editing the design changes the scene's hash -- the old file is
        still sitting on disk (nothing has pruned it, since no plan has run
        since), but the endpoint must not serve it as if it still matched.
        """
        _render_previews(workspace_root)
        write_design(workspace_root, (4600, 5500))
        client = _client(workspace_root)

        response = client.get(f"/api/listings/{LISTING}/previews/flat-lay-01/black")

        assert response.status_code == 404

    def test_no_lockfile_at_all_still_resolves_a_fresh_preview(self, workspace_root: Path) -> None:
        """The endpoint reads the lockfile through `Lockfile.read`, which
        answers `None` for a listing that has never been applied -- the
        render stage's own `desired()` already treats that as "nothing
        applied yet", not as an error."""
        _render_previews(workspace_root)
        lock_file = workspace_root / "listings" / LISTING / "state.lock.json"
        assert not lock_file.is_file(), "this fixture is never applied by this test"
        client = _client(workspace_root)

        response = client.get(f"/api/listings/{LISTING}/previews/flat-lay-01/black")

        assert response.status_code == 200
