"""Every config loader turns a file YAML cannot parse into a ConfigLoadError
naming that file, the same as a file that parses but fails validation.

Subject: the YAML-reading ``load`` of each ``core.config`` model.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from etsy_listings.core.config.defaults import Defaults
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.exceptions import load_exceptions
from etsy_listings.core.config.garment_profile import GarmentProfile
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.config.pricing_plan import PricingPlan
from etsy_listings.core.config.settings import Settings

LOADERS: dict[str, Callable[[Path], object]] = {
    "defaults": Defaults.load,
    "exceptions": load_exceptions,
    "garment_profile": GarmentProfile.load,
    "listing": lambda path: Listing.load(path, currency="USD"),
    "listing_template": lambda path: ListingTemplate.load(path, currency="USD"),
    "pricing_plan": lambda path: PricingPlan.load(path, currency="USD"),
    "settings": Settings.load,
}


@pytest.mark.parametrize("load", LOADERS.values(), ids=LOADERS.keys())
def test_a_file_that_is_not_yaml_names_the_file(
    tmp_path: Path, load: Callable[[Path], object]
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("key: [unclosed\n", "utf-8")

    with pytest.raises(ConfigLoadError) as caught:
        load(path)

    assert caught.value.path == path
    assert "not valid YAML" in str(caught.value)
