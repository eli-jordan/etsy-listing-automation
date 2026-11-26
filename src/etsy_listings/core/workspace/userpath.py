"""User-typed Cygwin paths (``--root /home/Admin/x``, ``ETSY_LISTINGS_ROOT``), translated for this
Windows-native process.

Translate the raw string: on Windows ``str(Path("/home/Admin"))`` is already ``\\home\\Admin``, a
root-relative Windows path, which is why ``--root`` is a ``str``."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

_CYGDRIVE = re.compile(r"^/cygdrive/([a-zA-Z])(/.*)?$")

CYGPATH_TIMEOUT_SECONDS = 5


def to_native_path(value: str) -> Path:
    if os.name != "nt" or not value.startswith("/"):
        return Path(value)

    # Textual, so it needs no Cygwin: MSYS2 and Git Bash emit this form too.
    cygdrive = _CYGDRIVE.match(value)
    if cygdrive is not None:
        drive, rest = cygdrive.groups()
        return Path(f"{drive.upper()}:\\") / (rest or "").lstrip("/")

    # Only cygpath can read the mount table, and it ships with Cygwin.
    return _via_cygpath(value)


def _via_cygpath(value: str) -> Path:
    cygpath = shutil.which("cygpath")
    if cygpath is None:
        return Path(value)
    try:
        result = subprocess.run(
            [cygpath, "-w", value],
            capture_output=True,
            text=True,
            timeout=CYGPATH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return Path(value)
    translated = result.stdout.strip()
    if result.returncode != 0 or not translated:
        return Path(value)
    return Path(translated)
