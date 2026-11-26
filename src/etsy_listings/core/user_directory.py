from __future__ import annotations

from pathlib import Path

USER_DIRECTORY_NAME = ".etsy-listings"


def user_directory(home: Path | None = None) -> Path:
    """The per-user directory under ``home`` (the real home by default).
    Not created here: each owner creates what it writes, when it writes it,
    so a read-only inspection leaves nothing behind."""
    return (home or Path.home()) / USER_DIRECTORY_NAME
