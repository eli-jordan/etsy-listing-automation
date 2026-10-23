"""Composed scenes, kept on disk by identity so a scene is composed once.

A full-size scene takes seconds to compose and encode (a Marigold one also
about 1 GB); its PNG is about 5 MB. :class:`SceneCache` keeps the PNG under the
scene's pixel identity, either renderer's
(:mod:`~etsy_listings.core.render.identity`). An entry is only ever written
under an identity computed from the very arrays that were composed, so it is
exactly the bytes a fresh composition encodes, and a reader holding a
pixel-derived identity (the render stage) trusts nothing but that identity.

Previews reach the same identity without decoding anything through
:data:`PIXEL_DIGESTS`, which remembers each photo's and design's pixel digest
against the file's :func:`~etsy_listings.core.workspace.file_version.file_version`
stamp. A file written since has a new stamp and is decoded again.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TypeVar

import numpy as np

from etsy_listings.core.render import load_design, load_template_base
from etsy_listings.core.render.identity import artwork_identity
from etsy_listings.core.render.types import RGB, RGBA
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.file_version import file_version

SCENE_CACHE_BYTES = 2 * 1024**3
"""About 400 full-size scenes. Past it the least recently read go first."""

_IDENTITY = re.compile(r"^sha256:([0-9a-f]{64})$")


class SceneCache:
    """Encoded scenes under ``.cache/scenes/``, least recently read evicted
    first. Reading an entry refreshes its modification time, which is the
    recency eviction sorts by."""

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
        """``identity``'s entry, or ``compose()``'s PNG, stored before it is
        returned. One composition per identity at a time: a second caller
        waits, then reads the first one's entry."""
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
    """Write beside ``path`` and rename over it, so a reader never sees a
    partial file. A rename refused because a reader holds the file open
    (Windows) leaves the existing entry, which has the same bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    except OSError:
        if not path.is_file():
            raise
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


_Pixels = TypeVar("_Pixels", RGB, RGBA)


class PixelDigests:
    """Pixel digests of files, remembered while the file's stamp is unchanged.

    A digest is remembered only when the stamp read before decoding matches
    the one read after, so a write racing the decode is never recorded."""

    def __init__(self, maxsize: int = 1024) -> None:
        self._maxsize = maxsize
        self._known: OrderedDict[tuple[str, Path], tuple[tuple[int | str, ...], str]] = (
            OrderedDict()
        )
        self._lock = threading.Lock()

    def photo(self, path: Path) -> str | None:
        return self._recall("photo", path)

    def design(self, path: Path) -> str | None:
        return self._recall("design", path)

    def decode_photo(
        self, path: Path, load: Callable[[Path], RGB] = load_template_base
    ) -> tuple[RGB, str]:
        """``path``'s pixels through ``load``, and their digest. Compose
        with these pixels, not a second decode, so the digest names them."""
        return self._decode("photo", path, load, photo_digest)

    def decode_design(
        self, path: Path, load: Callable[[Path], RGBA] = load_design
    ) -> tuple[RGBA, str]:
        return self._decode("design", path, load, artwork_identity)

    def _recall(self, kind: str, path: Path) -> str | None:
        try:
            stamp = file_version(path)
        except OSError:
            return None
        key = (kind, path.resolve())
        with self._lock:
            known = self._known.get(key)
            if known is None or known[0] != stamp:
                return None
            self._known.move_to_end(key)
            return known[1]

    def _decode(
        self,
        kind: str,
        path: Path,
        load: Callable[[Path], _Pixels],
        digest: Callable[[_Pixels], str],
    ) -> tuple[_Pixels, str]:
        before = file_version(path)
        pixels = load(path)
        value = digest(pixels)
        if file_version(path) == before:
            key = (kind, path.resolve())
            with self._lock:
                self._known[key] = (before, value)
                self._known.move_to_end(key)
                while len(self._known) > self._maxsize:
                    self._known.popitem(last=False)
        return pixels, value


def photo_digest(base: RGB) -> str:
    """The ``photo_pixels`` input of ``prepared_scene_identity``."""
    return hashlib.sha256(np.ascontiguousarray(base).tobytes()).hexdigest()


PIXEL_DIGESTS = PixelDigests()
"""Process-wide: the server's preview requests share it."""
