"""Seller-edited YAML as ADR-0055's writers must leave it.

`identity` tells a file left alone from one replaced with the same bytes: an
atomic replace gives the path a new file, so its id or mtime changes."""

from __future__ import annotations

from pathlib import Path


def identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_ino, stat.st_mtime_ns


def crlf(text: str) -> str:
    return text.replace("\n", "\r\n")
