"""Drafting a listing `brief` from its design image: the request
shape, the packaged default `prompts/brief.md`, the response schema, and the
hard validation a draft passes before it can reach an editor field.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Final

from etsy_listings.core.ai.errors import OutputValidationError
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


class BriefValidationError(OutputValidationError): ...


def default_brief_prompt_text() -> str:
    return (
        resources.files("etsy_listings.core.ai.resources")
        .joinpath("brief.md")
        .read_text(encoding="utf-8")
    )


def build_brief_task(seller_prompt: str, request: BriefRequest) -> ProviderTask:
    return ProviderTask(
        prompt_text=build_task_prompt(seller_prompt, context=None, schema=BRIEF_RESPONSE_SCHEMA),
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
