"""The two files a workspace needs before it is one, and the rules for
editing them without disturbing what the user put there.

Both were `setupcmd`'s until `auth` needed them too (PRD 49): `auth` writes
credentials into `.env`, and it runs *before* `setup`, so it is also the
command that must put the `.gitignore` in place -- a secret written into a
directory that some enclosing repository is already tracking is not something
a later `setup` run can take back.

They live under `workspace/` rather than in whichever command reached for them
first, because both are statements about the layout of a workspace (A8), and
because a second copy of the ignore list is exactly the drift that rule
exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

from etsy_listings.workspace import layout

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
    """Append any missing entry to ``.gitignore``; return the lines added.

    Appends rather than rewrites: the file may already carry rules that have
    nothing to do with us, and a workspace's ``.gitignore`` is the user's.
    """
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    # The pattern, not the line: the entries this function writes carry a
    # trailing `# why` comment, so comparing whole lines made every run think
    # its own previous output was missing and append it again.
    present = {line.split("#", 1)[0].strip() for line in existing.splitlines()}

    added = tuple(
        f"{pattern:<12} # {why}" for pattern, why in GITIGNORE_ENTRIES if pattern not in present
    )
    if not added:
        return ()

    prefix = existing if not existing or existing.endswith("\n") else existing + "\n"
    path.write_text(prefix + "\n".join(added) + "\n", encoding="utf-8")
    return added


def env_with(existing: str, key: str, value: str) -> str:
    """``existing`` with ``key`` set to ``value``, everything else untouched.

    Rewriting the line in place rather than appending keeps a second
    assignment from shadowing the first, and leaves comments and unrelated
    keys exactly where the user put them. A commented-out assignment is not a
    match -- it is a note, and silently un-commenting one would be a surprise.
    """
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
    """Set one variable in the workspace's ``.env``, creating it if needed.

    The one place the read-modify-write is spelled, because both commands that
    store a credential do exactly this and neither should be deciding on its
    own what happens to a file it did not fully read.
    """
    path = root / layout.ENV_FILE
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    path.write_text(env_with(existing, key, value), encoding="utf-8")
    return path
