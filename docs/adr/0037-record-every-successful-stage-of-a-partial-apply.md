# ADR-0037: Record every successful stage of a partial apply

Record the folded lockfile after each successful stage and record an incomplete-stage marker before re-raising a failure. Writing only at the end loses a created product's id when a later Etsy write fails, making the next run hit the duplicate guard. The incomplete marker keeps the listing dirty despite a newer lockfile mtime, clears on a clean run and stays outside hashed applied state.

First recorded 2026-09-17 in [commit c455e61](https://github.com/eli-jordan/etsy-listing-automation/commit/c455e616bc59c0340ab410d3c2b813bb61f466a3).
