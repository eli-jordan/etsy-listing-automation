"""The shop-scoped Printify write boundary (A4).

Narrow by design: the product methods land as the ``printify_product`` stage
needs them, not in one speculative batch. ``shops()`` is here first because
``setup`` needs it before any of the rest can be addressed at all -- every
other call in this protocol is scoped to a shop id that this one discovers.
"""

from __future__ import annotations

from typing import Protocol

from etsy_listings.clients.printify.models import Shop


class PrintifyClient(Protocol):
    def shops(self) -> list[Shop]:
        """Every shop the token can reach. Not shop-scoped, unlike the rest of
        this protocol -- it is what tells you which shop to scope to."""
        ...
