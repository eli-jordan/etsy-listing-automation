from __future__ import annotations

from etsy_listings.core.application.backup_restore import RestoreStatus
from etsy_listings.server.api.schemas import TemplateSummary


def test_a_wire_field_docstring_is_its_openapi_description() -> None:
    width = TemplateSummary.model_json_schema()["properties"]["width"]

    assert "true pixel width" in width["description"]


def test_a_core_model_served_over_the_api_describes_its_fields_too() -> None:
    percent = RestoreStatus.model_json_schema()["properties"]["percent"]

    assert percent["description"] == "0 to 1."
