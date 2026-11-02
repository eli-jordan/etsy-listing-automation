"""`PhaseTimer`: where a listings read spent its time."""

from __future__ import annotations

import pytest

from etsy_listings.core.application.listing_reads import PhaseTimer


class TickingClock:
    """Each read is one second after the last."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def test_a_phase_entered_per_row_sums_every_entry() -> None:
    timer = PhaseTimer(clock=TickingClock())
    for _ in range(3):
        with timer.phase("load"):
            pass
    assert timer.seconds == {"load": 3.0}


def test_a_phase_that_raises_is_still_counted() -> None:
    timer = PhaseTimer(clock=TickingClock())
    with pytest.raises(ValueError, match="boom"), timer.phase("checks"):
        raise ValueError("boom")
    assert timer.seconds == {"checks": 1.0}
