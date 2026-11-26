"""What `new` tells the user on the way, and what it refuses before asking anything.

Subject: the notices and early refusals in ``cli.new``. The rows each picker
offers are ``test_new_picker.py``'s; the whole walk is ``test_new.py``'s.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from etsy_listings.cli import new
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient
from etsy_listings.core.clients.printify.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.core.workspace.workspace import Workspace


def _variant(variant_id: int, size: str, width: int, height: int) -> Variant:
    return Variant(
        id=variant_id,
        title=f"Black / {size}",
        options=VariantOptions(color="Black", size=size),
        placeholders=(PrintAreaPlaceholder(position="front", width=width, height=height),),
    )


def test_the_shops_preferred_print_provider_is_the_first_row(
    workspace_root: Path, scripted
) -> None:
    script = scripted({"Print provider": "Monster Digital"})
    workspace = Workspace.discover(root_override=workspace_root)
    providers = [
        PrintProvider(id=1, title="Awkward Styles"),
        PrintProvider(id=29, title="Monster Digital"),
    ]

    new._pick_provider(workspace, providers)

    assert script.rows_for("Print provider")[0] == "Monster Digital"


def test_a_print_area_that_varies_by_garment_size_is_announced(capsys) -> None:
    variants = VariantSet(
        variants=(_variant(1, "S", 3600, 4800), _variant(2, "2XL", 4500, 5400)),
    )

    new._report_print_area_choice(variants)

    out = capsys.readouterr().out
    assert "3600x4800 to 4500x5400" in out
    assert "Recording the largest" in out


def test_a_single_kind_template_says_one_image_covers_every_colour(capsys) -> None:
    new._report_media_choice("lifestyle-01", "single", ["black", "white"], [{}])

    assert "one image for the listing, covering all 2 colours" in capsys.readouterr().out


def test_a_colour_matrix_over_etsys_image_limit_says_which_colours_get_photos(capsys) -> None:
    colours = [f"colour-{n}" for n in range(new.MAX_IMAGES + 5)]
    media = [{"colour": colour} for colour in colours[: new.MAX_IMAGES]]

    new._report_media_choice("flat-lay-01", "colour-matrix", colours, media)

    out = capsys.readouterr().out
    assert f"Etsy allows {new.MAX_IMAGES} images" in out
    assert f"All {len(colours)} stay in colors:" in out


def test_a_design_saved_with_a_doubled_extension_is_a_warning_that_names_it(
    workspace_root: Path, capsys
) -> None:
    """Writing the listing before its artwork exists is a legitimate order, so
    a missing design only warns; a near-miss name is the likely cause."""
    (workspace_root / "designs" / "duke-java.png.png").write_bytes(b"")
    workspace = Workspace.discover(root_override=workspace_root)

    new._warn_if_design_missing(workspace, "duke-java")

    assert "Did you mean 'duke-java.png.png'?" in capsys.readouterr().out


def test_a_taken_listing_name_is_refused_before_any_question(
    workspace_root: Path, scripted
) -> None:
    """Creating the listing is the last thing `new` does; without the early
    check the whole wizard would run before saying no."""
    script = scripted({})
    workspace = Workspace.discover(root_override=workspace_root)

    tee = Blueprint(id=12, title="Unisex Heavy Cotton Tee", brand="Gildan", model="5000")

    with pytest.raises(typer.Exit):
        new.run_new(workspace, FakeCatalogClient([tee], {}, {}), "take-a-hike", "tshirt")

    assert script.asked == []
