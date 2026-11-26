from __future__ import annotations

from etsy_listings.core.application.backup_restore import RestoreStatus
from etsy_listings.server.api.schemas import TemplateSummary


def test_a_wire_field_docstring_is_its_openapi_description() -> None:
    width = TemplateSummary.model_json_schema()["properties"]["width"]

    assert "true pixel width" in width["description"]


def test_a_core_model_served_over_the_api_describes_its_fields_too() -> None:
    seconds_left = RestoreStatus.model_json_schema()["properties"]["seconds_left"]

    assert seconds_left["description"].startswith("Estimated from the rate so far")
