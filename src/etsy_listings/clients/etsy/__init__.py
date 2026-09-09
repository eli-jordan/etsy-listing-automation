"""Everything said to Etsy, and everything remembered about saying it.

```
oauth.py      the flow as pure functions -- URLs, PKCE, payload parsing
callback.py   the loopback server that catches the redirect, once
tokens.py     the token file: expiry, rotation, the only writer of it
transport.py  Transport (both credentials, every API call) and OAuthClient
              (the token endpoint, which carries neither)
```

Phase 3's listing stages add `protocol.py`, `models.py` and `fakes.py` beside
these; what is here is the authentication half, which everything else waits
on (A23).

Exported below is what the rest of the codebase should need: a transport, the
two errors worth catching by type, and the store that keeps a bearer coming.
Deliberately withheld: `callback.wait_for_redirect`, which only `auth` has any
business calling -- a command that finds itself opening a browser mid-run is a
command that should have failed with :class:`EtsyAuthError` instead.
"""

from etsy_listings.clients.etsy.oauth import OAuthError, Pkce, TokenResponse
from etsy_listings.clients.etsy.tokens import EtsyAuthError, StoredTokens, TokenStore
from etsy_listings.clients.etsy.transport import EtsyApiError, OAuthClient, Transport

__all__ = [
    "EtsyApiError",
    "EtsyAuthError",
    "OAuthClient",
    "OAuthError",
    "Pkce",
    "StoredTokens",
    "TokenResponse",
    "TokenStore",
    "Transport",
]
