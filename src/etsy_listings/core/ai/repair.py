"""What text one attempt sends. A repair runs as a new, session-less CLI
invocation, so nothing about the first attempt survives unless the repair
prompt resends it.
"""

from __future__ import annotations

from typing import Final

from etsy_listings.core.ai.models import ProviderTask, RepairContext
from etsy_listings.core.ai.prompt import build_repair_prompt

PRIOR_RESPONSE_BEGIN: Final = "<<<PREVIOUS_RESPONSE>>>"
PRIOR_RESPONSE_END: Final = "<<<END_PREVIOUS_RESPONSE>>>"


def repair_prompt_suffix(repair: RepairContext) -> str:
    return (
        f"{PRIOR_RESPONSE_BEGIN}\n{repair.prior_raw_output}\n{PRIOR_RESPONSE_END}\n\n"
        f"{build_repair_prompt(repair.reasons)}"
    )


def prompt_text_for(
    task: ProviderTask, repair: RepairContext | None, *, image_tool: str | None = None
) -> str:
    text = task.prompt_text
    if image_tool is not None:
        text += (
            f"\n\nThe design image is at this absolute path: {task.design_image}\n"
            f"Use the {image_tool} tool to view it before answering.\n"
        )
    if repair is None:
        return text
    return f"{text}\n\n{repair_prompt_suffix(repair)}"
