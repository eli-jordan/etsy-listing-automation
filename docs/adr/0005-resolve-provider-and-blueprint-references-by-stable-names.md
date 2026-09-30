# ADR-0005: Resolve provider and blueprint references by stable names

Configuration names print providers and identifies blueprints by brand and model; cached catalog lookup resolves their API ids. A blueprint's title is readable context, not an identifier: live catalog checks found generic titles shared across brands and subject to change. Matching brand and model keeps human-authored configuration useful without relying on those titles.

First recorded 2026-09-03 in [commit 086df20](https://github.com/eli-jordan/etsy-listing-automation/commit/086df2096d7b293ccbad394c9891b661a9a194b9).
