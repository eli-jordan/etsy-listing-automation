"""Behaviour tests for the file locator's endpoints (PRD 72, 73): the two
places a `media:` file ref can point -- `common-media/` and the listing's own
directory -- listed with their kind and served with their real type.

The listing-local half is a security boundary (A8): its listing name and file
path both arrive from URLs, and the directory it serves from also holds
`listing.yaml` and the lockfile. Real files on disk, no network, no fakes.
"""

from __future__ import annotations

import os
import shutil
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace

VIDEOS = Path(__file__).parent.parent / "fixtures" / "video"
CLIP = VIDEOS / "valid-3s-512.mp4"


@pytest.fixture
def client(workspace_root: Path) -> TestClient:
    workspace = Workspace.discover(root_override=workspace_root)
    return TestClient(create_app(workspace))


@pytest.fixture
def shared(workspace_root: Path) -> Path:
    path = workspace_root / "common-media"
    path.mkdir(exist_ok=True)
    return path


@pytest.fixture
def listing(workspace_root: Path) -> Path:
    return workspace_root / "listings" / "take-a-hike"


def _picture(path: Path, size: tuple[int, int] = (900, 700)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (210, 180, 140)).save(path)


class TestCommonMedia:
    def test_lists_every_shared_file_with_the_ref_a_listing_stores_and_its_kind(
        self, client: TestClient, shared: Path
    ) -> None:
        """The picker hands back the ref ready to write. A shared file's ref is
        its workspace-relative path (PRD 73), and its name is its path under
        `common-media/` -- what the picture endpoints take. Videos are listed
        too, told apart by `kind` rather than by the browser reading an
        extension (PRD 72)."""
        (shared / "charts").mkdir()
        (shared / "size-guide.png").write_bytes(b"")
        (shared / "charts" / "care.jpg").write_bytes(b"")
        (shared / "intro.MOV").write_bytes(b"")

        response = client.get("/api/common-media")
        assert response.status_code == 200
        assert response.json() == [
            {
                "name": "charts/care.jpg",
                "file": "common-media/charts/care.jpg",
                "ref": "common-media/charts/care.jpg",
                "kind": "image",
            },
            {
                "name": "intro.MOV",
                "file": "common-media/intro.MOV",
                "ref": "common-media/intro.MOV",
                "kind": "video",
            },
            {
                "name": "size-guide.png",
                "file": "common-media/size-guide.png",
                "ref": "common-media/size-guide.png",
                "kind": "image",
            },
        ]

    def test_is_empty_on_a_workspace_that_has_none(self, client: TestClient) -> None:
        assert client.get("/api/common-media").json() == []

    def test_serves_a_thumbnail(self, client: TestClient, shared: Path) -> None:
        _picture(shared / "size-guide.png")

        response = client.get("/api/common-media/size-guide.png/thumbnail")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        with Image.open(BytesIO(response.content)) as img:
            assert max(img.size) <= 160

    def test_serves_a_thumbnail_from_a_subdirectory(self, client: TestClient, shared: Path) -> None:
        _picture(shared / "charts" / "care.jpg")

        response = client.get("/api/common-media/charts%2Fcare.jpg/thumbnail")
        assert response.status_code == 200

    def test_a_video_has_no_thumbnail(self, client: TestClient, shared: Path) -> None:
        """The browser draws a video's own poster from its first frame; a
        thumbnail endpoint that could not open one would otherwise be a 500."""
        shutil.copyfile(CLIP, shared / "intro.mp4")

        assert client.get("/api/common-media/intro.mp4/thumbnail").status_code == 415

    def test_an_unknown_asset_404s(self, client: TestClient) -> None:
        assert client.get("/api/common-media/no-such-asset.png/thumbnail").status_code == 404
        assert client.get("/api/common-media/no-such-asset.png/file").status_code == 404

    @pytest.mark.parametrize(
        "name", ["..%2Fshop.yaml", "..%2Flistings%2Ftake-a-hike%2Flisting.yaml"]
    )
    def test_a_path_out_of_the_directory_is_refused(self, client: TestClient, name: str) -> None:
        """A8: the name reaches `common_media_file`, whose segment rule is the
        boundary."""
        assert client.get(f"/api/common-media/{name}/file").status_code == 400

    def test_serves_a_file_byte_for_byte(self, client: TestClient, shared: Path) -> None:
        """The thumbnail is a picture to *pick* out of a list; this is the one
        the editor's preview pane and its lightbox show -- the file Etsy would
        actually receive, not a re-encode."""
        source = shared / "size-guide.png"
        _picture(source)

        response = client.get("/api/common-media/size-guide.png/file")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == source.read_bytes()

    @pytest.mark.parametrize(
        ("name", "media_type"),
        [
            ("care.jpg", "image/jpeg"),
            ("care.JPEG", "image/jpeg"),
            ("intro.mp4", "video/mp4"),
            ("intro.mov", "video/quicktime"),
        ],
    )
    def test_serves_each_kind_with_its_own_type(
        self, client: TestClient, shared: Path, name: str, media_type: str
    ) -> None:
        """Named from the extension list `media:` accepts, not the platform's
        MIME table, which on Windows is read from the registry."""
        (shared / name).write_bytes(b"x")

        response = client.get(f"/api/common-media/{name}/file")
        assert response.headers["content-type"] == media_type

    def test_a_range_request_is_answered_in_part(self, client: TestClient, shared: Path) -> None:
        """`<video>` seeks by asking for a byte range; a server that sends the
        whole file instead leaves the scrubber unable to move."""
        shutil.copyfile(CLIP, shared / "intro.mp4")

        response = client.get("/api/common-media/intro.mp4/file", headers={"Range": "bytes=0-99"})
        assert response.status_code == 206
        assert response.content == CLIP.read_bytes()[:100]
        assert response.headers["content-range"] == f"bytes 0-99/{CLIP.stat().st_size}"


