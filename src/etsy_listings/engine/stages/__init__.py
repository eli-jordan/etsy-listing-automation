"""Concrete stages, in pipeline order (A1: order encodes dependency).

Empty in Phase 0 -- ``plan``/``apply`` walk this list and, with nothing in it,
produce an empty plan. Phase 1 adds ``Render()``; later phases add the
Printify/Etsy stages.
"""

from __future__ import annotations

from etsy_listings.engine.stage import AnyStage

STAGES: list[AnyStage] = []
