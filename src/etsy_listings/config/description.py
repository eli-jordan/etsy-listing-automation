"""`etsy.description`'s structured model, and the one pure join rule every
deployment reader shares (AI SEO implementation plan, PR2).

`DescriptionConfig` replaces the old bare `description: str`: a required
`lead` (the opening paragraph a shopper reads) plus at most one body source --
inline `text` or a portable `ref` beneath `common-copy/`. `lead` may be empty
while a listing is being edited; deployment is blocked until it is non-empty
(`config/listing_validation.py`'s `check_copy_is_concrete`), not this model,
which has to stay satisfiable by an unsaved draft.

`compose_description` is the pure half of "the one shared composition path":
it only joins an already-resolved `lead`/`text` pair, and knows nothing about
`ref`, `common-copy/`, or the filesystem -- resolving a `ref` into text is
`Workspace.load_common_copy`'s job, and `Workspace.resolve_description` is the
one place that calls both in order (see `workspace/common_copy.py`). No other
stage, API serializer, or UI handler may independently concatenate, parse, or
path-resolve description text.
"""

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
    """The final concrete description Printify, Etsy, snapshots, diffs,
    validation and the UI preview all consume.

    Joins a non-empty ``lead`` and a non-empty ``text`` with exactly one blank
    line. A lead without a body is valid -- it composes to itself. An empty
    lead (a listing still being edited) preserves the body as-is, verbatim,
    rather than joining an empty string onto it. ``.strip()`` only decides
    which of those three branches applies; neither string's own content is
    otherwise touched, so a body's internal formatting survives untouched.
    """
    body = text or ""
    if not lead.strip():
        return body
    if not body.strip():
        return lead
    return f"{lead}\n\n{body}"
