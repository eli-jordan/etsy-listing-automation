from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

FRONT_MATTER_DELIMITER = "---"
DESCRIPTION_TARGET = "description"
"""The only supported target today. A file that
does not name it is not usable as a description body, whatever else it
names."""


class CommonCopyError(ValueError):
    """A `description.ref` that does not resolve to usable common copy --
    missing, malformed front matter, or not targeted to `description`
    (`docs/features/ai-seo-20260922/interactions.md` section 6). The message always
    names the ref, since a stage or the editor's banner surfaces it verbatim."""


@dataclass(frozen=True)
class CommonCopyDocument:
    title: str
    targets: tuple[str, ...]
    summary: str | None
    body: str


def _front_matter(ref: str, lines: list[str]) -> tuple[dict[str, Any], int]:
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
    return header, end


def _targets(ref: str, raw_targets: object) -> tuple[str, ...]:
    if not isinstance(raw_targets, list) or not raw_targets:
        raise CommonCopyError(f"{ref!r}: front matter is missing targets")
    targets = tuple(str(target) for target in raw_targets)
    if DESCRIPTION_TARGET not in targets:
        raise CommonCopyError(
            f"{ref!r}: does not target {DESCRIPTION_TARGET!r} "
            f"(targets: {', '.join(targets) or 'none'})"
        )
    return targets


def parse_common_copy(ref: str, raw: str) -> CommonCopyDocument:
    lines = raw.splitlines()
    header, end = _front_matter(ref, lines)

    title = header.get("title")
    if not isinstance(title, str) or not title.strip():
        raise CommonCopyError(f"{ref!r}: front matter is missing a title")

    targets = _targets(ref, header.get("targets"))

    summary = header.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise CommonCopyError(f"{ref!r}: front matter summary must be text")

    body = "\n".join(lines[end + 1 :]).strip("\n")
    return CommonCopyDocument(title=title, targets=targets, summary=summary, body=body)
