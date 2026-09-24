"""A description's lead: its first sentence (market-seo.md, *What the proposal
sees*). It is all of another seller's description that the model or the
panel ever sees."""

from __future__ import annotations

import pytest

from etsy_listings.market import lead


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("A retro sunset over the peaks. Printed to order.", "A retro sunset over the peaks."),
        ("Hike more! Worry less.", "Hike more!"),
        ("Need a gift? This is it.", "Need a gift?"),
        # A full stop inside a number or a word does not end the sentence.
        ("A 5.3 oz tee for www.example.com fans. Soft.", "A 5.3 oz tee for www.example.com fans."),
        # A heading line with no full stop ends at its line break.
        ("RETRO SUNSET TEE\nSoft and light. Unisex.", "RETRO SUNSET TEE"),
        ("  \n  Leading blank lines. Then more.", "Leading blank lines."),
        ("No full stop at all", "No full stop at all"),
        ("Ends at the end.", "Ends at the end."),
        ("", ""),
    ],
)
def test_the_lead_is_the_first_sentence(description: str, expected: str) -> None:
    assert lead(description) == expected


def test_a_runaway_first_sentence_is_cut_at_a_word_under_the_limit() -> None:
    description = "hiking shirt " * 40
    cut = lead(description)
    assert len(cut) <= 301
    assert cut.endswith("shirt…")
