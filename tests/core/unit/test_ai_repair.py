"""Prompt text sent on fresh and repaired CLI attempts."""

from pathlib import Path

from etsy_listings.core.ai.models import ProviderTask, RepairContext
from etsy_listings.core.ai.repair import prompt_text_for


def test_image_instructions_precede_the_repair_context():
    task = ProviderTask(
        prompt_text="Draft copy.", response_schema={}, design_image=Path("front.png")
    )
    repair = RepairContext(prior_raw_output="bad answer", reasons=("missing title",))
    prompt = prompt_text_for(task, repair, image_tool="Read")
    assert prompt.startswith(
        "Draft copy.\n\nThe design image is at this absolute path: front.png\n"
        "Use the Read tool to view it before answering.\n\n\n<<<PREVIOUS_RESPONSE>>>"
    )
    assert "bad answer" in prompt
    assert "missing title" in prompt
