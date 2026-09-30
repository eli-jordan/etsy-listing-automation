# ADR-0043: Save named listings even when incomplete

Naming a listing writes it even if garment, colours, prices, copy or media are not yet chosen. Incompleteness blocks deployment through shared validation, rather than withholding the file the seller asked to create. Malformed values still refuse a save with field errors. This separates an editable work in progress from a deployable listing and removes the former special case where choosing a price source controlled whether anything existed on disk.

First recorded 2026-09-24 in [commit 7886c6a](https://github.com/eli-jordan/etsy-listing-automation/commit/7886c6a31a4da70f40753bb72b3fda63ab006bb1).
