"""Automation that takes a print-on-demand t-shirt design to a reviewable Etsy draft.

The current module map and invariants live in docs/architecture.md. The
``server`` and ``cli`` adapters compose the transport-independent
``core`` packages: engine, workspace, config, clients, rendering, AI, market
research, listing templates and batches. Only core.engine computes deployment
diffs and merges stage results into lockfiles; core.workspace owns the
user-data layout. Dependencies form a graph, not a strict layered tree.
Catalog protocols and caches live under core/clients/printify.

Each package's ``__init__`` states its own interface and what it deliberately
does not do. Nothing is re-exported here: importing the root would otherwise
drag in OpenCV, FastAPI and Typer to read a version number.
"""

from etsy_listings.__about__ import VERSION

__all__ = ["VERSION"]
