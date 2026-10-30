# ADR-0005: Resolve provider and blueprint references by stable names

Status: accepted.

Configuration names print providers and identifies blueprints by brand and model; cached catalog lookup resolves their API ids. A blueprint's title is readable context, not an identifier: live catalog checks found generic titles shared across brands and subject to change. Matching brand and model keeps human-authored configuration useful without relying on those titles.

## Amendment, 2026-10-29

The catalog now names Comfort Colors as `Comfort Colors® Print on Demand`,
which breaks existing profiles naming `Comfort Colors®`. Blueprint resolution
treats these two brand spellings as aliases while still matching the model
exactly after case, spacing and trademark normalization. This explicit alias
preserves existing profiles without fuzzy brand matching or guessing from a
shared model number. Multiple matching blueprints still require human review.

First recorded 2026-09-03 in [commit 086df20](https://github.com/eli-jordan/etsy-listing-automation/commit/086df2096d7b293ccbad394c9891b661a9a194b9).
