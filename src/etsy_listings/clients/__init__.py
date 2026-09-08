"""The outside world: one package per API this tool talks to.

``printify/``   everything said to Printify -- reference data and shop writes
``etsy/``       Etsy's OAuth and listing endpoints (Phase 3)
``retry.py``    the backoff policy both write sides share (A21)
``limiter.py``  token buckets and the persisted daily budget (Phase 6)

Each API gets narrow ``Protocol``s returning pydantic models, an HTTP
implementation, and an in-memory fake (A4). Behaviour tests drive the fakes;
contract tests drive the HTTP clients through ``httpx``'s mock transport
against transcripts of real responses.

Where one API carries more authority in one place than another -- Printify's
catalog reads versus its product writes -- the separation is a protocol, not a
package. See :mod:`etsy_listings.clients.printify` for why that distinction is
the one worth drawing.
"""
