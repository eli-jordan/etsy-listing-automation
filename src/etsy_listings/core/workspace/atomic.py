"""Replace a file without a window where a reader sees it half-written."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from etsy_listings.core.workspace.yaml_source import UNSET, edit_yaml_bytes


def write_bytes_atomic(path: Path, data: bytes, *, durable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Beside path, so the rename never crosses a filesystem.
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            if durable:
                stream.flush()
                os.fsync(stream.fileno())
        _replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


REPLACE_ATTEMPTS = 40
REPLACE_BACKOFF_SECONDS = 0.025


def _replace(temporary: str, path: Path) -> None:
    """Windows refuses to replace a file another thread has open (CPython opens
    without ``FILE_SHARE_DELETE``) with a bare ``PermissionError``. A read
    lasts milliseconds, so about a second of retries outlasts one."""
    for _ in range(REPLACE_ATTEMPTS - 1):
        try:
            Path(temporary).replace(path)
        except PermissionError:
            time.sleep(REPLACE_BACKOFF_SECONDS)
        else:
            return
    Path(temporary).replace(path)


def read_bytes_retrying(path: Path) -> bytes:
    """Windows also refuses to open a file while another thread replaces it,
    with the same bare ``PermissionError``."""
    for _ in range(REPLACE_ATTEMPTS - 1):
        try:
            return path.read_bytes()
        except PermissionError:
            time.sleep(REPLACE_BACKOFF_SECONDS)
    return path.read_bytes()


def write_json_atomic(path: Path, document: object) -> None:
    text = json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False)
    write_bytes_atomic(path, (text + "\n").encode("utf-8"))


def write_yaml_atomic(
    path: Path,
    document: object,
    *,
    new: Callable[[], str],
    before: object = UNSET,
    durable: bool = False,
) -> bool:
    """The caller holds whatever lock guards ``path``."""
    try:
        source = read_bytes_retrying(path)
    except FileNotFoundError:
        write_bytes_atomic(path, new().encode("utf-8"), durable=durable)
        return True
    edited = edit_yaml_bytes(source, document, before=before)
    if edited is source:
        return False
    write_bytes_atomic(path, edited, durable=durable)
    return True
