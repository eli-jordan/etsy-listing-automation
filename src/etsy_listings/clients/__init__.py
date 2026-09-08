"""Shop-scoped API clients: the halves of Printify and Etsy that *write*.

Distinct from :mod:`etsy_listings.catalog`, which is Printify's read-only,
shop-agnostic reference data and stays there. The split is not tidiness: a
catalog read is cacheable, idempotent and safe to fan out (A3), and nothing
built on ``CatalogClient`` should be able to reach a call that creates a
product by accident.

Each API gets a narrow ``Protocol`` returning pydantic models, an HTTP
implementation, and an in-memory fake (A4). Behaviour tests drive the fakes;
contract tests drive the HTTP client through ``httpx``'s mock transport
against transcripts of real responses.
"""