class TestListingMediaFiles:
    def test_lists_the_listings_own_files_with_the_ref_it_stores(
        self, client: TestClient, listing: Path
    ) -> None:
        """The *This listing* group: a `./` ref (PRD 73), and never the two
        files that sit beside the pictures."""
        (listing / "shots").mkdir()
        (listing / "shots" / "back.png").write_bytes(b"")
        shutil.copyfile(CLIP, listing / "close-up.mp4")
        (listing / "state.lock.json").write_text("{}", encoding="utf-8")

        response = client.get("/api/listings/take-a-hike/media-files")
        assert response.status_code == 200
        assert response.json() == [
            {
                "name": "close-up.mp4",
                "file": "listings/take-a-hike/close-up.mp4",
                "ref": "./close-up.mp4",
                "kind": "video",
            },
            {
                "name": "shots/back.png",
                "file": "listings/take-a-hike/shots/back.png",
                "ref": "./shots/back.png",
                "kind": "image",
            },
        ]

    def test_a_listing_with_no_files_of_its_own_lists_none(self, client: TestClient) -> None:
        assert client.get("/api/listings/take-a-hike/media-files").json() == []

    def test_an_unknown_listing_404s(self, client: TestClient) -> None:
        assert client.get("/api/listings/no-such-listing/media-files").status_code == 404

    @pytest.mark.parametrize("name", ["..", "..%2F..", "..%5Cshop"])
    def test_a_listing_name_that_is_not_one_segment_is_refused(
        self, client: TestClient, name: str
    ) -> None:
        """Refused before anything is listed: `..` would otherwise list
        `listings/` itself, and `..%2F..` the workspace root."""
        response = client.get(f"/api/listings/{name}/media-files")
        assert response.status_code in (400, 404)
        assert response.headers["content-type"] == "application/json"

    def test_serves_a_file_byte_for_byte_with_its_type(
        self, client: TestClient, listing: Path
    ) -> None:
        source = listing / "shots" / "back.png"
        _picture(source)

        response = client.get("/api/listings/take-a-hike/media-files/shots%2Fback.png/file")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == source.read_bytes()

    def test_serves_a_video_as_a_video_and_answers_a_range(
        self, client: TestClient, listing: Path
    ) -> None:
        shutil.copyfile(CLIP, listing / "close-up.mp4")

        response = client.get(
            "/api/listings/take-a-hike/media-files/close-up.mp4/file",
            headers={"Range": "bytes=10-19"},
        )
        assert response.status_code == 206
        assert response.headers["content-type"] == "video/mp4"
        assert response.content == CLIP.read_bytes()[10:20]

    def test_serves_an_image_thumbnail(self, client: TestClient, listing: Path) -> None:
        _picture(listing / "back.jpg")

        response = client.get("/api/listings/take-a-hike/media-files/back.jpg/thumbnail")
        assert response.status_code == 200
        with Image.open(BytesIO(response.content)) as img:
            assert max(img.size) <= 160

    def test_a_video_has_no_thumbnail(self, client: TestClient, listing: Path) -> None:
        shutil.copyfile(CLIP, listing / "close-up.mp4")

        response = client.get("/api/listings/take-a-hike/media-files/close-up.mp4/thumbnail")
        assert response.status_code == 415

    def test_an_unknown_file_404s(self, client: TestClient) -> None:
        response = client.get("/api/listings/take-a-hike/media-files/nothing.png/file")
        assert response.status_code == 404

    @pytest.mark.parametrize(
        "path",
        [
            "listing.yaml",
            "state.lock.json",
            "..%2F..%2Fshop.yaml",
            "shots%2F..%2F..%2F..%2Fshop.yaml",
            "..%2Fother%2Fx.png",
            "C%3Ax.png",
            "a%5Cb.png",
        ],
    )
    @pytest.mark.parametrize("endpoint", ["file", "thumbnail"])
    def test_a_path_that_is_not_one_of_its_media_files_is_refused(
        self, client: TestClient, listing: Path, path: str, endpoint: str
    ) -> None:
        """The two files a listing directory holds besides its pictures, and
        every spelling of a way out of it."""
        (listing / "state.lock.json").write_text("{}", encoding="utf-8")

        response = client.get(f"/api/listings/take-a-hike/media-files/{path}/{endpoint}")
        assert response.status_code == 400
        assert response.headers["content-type"] == "application/json"

    @pytest.mark.skipif(os.name == "nt", reason="symlinks need elevation on Windows")
    def test_a_symlink_out_of_the_listing_is_neither_listed_nor_served(
        self, client: TestClient, workspace_root: Path, listing: Path
    ) -> None:
        (listing / "shop.png").symlink_to(workspace_root / "shop.yaml")

        assert client.get("/api/listings/take-a-hike/media-files").json() == []
        response = client.get("/api/listings/take-a-hike/media-files/shop.png/file")
        assert response.status_code == 400
