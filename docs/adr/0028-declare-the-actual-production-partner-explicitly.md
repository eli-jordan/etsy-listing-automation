# ADR-0028: Declare the actual production partner explicitly

Use `who_made: someone_else` and attach a resolved production partner to the listing. Live writes failed without that attachment even when a partner existed at shop level. Resolve an explicit listing, profile or default partner, then fall back only to the shop's sole partner; report candidate names and locations otherwise. Deriving it from the Printify provider would fail because Etsy's partner can have a deliberately generic name.

First recorded 2026-09-10 in [commit de9728e](https://github.com/eli-jordan/etsy-listing-automation/commit/de9728e46c88a8da0f59674f1c20831867f75ec9).
