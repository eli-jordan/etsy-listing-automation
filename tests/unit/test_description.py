"""`etsy.description`'s structured model and its one pure composer (AI SEO
implementation plan, PR2: "Target listing representation" /
"Description and common-copy boundaries").

`DescriptionConfig` is the strict `lead` + exactly one of `text`/`ref` model;
`compose_description` is the one join rule every deployment reader -- Printify,
Etsy, snapshots, diffs, validation, UI preview -- is meant to share. Both are
pure: no workspace, no filesystem, no network.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from etsy_listings.config.description import DescriptionConfig, compose_description


class TestDescriptionConfig:
    def test_defaults_to_an_empty_lead_with_no_body(self) -> None:
        description = DescriptionConfig()
        assert description.lead == ""
        assert description.text is None
        assert description.ref is None

    def test_accepts_a_lead_with_inline_text(self) -> None:
        description = DescriptionConfig(lead="A relaxed tee.", text="Printed to order.")
        assert description.lead == "A relaxed tee."
        assert description.text == "Printed to order."
        assert description.ref is None

    def test_accepts_a_lead_with_a_ref(self) -> None:
        description = DescriptionConfig(lead="A relaxed tee.", ref="common-copy/comfort-colors.md")
        assert description.ref == "common-copy/comfort-colors.md"
        assert description.text is None

    def test_rejects_text_and_ref_together(self) -> None:
        with pytest.raises(ValidationError, match="text and ref"):
            DescriptionConfig(lead="x", text="inline", ref="common-copy/x.md")

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            DescriptionConfig.model_validate({"lead": "x", "body": "y"})

    def test_an_empty_lead_is_valid_while_editing(self) -> None:
        """Deployment blocks on it (PRD 44's amendment) -- the model itself
        never refuses it, or a seller could not save a listing mid-edit."""
        assert DescriptionConfig(text="Printed to order.").lead == ""


class TestComposeDescription:
    def test_joins_a_non_empty_lead_and_body_with_one_blank_line(self) -> None:
        composed = compose_description("A relaxed tee.", "Printed to order.")
        assert composed == "A relaxed tee.\n\nPrinted to order."

    def test_a_lead_without_a_body_is_valid(self) -> None:
        assert compose_description("A relaxed tee.", None) == "A relaxed tee."
        assert compose_description("A relaxed tee.", "") == "A relaxed tee."

    def test_an_empty_lead_preserves_the_body_as_is(self) -> None:
        assert compose_description("", "Printed to order.") == "Printed to order."

    def test_both_empty_is_empty(self) -> None:
        assert compose_description("", None) == ""

    def test_does_not_strip_the_bodys_own_internal_formatting(self) -> None:
        """Only the *decision* to join uses `.strip()`; the body's own
        newlines are not this function's to rewrite."""
        composed = compose_description("Lead.", "Line one.\nLine two.")
        assert composed == "Lead.\n\nLine one.\nLine two."

    def test_a_whitespace_only_lead_behaves_as_empty(self) -> None:
        assert compose_description("   ", "Printed to order.") == "Printed to order."
