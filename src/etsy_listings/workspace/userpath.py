"""Translates user-typed paths into paths this (Windows-native) process can open.

This exists for exactly one environment: the tool runs as a Windows-native
Python, but is driven from a Cygwin shell, where the natural thing to type is
``--root /home/Admin/etsy-listings``. Windows Python reads that as
``C:\\home\\Admin\\etsy-listings`` and reports a confusing "no shop.yaml
found" against a path the user never named.

Only *user-supplied* paths go through here -- CLI options and the
``ETSY_LISTINGS_ROOT`` environment variable. Paths written inside config files
are workspace-relative by construction (A8) and never need it, and nothing
downstream of ``Workspace`` ever sees a POSIX-style path.

Translate the **raw string**, before ``pathlib`` sees it: on Windows,
``str(Path("/home/Admin"))`` is already ``\\home\\Admin``, and a
backslash-mangled path can no longer be told apart from a legitimate
root-relative Windows one. That is why the CLI declares ``--root`` as ``str``
rather than ``Path``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

_CYGDRIVE = re.compile(r"^/cygdrive/([a-zA-Z])(/.*)?$")

CYGPATH_TIMEOUT_SECONDS = 5


def to_native_path(value: str) -> Path:
    """Best-effort conversion of a POSIX-style path to a native one.

    A no-op everywhere except Windows, and even there only for paths that
    actually look POSIX-absolute. Anything it can't confidently translate is
    returned unchanged -- a wrong guess would be worse than the original
    error message.
    """
    if os.name != "nt" or not value.startswith("/"):
        return Path(value)

    # /cygdrive/c/x -> C:\x. Purely textual, so it works even without Cygwin
    # installed (MSYS2 and Git Bash emit this form too).
    cygdrive = _CYGDRIVE.match(value)
    if cygdrive is not None:
        drive, rest = cygdrive.groups()
        return Path(f"{drive.upper()}:\\") / (rest or "").lstrip("/")

    # Anything else ("/home/Admin/...") depends on the shell's mount table,
    # which only cygpath can read. It ships with Cygwin, so it is present
    # exactly when such a path could have been typed.
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
