"""The file locator's endpoints (PRD 72, 73): the two directories a `media:`
file ref can name, listed with each file's kind, and served.

A file ref has two roots, and the locator offers one group per root: the
listing's own directory (``./close-up.mp4``) and ``common-media/``
(``common-media/size-guide.png``). Both groups answer the same three
questions -- what is here, a picture to pick it by, the file itself -- so both
are one schema and one pair of responses, differing only in which `Workspace`
accessor finds the file.

The listing-local half is a security boundary (A8). Its listing name and path
both come from URLs, and the directory it serves from also holds
``listing.yaml`` and the lockfile. The boundary is `Workspace`'s
(``_media_file_in``); this module only decides that a refusal is a ``400``
(the app-wide ``InvalidNameError`` handler) and a missing file a ``404``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from etsy_listings.config.media import media_kind
from etsy_listings.ui.api.schemas import MediaFileSummary
from etsy_listings.ui.api.thumbnails import thumbnail_response
from etsy_listings.workspace import layout
from etsy_listings.workspace.workspace import Workspace

router = APIRouter(tags=["media-files"])

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}
"""Every extension `media:` accepts (PRD 72), named here rather than asked of
`mimetypes`, which on Windows reads the registry and may not know ``.mov``."""


def _workspace(request: Request) -> Workspace:
    workspace: Workspace = request.app.state.workspace
    return workspace


@router.get("/api/common-media", response_model=list[MediaFileSummary])
def list_common_media(request: Request) -> list[MediaFileSummary]:
    """The *Shared* group: files every listing can use -- a sizing chart,
    care instructions, a size-guide video.

    Distinct from both design endpoints: ``designs/`` is the artwork that gets
    printed, ``test-designs/`` is calibration targets, and these are finished
    files uploaded to Etsy as-is, never rendered onto a garment.
    """
    workspace = _workspace(request)
    shared = workspace.common_media_dir()
    rows: list[MediaFileSummary] = []
    for path in workspace.common_media_files():
        ref = f"{layout.COMMON_MEDIA_DIR}/{path.relative_to(shared).as_posix()}"
        rows.append(_summary(path, shared, file=ref, ref=ref))
    return rows


@router.get("/api/common-media/{name:path}/thumbnail")
def common_media_thumbnail(request: Request, name: str) -> Response:
    return _thumbnail(_existing(_workspace(request).common_media_file(name), name))


@router.get("/api/common-media/{name:path}/file")
def common_media_file(request: Request, name: str) -> FileResponse:
    """The shared file at its own size, for the preview pane and the
    lightbox -- the bytes as they sit on disk, which are exactly what Etsy
    would receive."""
    return _file(_existing(_workspace(request).common_media_file(name), name))


@router.get("/api/listings/{listing}/media-files", response_model=list[MediaFileSummary])
def list_listing_media_files(request: Request, listing: str) -> list[MediaFileSummary]:
    """The *This listing* group: the listing's own files, each with the
    ``./`` ref that names it (PRD 73). A ``404`` for a listing that does not
    exist, rather than an empty group that would look like one with nothing
    in it."""
    workspace = _workspace(request)
    if not workspace.listing_file(listing).is_file():
        raise HTTPException(status_code=404, detail=f"no listing {listing!r}")
    directory = workspace.listing_dir(listing)
    rows: list[MediaFileSummary] = []
    for path in workspace.listing_media_files(listing):
        relative = path.relative_to(directory).as_posix()
        rows.append(
            _summary(
                path,
                directory,
                file=f"{layout.LISTINGS_DIR}/{listing}/{relative}",
                ref=f"./{relative}",
            )
        )
    return rows


@router.get("/api/listings/{listing}/media-files/{path:path}/thumbnail")
def listing_media_thumbnail(request: Request, listing: str, path: str) -> Response:
    return _thumbnail(_existing(_workspace(request).listing_media_file(listing, path), path))


@router.get("/api/listings/{listing}/media-files/{path:path}/file")
def listing_media_file(request: Request, listing: str, path: str) -> FileResponse:
    return _file(_existing(_workspace(request).listing_media_file(listing, path), path))


def _summary(path: Path, directory: Path, *, file: str, ref: str) -> MediaFileSummary:
    return MediaFileSummary(
        name=path.relative_to(directory).as_posix(), file=file, ref=ref, kind=media_kind(ref)
    )


def _existing(path: Path, name: str) -> Path:
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"no media file {name!r}")
    return path


def _thumbnail(path: Path) -> Response:
    """A picture to pick an image by. A video answers ``415``: the locator
    draws its own poster from the first frame with a ``<video>`` element, and
    a still would be a second rendition of the same frame to keep in step."""
    if media_kind(path.name) == "video":
        raise HTTPException(status_code=415, detail="a video has no thumbnail; use /file")
    return thumbnail_response(path)


def _file(path: Path) -> FileResponse:
    """The file as-is, through `FileResponse` so a ``Range`` request is
    answered ``206`` -- which is how ``<video>`` seeks. ``no-cache`` means
    revalidate, so a replaced file shows without a hard refresh."""
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES[path.suffix.lower()],
        headers={"Cache-Control": "no-cache"},
    )
