from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


class DescriptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead: str = ""
    text: str | None = None
    ref: str | None = None
    """A portable POSIX workspace reference beneath `common-copy/`, e.g.
    `common-copy/comfort-colors.md` -- resolved and loaded through
    `Workspace.load_common_copy`, never here (this model does no I/O and
    knows nothing about the workspace it will eventually be read from)."""

    @model_validator(mode="after")
    def _at_most_one_body_source(self) -> DescriptionConfig:
        if self.text is not None and self.ref is not None:
            raise ValueError("etsy.description: text and ref must not both be set")
        return self


def compose_description(lead: str, text: str | None) -> str:
    """The final description Printify, Etsy, snapshots, diffs, validation and
    the UI preview all consume."""
    body = text or ""
    if not lead.strip():
        return body
    if not body.strip():
        return lead
    return f"{lead}\n\n{body}"
