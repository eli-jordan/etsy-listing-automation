"""Printify's shop-scoped half: the calls that write, and the ones that read
state a shop owns rather than reference data everyone shares.

:class:`PrintifyClient` is the protocol; :class:`HttpPrintifyClient` talks to
Printify and :class:`FakePrintifyClient` is what behaviour tests use.

**Not exported, deliberately: nothing here caches.** ``catalog/`` wraps its
client in a TTL disk cache because blueprint data is large and rarely changes;
a shop's products are the state this tool is trying to converge on, and a
cached read of them would make ``plan`` report a diff against a stale world.

The surface grows one method at a time, as a stage needs it. ``shops()`` came
first because every other call in the protocol is scoped to a shop id, and
that one discovers it (PRD 42).
"""

from etsy_listings.clients.printify.fakes import FakePrintifyClient
from etsy_listings.clients.printify.http import (
    BASE_URL,
    HttpPrintifyClient,
    PrintifyApiError,
    PrintifyAuthError,
)
from etsy_listings.clients.printify.models import Shop
from etsy_listings.clients.printify.protocol import PrintifyClient

__all__ = [
    "PrintifyClient",
    "HttpPrintifyClient",
    "FakePrintifyClient",
    "BASE_URL",
    "PrintifyAuthError",
    "PrintifyApiError",
    "Shop",
]
