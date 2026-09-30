---
title: "Batch Creation — Thinking"
---

# Batch listing creation thinking — brief and flow from docs/features/batch-creation-20260927/spec.md (UNCONFIRMED: self-answered from the spec).

**Who / scene:** one print-on-demand seller at a laptop, focused, after exporting 5-25 finished designs (often a Kittl ZIP).

**One job:** turn a drop of finished PNGs into one reviewable local listing draft per design, without re-entering the product settings each time.

**Mode:** Operate.

**Flow:**
1. Listing editor → Save as listing template (once per product setup).
2. Listing templates → pick a template, or drop files straight onto its card.
3. New batch → drop one ZIP or loose PNGs; staging validates, dedupes and names.
4. Confirm → one local listing per valid row; the AI queue drafts brief + SEO proposal.
5. Batch summary → watch the queue, retry failures, open each listing, mark reviewed.
6. Open a listing from the summary → review and accept SEO copy, Back to batch.

**Content:** the spec, the existing Listings page, editor and batch-deploy vocabulary; fixture designs from a hiking-tee shop.

**Deliberate change from the spec:** no batch filter on the Listings table (the spec lists one); the batch summary replaces it.

**Out of scope:** deployment from the batch, per-row cancel, inbox folders, CLI, multi-template batches.
