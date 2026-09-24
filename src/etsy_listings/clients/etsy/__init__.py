"""Everything said to Etsy, and everything remembered about saying it.

```
oauth.py      the flow as pure functions -- URLs, PKCE, payload parsing
callback.py   the loopback server that catches the redirect, once
tokens.py     the token file: expiry, rotation, the only writer of it
transport.py  Transport (both credentials, every API call, paced by the
              rate headers through RateGate) and OAuthClient (the token
              endpoint, which carries neither)
shops.py      EtsyShopClient -- setup's four unscoped reads
listings.py   EtsyListingClient -- Phase 3's stages: publish's poll target,
              the copy PATCH, media upload/reorder/variation-images
market.py     EtsyMarketClient -- market-informed SEO's three unscoped
              reads: search, batch stats, review counts (market-seo.md)
models.py     what every endpoint above returns
fakes.py      in-memory doubles for the behaviour layer (A4)
```

What is here (`oauth.py`, `callback.py`, `tokens.py`, `transport.py`) is the
authentication half, which everything else waits on (A23).

Exported below is what the rest of the codebase should need: a transport, the
two errors worth catching by type, and the store that keeps a bearer coming.
Deliberately withheld: `callback.wait_for_redirect`, which only `auth` has any
business calling -- a command that finds itself opening a browser mid-run is a
command that should have failed with :class:`EtsyAuthError` instead.
"""

from etsy_listings.clients.etsy.listings import EtsyListingClient, HttpEtsyListingClient
from etsy_listings.clients.etsy.market import EtsyMarketClient, HttpEtsyMarketClient
from etsy_listings.clients.etsy.oauth import OAuthError, Pkce, TokenResponse
from etsy_listings.clients.etsy.tokens import EtsyAuthError, StoredTokens, TokenStore
from etsy_listings.clients.etsy.transport import EtsyApiError, OAuthClient, Transport

__all__ = [
    "EtsyApiError",
    "EtsyAuthError",
    "EtsyListingClient",
    "EtsyMarketClient",
    "HttpEtsyListingClient",
    "HttpEtsyMarketClient",
    "OAuthClient",
    "OAuthError",
    "Pkce",
    "StoredTokens",
    "TokenResponse",
    "TokenStore",
    "Transport",
]
