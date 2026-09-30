# ADR-0033: Resolve Etsy shop reference data once per run

Resolve sections, shipping profiles, production partners and return policies in memory once per run. These small shop-owned lists can change in Shop Manager, and a stale section id was measured failing the whole listing PATCH. A disk TTL cache suitable for Printify's catalog would therefore hide exactly the edits the next run needs to see. Filter deleted shipping profiles and include every candidate, including partner locations, in resolution errors.

First recorded 2026-09-10 in [commit de9728e](https://github.com/eli-jordan/etsy-listing-automation/commit/de9728e46c88a8da0f59674f1c20831867f75ec9).
