"""The etsy-research-design skill's `design_ideas.py`: the generator prompt each idea's
brief fills in, and the command that generates the seller's picks."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SKILL = Path(__file__).parents[1] / ".claude/skills/etsy-research-design"


@pytest.fixture(scope="module")
def ideas() -> ModuleType:
    sys.path.insert(0, str(SKILL))
    spec = importlib.util.spec_from_file_location("design_ideas", SKILL / "design_ideas.py")
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["design_ideas"] = module
    spec.loader.exec_module(module)
    return module


def idea(**changes: Any) -> dict[str, Any]:
    base = {
        "slug": "kente-letters",
        "name": "Kente Letters",
        "text": "Black History / Month",
        "concept": "The month's name woven as kente strips.",
        "hook": "Celebratory and bold.",
        "direction": "woven letters, centred",
        "palette": "gold, red and black",
        "garment": "black",
        "ref": {"listing": 123, "take": "the woven strip lettering."},
        "general_tags": [],
        "niche_tags": [],
        "phrase": {},
        "template": {},
        "forecast": "strong",
        "why": "It sells.",
    }
    return base | changes


def test_the_prompt_is_filled_with_the_ideas_lines_and_shirt(ideas: ModuleType) -> None:
    prompt = ideas.fill_brief(idea())

    assert '"Black History" | "Month"' in prompt
    assert "upper half" in prompt
    assert "printed on a black shirt (#1c1c1c)" in prompt
    assert "Take only its style: the woven strip lettering." in prompt
    assert "pure green background (#00FF00)" in prompt
    assert "__" not in prompt


def test_a_green_palette_gets_a_magenta_key(ideas: ModuleType) -> None:
    prompt = ideas.fill_brief(idea(palette="red, black and green"))
    assert "magenta background (#FF00FF)" in prompt


def test_an_image_only_idea_asks_for_no_text(ideas: ModuleType) -> None:
    prompt = ideas.fill_brief(idea(text=None))
    assert "The artwork has no text" in prompt
    assert "exactly this text" not in prompt


def test_a_garment_with_no_known_colour_needs_a_hex(ideas: ModuleType) -> None:
    with pytest.raises(SystemExit, match="garment_hex"):
        ideas.fill_brief(idea(garment="butter"))
    assert "(#f3e6a0)" in ideas.fill_brief(idea(garment="butter", garment_hex="#f3e6a0"))


def test_picked_prints_the_command_that_generates_the_picks(
    ideas: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = {"ideas": [idea(slug="one"), idea(slug="two"), idea(slug="three")]}
    (tmp_path / "ideas.json").write_text(json.dumps(doc), encoding="utf-8")
    decisions = tmp_path / "dec"
    decisions.mkdir()
    for slug, decision in (("one", "generate"), ("two", "skip"), ("three", "generate")):
        (decisions / f"{slug}.json").write_text(json.dumps({"decision": decision}), "utf-8")

    ideas.picked(tmp_path, decisions)

    out = capsys.readouterr().out
    assert "2 to generate, 1 skipped, 0 undecided" in out
    assert f"generate_designs.py generate {tmp_path} one three" in out
