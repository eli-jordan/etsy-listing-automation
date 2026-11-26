"""AI work: brief, market research and proposal as one streamed, cancellable
run per listing, and the batch queue that drafts only the brief for every
created batch row through the same runner (ADR-0048 through ADR-0050).

Runs live in memory, each on its own thread, and are forgotten on restart;
nothing guards two servers on one workspace. Serving a run's events is the
server's (``server/api/airuns.py``). This package re-exports nothing, and
withholds ``runner``: only ``coordinator`` and ``batch_queue`` may import it
(Import Linter's ``protected`` contract).
"""
