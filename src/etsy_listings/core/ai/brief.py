"""Drafting a listing `brief` from its design image: the request
shape, the packaged default `prompts/brief.md`, the response schema, and the
hard validation a draft passes before it can reach an editor field.

The whole feature is one module because it is one small contract, and
splitting it the way SEO is split (`models` / `prompt` / `validation`) would
put four files' worth of headers around about eighty lines of rule. What it
deliberately does *not* own is anything already owned elsewhere: the
delimited-context wrapper is `ai/prompt.py.build_task_prompt`, the provider
chain, repair and deadline are `ai/orchestrator.py`'s, and the CLI
invocation is each adapter's. A brief request is an ordinary
`ai/models.py.ProviderTask`, which is the entire point of that type.

Why a brief is validated at all, given it is one free-text field a seller can
edit: the same reason a proposal is. It is written into `listing.yaml`
without anyone reading it first, so the shapes that must never get there --
an empty string, a wall of text, a JSON object with no `brief` key at all
because the CLI ignored the schema -- are refused here rather than
discovered as a confusing autosave later. Everything beyond that (is it a
*good* brief?) is the seller's call, in an ordinary editable field.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Final

from etsy_listings.core.ai.models import ProviderTask
from etsy_listings.core.ai.prompt import build_task_prompt

MAX_BRIEF_LENGTH: Final = 1000
"""A ceiling, not a target -- `prompts/brief.md` asks for under 500
characters and two to five sentences. This refuses the failure mode that
ceiling exists to prevent: a model that answers with an essay, or with its
own reasoning transcript, filling the editor's Brief box with something the
seller has to delete before they can start. Generous enough that a genuinely
detailed brief about a busy design is never refused for being thorough."""


@dataclass(frozen=True)
class BriefRequest:
    design_image: Path


@dataclass(frozen=True)
class DesignBrief:
    brief: str


BRIEF_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["brief"],
    "properties": {"brief": {"type": "string"}},
}
"""The JSON Schema handed to a CLI's structured-output option, and the shape
:func:`validate_brief` hard-validates independently of whatever the CLI
itself enforced -- same rule as `ai/prompt.py.RESPONSE_SCHEMA`: a schema a
provider ignores or only partially honours must never reach the editor
unchecked."""


class BriefValidationError(Exception):
    def __init__(self, *reasons: str) -> None:
        self.reasons: tuple[str, ...] = reasons
        super().__init__("; ".join(reasons))


def default_brief_prompt_text() -> str:
    return (
        resources.files("etsy_listings.core.ai.resources")
        .joinpath("brief.md")
        .read_text(encoding="utf-8")
    )


def build_brief_task(seller_prompt: str, request: BriefRequest) -> ProviderTask:
    return ProviderTask(
        # No context block: the image is the whole input (see `BriefRequest`).
        prompt_text=build_task_prompt(seller_prompt, None, BRIEF_RESPONSE_SCHEMA),
        response_schema=BRIEF_RESPONSE_SCHEMA,
        design_image=request.design_image,
    )


def validate_brief(parsed: object) -> DesignBrief:
    if not isinstance(parsed, dict):
        raise BriefValidationError("response: expected a JSON object")

    value = parsed.get("brief")
    if not isinstance(value, str):
        raise BriefValidationError("brief: expected a string")

    text = " ".join(value.split())
    reasons: list[str] = []
    if not text:
        reasons.append("brief: must not be empty")
    if len(text) > MAX_BRIEF_LENGTH:
        reasons.append(
            f"brief: is {len(text)} characters, over the {MAX_BRIEF_LENGTH}-character limit"
        )
    if reasons:
        raise BriefValidationError(*reasons)
    return DesignBrief(brief=text)
