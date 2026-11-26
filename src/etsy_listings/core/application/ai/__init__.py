"""AI work: brief, market research and proposal as one streamed, cancellable run
per listing, and the batch queue that drafts every created batch row's brief
through the same runner.

Runs live in memory and are forgotten on restart, and nothing guards two
servers on one workspace."""
