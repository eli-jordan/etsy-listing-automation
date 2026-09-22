"""`common-copy/*.md`: reusable description bodies, and the one place their
Markdown front matter is parsed (AI SEO implementation plan, PR2:
"Description and common-copy boundaries").

A common-copy file is `---`-delimited YAML front matter (`title`, `targets`,
optional `summary`) followed by its Markdown body -- the body a
`description.ref` supplies to :func:`~etsy_listings.config.description.compose_description`.
:func:`parse_common_copy` is pure: it takes the ref only to name it in a
refusal, and the raw text `Workspace.load_common_copy` already read. Nothing
else in the codebase may parse this shape -- see that method's docstring.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

FRONT_MATTER_DELIMITER = "---"
DESCRIPTION_TARGET = "description"
"""The only supported target today (PRD's description model). A file that
does not name it is not usable as a description body, whatever else it
names."""


class CommonCopyError(ValueError):
    """A `description.ref` that does not resolve to usable common copy --
    missing, malformed front matter, or not targeted to `description`
    (`docs/ui-listing-seo-interactions.md` section 6). The message always
    names the ref, since a stage or the editor's banner surfaces it verbatim."""


@dataclass(frozen=True)
class CommonCopyDocument:
    title: str
    targets: tuple[str, ...]
    summary: str | None
    body: str


def parse_common_copy(ref: str, raw: str) -> CommonCopyDocument:
    """``raw`` is the file's full text; ``ref`` is used only to name it in a
    refusal. Reading the file is
    :meth:`~etsy_listings.workspace.workspace.Workspace.load_common_copy`'s job
    -- this function does no I/O, so it is exercised directly against string
    fixtures rather than real files on disk.
    """
    lines = raw.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_DELIMITER:
        raise CommonCopyError(
            f"{ref!r}: missing front matter -- expected the file to open with a '---' block"
        )
    try:
        end = lines.index(FRONT_MATTER_DELIMITER, 1)
    except ValueError as exc:
        raise CommonCopyError(f"{ref!r}: front matter is never closed with '---'") from exc

    try:
        header = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise CommonCopyError(f"{ref!r}: front matter is not valid YAML: {exc}") from exc
    if not isinstance(header, dict):
        raise CommonCopyError(f"{ref!r}: front matter must be a mapping of title/targets/summary")

    title = header.get("title")
    if not isinstance(title, str) or not title.strip():
        raise CommonCopyError(f"{ref!r}: front matter is missing a title")

    raw_targets = header.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise CommonCopyError(f"{ref!r}: front matter is missing targets")
    targets = tuple(str(target) for target in raw_targets)
    if DESCRIPTION_TARGET not in targets:
        raise CommonCopyError(
            f"{ref!r}: does not target {DESCRIPTION_TARGET!r} "
            f"(targets: {', '.join(targets) or 'none'})"
        )

    summary = header.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise CommonCopyError(f"{ref!r}: front matter summary must be text")

    body = "\n".join(lines[end + 1 :]).strip("\n")
    return CommonCopyDocument(title=title, targets=targets, summary=summary, body=body)
