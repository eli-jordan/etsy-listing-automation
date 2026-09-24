"""What text one attempt actually sends -- the one bit of prompt assembly
both CLI adapters share (AI SEO implementation plan, PR4, item 3): a first
attempt sends the task's prompt unchanged, and a repair attempt appends the
model's own previous response, then PR3's `ai/prompt.py.build_repair_prompt`.

A repair call runs as a brand-new, session-less CLI invocation (no durable
provider session -- implementation plan, "Provider process"), so nothing
about the first attempt survives unless this call resends it. Kept as its
own tiny module, not inlined into each adapter, so the delimiters and
wording used to show "here is what you said last time" can't drift between
Codex and Claude.
"""

from __future__ import annotations

from typing import Final

from etsy_listings.ai.models import ProviderTask, RepairContext
from etsy_listings.ai.prompt import build_repair_prompt

PRIOR_RESPONSE_BEGIN: Final = "<<<PREVIOUS_RESPONSE>>>"
PRIOR_RESPONSE_END: Final = "<<<END_PREVIOUS_RESPONSE>>>"


def repair_prompt_suffix(repair: RepairContext) -> str:
    """Text to append after the ordinary `build_prompt` output for a repair
    call: the previous response inside its own delimited block, then the
    same repair instructions `ai/orchestrator.py` would give any provider."""
    return (
        f"{PRIOR_RESPONSE_BEGIN}\n{repair.prior_raw_output}\n{PRIOR_RESPONSE_END}\n\n"
        f"{build_repair_prompt(repair.reasons)}"
    )


def prompt_text_for(task: ProviderTask, repair: RepairContext | None) -> str:
    """The complete prompt text for one attempt at ``task``.

    Both adapters call exactly this, so "what does a repair send?" has one
    answer rather than one per CLI -- the shape of mistake this module was
    already split out to prevent, applied to the branch as well as the
    wording.
    """
    if repair is None:
        return task.prompt_text
    return f"{task.prompt_text}\n\n{repair_prompt_suffix(repair)}"
