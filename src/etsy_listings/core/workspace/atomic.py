"""Replace a file without a window where a reader sees it half-written.

The atomic replacement rule shared by cache records and listing YAML writes.
JSON and YAML serializers use the same unique temporary and bounded retry.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


def write_bytes_atomic(path: Path, data: bytes, *, durable: bool = False) -> None:
    """Write ``data`` to a temporary file beside ``path``, then ``os.replace``
    it over ``path``. Same directory, so the rename never crosses a
    filesystem; a uniquely named temporary, so two writers never share one.
    A failure removes the temporary and leaves ``path`` as it was."""
    path.parent.mkdir(parents=True, exist_ok=True)
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
    """``os.replace``, waiting out a reader. Windows refuses to replace a file
    another thread has open -- CPython opens files without
    ``FILE_SHARE_DELETE`` -- with a bare ``PermissionError``, and a cache
    record is exactly that: the batch summary polls the record the queue is
    writing, and a refused save there left a row ``running`` for good. A
    read lasts milliseconds, so about a second of retries outlasts one; a
    refusal still there after that is a real one and is raised."""
    for _ in range(REPLACE_ATTEMPTS - 1):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            time.sleep(REPLACE_BACKOFF_SECONDS)
    os.replace(temporary, path)


def read_bytes_retrying(path: Path) -> bytes:
    """``path.read_bytes()``, waiting out a writer: the reader's half of
    :func:`_replace`. Windows also refuses to *open* a file while another
    thread is ``os.replace``-ing onto it, with the same bare
    ``PermissionError``, so a summary poll that lands on the queue's save
    would otherwise see the batch record vanish. The same bound applies; a
    refusal still there after it is raised. ``FileNotFoundError`` is never
    retried: a file that is not there is absent, at once."""
    for _ in range(REPLACE_ATTEMPTS - 1):
        try:
            return path.read_bytes()
        except PermissionError:
            time.sleep(REPLACE_BACKOFF_SECONDS)
    return path.read_bytes()


def write_json_atomic(path: Path, document: object) -> None:
    """:func:`write_bytes_atomic` for a cache record: indented UTF-8
    JSON, so a record is readable when somebody opens ``.cache`` to see why."""
    text = json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False)
    write_bytes_atomic(path, (text + "\n").encode("utf-8"))


def write_yaml_atomic(path: Path, document: Mapping[str, Any]) -> None:
    """Write a YAML document through the shared atomic replacement rule."""
    text = yaml.safe_dump(dict(document), sort_keys=False)
    write_bytes_atomic(path, text.encode("utf-8"))
