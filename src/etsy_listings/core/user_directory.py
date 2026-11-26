from __future__ import annotations

from pathlib import Path

USER_DIRECTORY_NAME = ".etsy-listings"


def user_directory(home: Path | None = None) -> Path:
    return (home or Path.home()) / USER_DIRECTORY_NAME
