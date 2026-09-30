# ADR-0003: AI proposes copy; the seller accepts it

AI Mode proposes title, tags and description lead for the seller to accept into ordinary listing fields. Generated suggestions do not enter the deployment lockfile or become remote writes: `plan` and `apply` consume only concrete saved copy. This keeps generation latency and non-determinism outside the idempotent engine.

## Amendments

The original generated-file lifecycle was replaced by field-level acceptance. Attaching artwork may draft an empty brief, which is an input rather than buyer-facing copy. Market research adds read-only Etsy calls and cached evidence; server-side AI runs outlive navigation. The latest proposal and its acceptance state now survive reloads in server cache; see [durable proposals](0049-keep-the-latest-proposal-in-server-cache.md).

First recorded 2026-09-03 in [commit 086df20](https://github.com/eli-jordan/etsy-listing-automation/commit/086df2096d7b293ccbad394c9891b661a9a194b9).
