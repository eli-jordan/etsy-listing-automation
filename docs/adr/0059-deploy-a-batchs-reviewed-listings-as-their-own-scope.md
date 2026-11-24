# ADR-0059: Deploy a batch's reviewed listings as their own scope

Status: accepted. First recorded 2026-11-24.

A listing batch's summary offers **Deploy reviewed**: one plan and apply over
the batch's rows that are marked Reviewed and whose listing has changes its
last apply did not deploy (never applied, edited since, or an apply left
incomplete). That last fact is local, read from the lockfile as the `draft`
and `dirty` badges are, so choosing the rows needs no Etsy call. A reviewed
row already deployed stays out until it is edited again.

This is a third run scope, `batch`, beside `listings` and `workspace`, rather
than a listings-scoped run naming several listings. It reuses ADR-0042's
review rule unchanged: the server resolves the row set when it accepts the
plan, and a `BatchApply` must repeat a ready plan of the same batch, its
listings in order and their fingerprints. The workspace review page serves it
too, so the review, preview and result surfaces stay one implementation; only
its title, copy and Back link name the batch.

A batch run conflicts only with active runs holding one of its listings, and
with any active workspace run, so another batch or an unrelated listing can
still be queued behind it on the one worker (ADR-0041). The registry keeps the
latest run per batch apart from the per-listing holder, so a listing's own
deploy page never adopts a batch run as that listing's run; a listing deploy
refused by one is sent to the batch's review page instead.
