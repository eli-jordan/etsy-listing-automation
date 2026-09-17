"""Live plan/apply runs, in memory, for the UI server (A33).

Distinct from the top-level ``runs/`` package the code layout reserves for
Phase 6's SQLite recorder of *finished* runs -- this one holds runs that are
in flight or recently finished, forgotten on restart. When Phase 6 lands, the
recorder subscribes to :class:`~etsy_listings.ui.runs.registry.RunRegistry`
rather than replacing it.

``registry`` owns identity, locking and retention; ``executor`` owns the one
FIFO worker thread that actually calls into ``engine``; ``events`` owns the
wire shape a client streams. Nothing here computes a diff or runs a run
itself -- both remain ``engine``'s alone (CLAUDE.md's invariants); this
package is the part that turns one already-built ``RunReport`` into a
sequence of HTTP-visible events.
"""

from etsy_listings.ui.runs.executor import ContextFactory, RunExecutor
from etsy_listings.ui.runs.registry import Conflict, Run, RunRegistry

__all__ = ["Conflict", "ContextFactory", "Run", "RunExecutor", "RunRegistry"]
