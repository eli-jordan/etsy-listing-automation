"""Whether a cached proposal still describes its listing (ADR-0049; spec, *Durable
AI proposals*): the inputs frozen when it was generated against the same
inputs read from the listing now, with a reason per input that moved.

This is the frontend's old ``isStale`` moved to the server, field by field,
so the editor and the batch summary say the same thing about one proposal.
"""

from __future__ import annotations

import pytest

from etsy_listings.core.ai.proposals import SeoProposalSnapshot, proposal_staleness


def _snapshot(**over: object) -> SeoProposalSnapshot:
    fields: dict[str, object] = {
        "brief": "Retro sunset over mountains; the text reads TAKE A HIKE.",
        "product_type": "Unisex Garment-Dyed T-shirt",
        "etsy_category": "Hiking",
        "materials": ["ring-spun cotton", "water-based ink"],
        "colors": ["black", "ivory", "moss"],
        "garment_brand": "Comfort Colors",
        "garment_model": "1717",
        "garment_profile": "comfort-colors-1717",
        "design": {"default": "designs/take-a-hike.png"},
        "design_content_hash": "3f1c",
    }
    fields.update(over)
    return SeoProposalSnapshot.model_validate(fields)


def test_unchanged_inputs_are_not_stale() -> None:
    staleness = proposal_staleness(_snapshot(), _snapshot())

    assert staleness.is_stale is False
    assert staleness.reasons == []


@pytest.mark.parametrize(
    ("changed", "reason"),
    [
        ({"brief": "A different brief."}, "brief edited since"),
        ({"etsy_category": "Gifts"}, "shop section changed since"),
        ({"colors": ["black", "ivory"]}, "colours changed since"),
        ({"materials": ["polyester"]}, "materials changed since"),
        ({"garment_profile": "bella-canvas-3001"}, "garment profile changed since"),
        ({"product_type": "Heavyweight Tee"}, "product type changed since"),
        ({"garment_brand": "Bella+Canvas"}, "garment brand changed since"),
        ({"garment_model": "1717X"}, "garment model changed since"),
        ({"design": {"default": "designs/other.png"}}, "design changed since"),
        ({"design_content_hash": "9a0b"}, "design file edited since"),
        ({"design_content_hash": None}, "design file edited since"),
    ],
)
def test_each_generation_input_gives_its_own_reason(
    changed: dict[str, object], reason: str
) -> None:
    staleness = proposal_staleness(_snapshot(), _snapshot(**changed))

    assert staleness.is_stale is True
    assert staleness.reasons == [reason]


@pytest.mark.parametrize(
    ("frozen", "now"),
    [
        ({"colors": ["black", "ivory", "moss"]}, {"colors": ["moss", "black", "ivory"]}),
        (
            {"materials": ["ring-spun cotton", "water-based ink"]},
            {"materials": ["water-based ink", "ring-spun cotton"]},
        ),
        (
            {"design": {"on-light": "designs/a.png", "on-dark": "designs/b.png"}},
            {"design": {"on-dark": "designs/b.png", "on-light": "designs/a.png"}},
        ),
    ],
)
def test_order_carries_no_meaning(frozen: dict[str, object], now: dict[str, object]) -> None:
    """``VariantsTab`` appends a re-enabled colour at the end, and a design
    map can arrive in any key order: the same set is the same input."""
    assert proposal_staleness(_snapshot(**frozen), _snapshot(**now)).is_stale is False


def test_a_repeated_colour_is_not_the_same_set() -> None:
    frozen = _snapshot(colors=["black", "ivory"])

    assert proposal_staleness(frozen, _snapshot(colors=["black", "black"])).is_stale is True


def test_every_changed_input_is_reported() -> None:
    now = _snapshot(brief="Edited.", colors=["black"], design_content_hash="9a0b")

    assert proposal_staleness(_snapshot(), now).reasons == [
        "brief edited since",
        "colours changed since",
        "design file edited since",
    ]


def test_a_new_garment_profile_is_one_reason_not_five() -> None:
    """A different profile brings its own product type, materials, brand and
    model; the heading names the change the seller made, not its echoes."""
    now = _snapshot(
        garment_profile="bella-canvas-3001",
        product_type="Unisex Jersey Tee",
        materials=["airlume cotton"],
        garment_brand="Bella+Canvas",
        garment_model="3001",
    )

    assert proposal_staleness(_snapshot(), now).reasons == ["garment profile changed since"]


def test_a_different_design_is_one_reason_not_two() -> None:
    now = _snapshot(design={"default": "designs/other.png"}, design_content_hash="9a0b")

    assert proposal_staleness(_snapshot(), now).reasons == ["design changed since"]


class TestALightDarkPair:
    """Multi-artwork plan, *AI staleness*: only arming follows the
    representative artwork; staleness compares the whole map, ``null`` slots
    and colour keys included, since every file in it is what the proposal was
    judged against."""

    PAIR: dict[str, str | None] = {"on-light": "designs/light.png", "on-dark": None}

    def test_the_same_pair_is_not_stale_empty_slot_and_key_order_aside(self) -> None:
        frozen = _snapshot(design=self.PAIR)
        now = _snapshot(design={"on-dark": None, "on-light": "designs/light.png"})
        assert proposal_staleness(frozen, now).is_stale is False

    def test_filling_the_empty_slot_is_stale_though_the_representative_is_unchanged(
        self,
    ) -> None:
        now = _snapshot(design={**self.PAIR, "on-dark": "designs/dark.png"})
        assert proposal_staleness(_snapshot(design=self.PAIR), now).reasons == [
            "design changed since"
        ]

    def test_a_colour_s_own_design_is_stale(self) -> None:
        now = _snapshot(design={**self.PAIR, "black": "designs/black.png"})
        assert proposal_staleness(_snapshot(design=self.PAIR), now).reasons == [
            "design changed since"
        ]
