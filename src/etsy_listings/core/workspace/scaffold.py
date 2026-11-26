"""A workspace's ``.gitignore`` and ``.env``, edited without disturbing what the
user put there.

``.gitignore`` must be in place before the first secret is written: a secret in
a directory an enclosing repository already tracks cannot be taken back.
"""

from __future__ import annotations

from pathlib import Path

from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.atomic import write_bytes_atomic

GITIGNORE_ENTRIES: tuple[tuple[str, str], ...] = (
    (layout.ENV_FILE, "API tokens -- never commit"),
    (f"{layout.AUTH_DIR}/", "OAuth tokens -- never commit"),
    (f"{layout.CACHE_DIR}/", "derived: catalog, renders, run history"),
)
"""What must not reach a repository, and why.

A workspace is not a git repository by default, but people put one around it
-- the listings and pricing are worth versioning. The two that would leak a
credential are the reason this file is written at all; ``.cache/`` is there
because it is large and fully derivable.
"""


def update_gitignore(root: Path) -> tuple[str, ...]:
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    present = {_ignore_pattern(line) for line in existing.splitlines()}

    added = tuple(
        f"{pattern:<12} # {why}" for pattern, why in GITIGNORE_ENTRIES if pattern not in present
    )
    if not added:
        return ()

    prefix = existing if not existing or existing.endswith("\n") else existing + "\n"
    path.write_text(prefix + "\n".join(added) + "\n", encoding="utf-8")
    return added


def _ignore_pattern(line: str) -> str:
    return line.split("#", 1)[0].strip()


def env_with(existing: str, key: str, value: str) -> str:
    lines = existing.splitlines()
    prefix = f"{key}="
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def write_env_value(root: Path, key: str, value: str) -> Path:
    """Replaced atomically and durably: ``.env`` holds this machine's only copy
    of the backup password, and a write cut short would lose it."""
    path = root / layout.ENV_FILE
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    write_bytes_atomic(path, env_with(existing, key, value).encode("utf-8"), durable=True)
    return path
