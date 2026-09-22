"""The one bit of prompt assembly both CLI adapters share for a same-provider
repair call (AI SEO implementation plan, PR4, item 3): showing the model
exactly what it produced last time, then appending PR3's
`ai/prompt.py.build_repair_prompt`.

A repair call runs as a brand-new, session-less CLI invocation (no durable
provider session -- implementation plan, "Provider process"), so nothing
about the first attempt survives unless this call resends it. Kept as its
own tiny module, not inlined into each adapter, so the delimiters and
wording used to show "here is what you said last time" can't drift between
Codex and Claude.
"""

from __future__ import annotations

from typing import Final

from etsy_listings.ai.models import RepairContext
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
