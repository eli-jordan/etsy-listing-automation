"""The transport-independent backend (ADR-0052).

Engine, workspace, config, clients, rendering, AI, market research, listing
templates, batches and explicit model preparation live here, with shared client construction
(:mod:`~etsy_listings.core.connections`), the user-facing error base
(:mod:`~etsy_listings.core.errors`) and the move and removal of everything
keyed by a listing's name (:mod:`~etsy_listings.core.listing_artifacts`).
Core may write files, call external services and run background work, but it
never imports FastAPI, Typer, the UI server, the CLI or the terminal/prompt
adapters that sit on top of it.

Nothing is re-exported here: each subpackage's ``__init__`` states its own
interface, and importing ``etsy_listings.core`` must not load OpenCV, httpx
or any subpackage just to reach one of them.
"""
