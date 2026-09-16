"""``GarmentProfile`` as a document: what a file may name, and what it
must still load without.

The field that looks like it belongs in a listing -- ``preview_template`` --
is the editor's colour-judgement photo, not a ``media:`` default (A13, PRD 29).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.garment_profile import GarmentProfile

MINIMAL: dict[str, object] = {
    "blueprint": {"brand": "Comfort Colors", "model": "1717"},
    "print_provider": "Monster Digital",
    "placeholder": "front",
    "print_area": {"width": 4500, "height": 5400},
    "sizes": ["S", "M", "L"],
}


def _write(tmp_path: Path, data: dict[str, object]) -> Path:
    path = tmp_path / "comfort-colors-1717.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_a_profile_without_preview_template_still_loads(tmp_path: Path) -> None:
    """Existing workspace files predate the field; requiring it would refuse
    every garment profile that ``new`` has ever written."""
    profile = GarmentProfile.load(_write(tmp_path, MINIMAL))
    assert profile.preview_template is None


def test_preview_template_is_the_named_colour_matrix(tmp_path: Path) -> None:
    profile = GarmentProfile.load(_write(tmp_path, {**MINIMAL, "preview_template": "flat-lay-01"}))
    assert profile.preview_template == "flat-lay-01"


def test_an_empty_preview_template_is_the_same_as_omitting_it(tmp_path: Path) -> None:
    """``preview_template:`` with nothing after it is YAML null, and a blank
    string is the same question asked badly -- neither names a template."""
    assert (
        GarmentProfile.load(
            _write(tmp_path, {**MINIMAL, "preview_template": None})
        ).preview_template
        is None
    )
    assert (
        GarmentProfile.load(_write(tmp_path, {**MINIMAL, "preview_template": ""})).preview_template
        is None
    )


def test_unknown_fields_are_still_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError, match="templates"):
        GarmentProfile.load(_write(tmp_path, {**MINIMAL, "templates": ["flat-lay-01"]}))
