"""`common-copy/*.md` front-matter parsing (AI SEO implementation plan, PR2:
"Description and common-copy boundaries").

Pure: `parse_common_copy` takes the ref (for its own error messages) and the
raw file text, and never touches a filesystem -- `Workspace.load_common_copy`
is what reads the bytes. Front matter carries `title` and `targets`, optional
`summary`, and must target `description`; anything else is a
`CommonCopyError` naming the ref.
"""

from __future__ import annotations

import pytest

from etsy_listings.workspace.common_copy import CommonCopyError, parse_common_copy

REF = "common-copy/comfort-colors.md"


def _doc(front_matter: str, body: str = "Printed to order on a Comfort Colors 1717 shirt.") -> str:
    return f"---\n{front_matter}\n---\n{body}"


class TestParseCommonCopy:
    def test_parses_title_targets_and_body(self) -> None:
        doc = parse_common_copy(REF, _doc("title: Comfort Colors\ntargets: [description]"))
        assert doc.title == "Comfort Colors"
        assert doc.targets == ("description",)
        assert doc.summary is None
        assert doc.body == "Printed to order on a Comfort Colors 1717 shirt."

    def test_parses_an_optional_summary(self) -> None:
        doc = parse_common_copy(
            REF, _doc("title: Comfort Colors\ntargets: [description]\nsummary: Fit and care.")
        )
        assert doc.summary == "Fit and care."

    def test_a_multi_line_body_survives_intact(self) -> None:
        doc = parse_common_copy(
            REF, _doc("title: Comfort Colors\ntargets: [description]", body="Line one.\nLine two.")
        )
        assert doc.body == "Line one.\nLine two."

    def test_missing_leading_front_matter_delimiter_is_an_error(self) -> None:
        with pytest.raises(CommonCopyError, match="front matter"):
            parse_common_copy(REF, "title: Comfort Colors\ntargets: [description]\n---\nBody.")

    def test_an_unclosed_front_matter_block_is_an_error(self) -> None:
        with pytest.raises(CommonCopyError, match="closed"):
            parse_common_copy(REF, "---\ntitle: Comfort Colors\ntargets: [description]\nBody.")

    def test_front_matter_that_is_not_valid_yaml_is_an_error(self) -> None:
        with pytest.raises(CommonCopyError, match="YAML"):
            parse_common_copy(REF, _doc("title: [unterminated"))

    def test_front_matter_that_is_not_a_mapping_is_an_error(self) -> None:
        with pytest.raises(CommonCopyError, match="mapping"):
            parse_common_copy(REF, _doc("- just\n- a\n- list"))

    def test_a_missing_title_is_an_error(self) -> None:
        with pytest.raises(CommonCopyError, match="title"):
            parse_common_copy(REF, _doc("targets: [description]"))

    def test_a_blank_title_is_an_error(self) -> None:
        with pytest.raises(CommonCopyError, match="title"):
            parse_common_copy(REF, _doc('title: ""\ntargets: [description]'))

    def test_missing_targets_is_an_error(self) -> None:
        with pytest.raises(CommonCopyError, match="targets"):
            parse_common_copy(REF, _doc("title: Comfort Colors"))

    def test_empty_targets_is_an_error(self) -> None:
        with pytest.raises(CommonCopyError, match="targets"):
            parse_common_copy(REF, _doc("title: Comfort Colors\ntargets: []"))

    def test_targets_missing_description_is_an_error(self) -> None:
        with pytest.raises(CommonCopyError, match="description"):
            parse_common_copy(REF, _doc("title: Comfort Colors\ntargets: [tags]"))

    def test_a_non_string_summary_is_an_error(self) -> None:
        with pytest.raises(CommonCopyError, match="summary"):
            parse_common_copy(
                REF, _doc("title: Comfort Colors\ntargets: [description]\nsummary: [1, 2]")
            )

    def test_the_error_names_the_ref(self) -> None:
        with pytest.raises(CommonCopyError, match=REF):
            parse_common_copy(REF, _doc("targets: [description]"))
