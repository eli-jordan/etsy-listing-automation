"""Config loading keeps source paths and validation context at the file boundary."""

from pydantic import BaseModel, ValidationInfo, field_validator

from etsy_listings.core.config.errors import load_model


def test_model_loading_passes_currency_and_uses_the_supplied_reader(tmp_path):
    class Document(BaseModel):
        currency: str

        @field_validator("currency")
        @classmethod
        def currency_matches_context(cls, value, info: ValidationInfo):
            assert value == info.context["currency"]
            return value

    path = tmp_path / "document.yaml"
    path.touch()
    value = load_model(
        Document,
        path,
        context={"currency": "NOK"},
        read=lambda path: b"currency: NOK",
        missing="missing",
    )
    assert value.currency == "NOK"
