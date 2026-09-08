"""In-memory :class:`PrintifyClient` for behaviour tests. No network, ever."""

from __future__ import annotations

from etsy_listings.clients.printify.http import PrintifyAuthError
from etsy_listings.clients.printify.models import Shop
from etsy_listings.clients.printify.protocol import PrintifyClient


class FakePrintifyClient(PrintifyClient):
    """Configurable shop list, plus the one failure every caller has to
    handle.

    ``auth_fails`` exists because rejecting a token is not an edge case for
    ``setup`` -- it is the entire point of verifying one before it is stored,
    so the path has to be drivable without a network.
    """

    def __init__(self, shops: list[Shop] | None = None, *, auth_fails: bool = False) -> None:
        self._shops = list(shops or [])
        self.auth_fails = auth_fails
        self.shops_calls = 0

    def shops(self) -> list[Shop]:
        self.shops_calls += 1
        if self.auth_fails:
            raise PrintifyAuthError(401)
        return list(self._shops)
