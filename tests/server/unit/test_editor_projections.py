"""The editor's shared wire projection for an absent garment selection."""

from etsy_listings.server.api.editor_projections import garment_fields


def test_absent_garment_clears_all_display_metadata():
    assert garment_fields(None) == {
        "garment_materials": [],
        "garment_product_type": None,
        "garment_brand": None,
        "garment_model": None,
    }
