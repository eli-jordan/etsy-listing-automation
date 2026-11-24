"""``~/.etsy-listings``: this machine's state, kept outside every workspace.

The Marigold runtime, the pinned restic download and the backup state file
live here, because they belong to the computer, not to the workspace that
travels between computers in a backup (workspace-backup spec, *Status and
warnings*). Every owner takes ``home`` so tests never write to the real home
directory (workspace-backup plan, P2).
"""

from __future__ import annotations

from pathlib import Path

USER_DIRECTORY_NAME = ".etsy-listings"


def user_directory(home: Path | None = None) -> Path:
    """The per-user directory under ``home`` (the real home by default).
    Not created here: each owner creates what it writes, when it writes it,
    so a read-only inspection leaves nothing behind."""
    return (home or Path.home()) / USER_DIRECTORY_NAME
