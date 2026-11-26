from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TypeVar

import numpy as np

from etsy_listings.core.bounded_cache import BoundedCache
from etsy_listings.core.render import load_design, load_template_base
from etsy_listings.core.render.identity import artwork_identity
from etsy_listings.core.render.types import RGB, RGBA
from etsy_listings.core.workspace import Workspace, layout
from etsy_listings.core.workspace.file_version import file_version

SCENE_CACHE_BYTES = 2 * 1024**3
"""About 400 full-size scenes. Past it the least recently read go first."""

_IDENTITY = re.compile(r"^sha256:([0-9a-f]{64})$")


class SceneCache:
    def __init__(self, workspace: Workspace, *, budget: int = SCENE_CACHE_BYTES) -> None:
        self._root = workspace.scene_cache_dir()
        self._budget = budget

    def read(self, identity: str) -> bytes | None:
        path = self._path(identity)
        try:
            data = path.read_bytes()
        except OSError:
            return None
        with contextlib.suppress(OSError):
            os.utime(path)
        return data

    def get_or_compose(self, identity: str, compose: Callable[[], bytes]) -> bytes:
        """One composition per identity at a time: a second caller reads the first's entry."""
        with _composing(identity):
            png = self.read(identity)
            if png is None:
                png = compose()
                self.store(identity, png)
            return png

    def store(self, identity: str, png: bytes) -> None:
        write_atomic(self._path(identity), png)
        self._evict()

    def _path(self, identity: str) -> Path:
        match = _IDENTITY.match(identity)
        if match is None:
            raise ValueError(f"not a scene identity: {identity!r}")
        return self._root / f"{match.group(1)}.png"

    def _evict(self) -> None:
        entries = []
        for path in self._root.glob("*.png"):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((stat.st_mtime_ns, stat.st_size, path))
        total = sum(size for _, size, _ in entries)
        for _, size, path in sorted(entries):
            if total <= self._budget:
                break
            try:
                path.unlink()
            except OSError:
                # Another thread is reading it (Windows), or already removed it.
                continue
            total -= size


_COMPOSING: dict[str, tuple[threading.Lock, int]] = {}
_COMPOSING_GUARD = threading.Lock()


@contextlib.contextmanager
def _composing(identity: str) -> Iterator[None]:
    with _COMPOSING_GUARD:
        lock, users = _COMPOSING.get(identity, (threading.Lock(), 0))
        _COMPOSING[identity] = (lock, users + 1)
    try:
        with lock:
            yield
    finally:
        with _COMPOSING_GUARD:
            lock, users = _COMPOSING[identity]
            if users == 1:
                del _COMPOSING[identity]
            else:
                _COMPOSING[identity] = (lock, users - 1)


def write_atomic(path: Path, data: bytes) -> None:
    """Write beside ``path`` and rename over it, so a reader never sees a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        Path(temporary).replace(path)
    except OSError:
        # Windows refuses the rename while a reader holds the file; it has these bytes.
        if not path.is_file():
            raise
    finally:
        temporary_path = Path(temporary)
        if temporary_path.exists():
            temporary_path.unlink()


_Pixels = TypeVar("_Pixels", RGB, RGBA)


class PixelDigests:
    def __init__(self, maxsize: int = 1024) -> None:
        self._known: BoundedCache[tuple[str, Path], tuple[tuple[int | str, ...], str]] = (
            BoundedCache(maxsize)
        )

    def photo(self, path: Path) -> str | None:
        return self._recall("photo", path)

    def design(self, path: Path) -> str | None:
        return self._recall("design", path)

    def decode_photo(
        self, path: Path, load: Callable[[Path], RGB] = load_template_base
    ) -> tuple[RGB, str]:
        """Compose with these pixels, not a second decode, so the digest names them."""
        return self._decode("photo", path, load, photo_digest)

    def decode_design(
        self, path: Path, load: Callable[[Path], RGBA] = load_design
    ) -> tuple[RGBA, str]:
        return self._decode("design", path, load, artwork_identity)

    def known(self, kind: str, path: Path) -> tuple[tuple[int | str, ...], str] | None:
        """The stamp and digest this process computed for ``path``, if any:
        what :class:`RememberedDigests` keeps across restarts."""
        return self._known.get((kind, path.resolve()))

    def clear(self) -> None:
        """Forget every digest, as a restart does."""
        self._known.clear()

    def _recall(self, kind: str, path: Path) -> str | None:
        try:
            stamp = file_version(path)
        except OSError:
            return None
        known = self._known.get((kind, path.resolve()))
        if known is None or known[0] != stamp:
            return None
        return known[1]

    def _decode(
        self,
        kind: str,
        path: Path,
        load: Callable[[Path], _Pixels],
        digest: Callable[[_Pixels], str],
    ) -> tuple[_Pixels, str]:
        # Reuse a digest only when the stamps before and after the decode agree.
        key = (kind, path.resolve())
        before = file_version(path)
        known = self._known.get(key)
        pixels = load(path)
        unchanged = file_version(path) == before
        if unchanged and known is not None and known[0] == before:
            return pixels, known[1]
        value = digest(pixels)
        if unchanged:
            self._known.put(key, (before, value))
        return pixels, value


def photo_digest(base: RGB) -> str:
    return hashlib.sha256(np.ascontiguousarray(base).tobytes()).hexdigest()


PIXEL_DIGESTS = PixelDigests()
"""Process-wide: the server's preview requests share it."""


class RememberedDigests:
    """Pixel digests kept on disk under ``.cache/pixel-digests/``, each with
    the file stamp it was computed for, so a scene viewed before a restart is
    found again without decoding its photo and designs.

    Only the Listing Images preview reads them, and it checks each answer
    afterwards (``GET /api/listings/{name}/scene-preview/verify``): a digest
    read from here is a guess about a file, while :data:`PIXEL_DIGESTS` holds
    what this process computed. The render stage and deploy never read it.
    Writing is safe from anywhere, since an entry is only ever a digest just
    computed from the file at that stamp."""

    def __init__(self, workspace: Workspace) -> None:
        self._root = workspace.cache(layout.PIXEL_DIGESTS_DIR)

    def recall(self, kind: str, path: Path) -> str | None:
        """``path``'s remembered digest, while its stamp is the one recorded."""
        try:
            stamp = file_version(path)
            entry = json.loads(self._path(kind, path).read_bytes())
        except (OSError, ValueError):
            return None
        if not isinstance(entry, dict) or entry.get("stamp") != list(stamp):
            return None
        digest = entry.get("digest")
        return digest if isinstance(digest, str) else None

    def remember(self, kind: str, path: Path) -> None:
        """Keep what this process computed for ``path``, if it computed one."""
        known = PIXEL_DIGESTS.known(kind, path)
        if known is None:
            return
        stamp, digest = known
        entry = json.dumps({"stamp": list(stamp), "digest": digest}).encode()
        with contextlib.suppress(OSError):
            write_atomic(self._path(kind, path), entry)

    def _path(self, kind: str, path: Path) -> Path:
        key = hashlib.sha256(f"{kind}\0{path.resolve()}".encode()).hexdigest()
        return self._root / f"{key}.json"
