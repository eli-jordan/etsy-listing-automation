# ADR-0024: Share transport while separating client authority

Status: accepted.

Keep Printify catalog reads and shop-scoped writes in one package over one transport, exposing separate protocols to callers. The authority boundary belongs in the type a caller holds, not in duplicate HTTP plumbing. The previous package split had already produced retry drift between identical failures on reads and writes. Etsy follows the same pattern: separate shop and listing protocols over its shared transport.

First recorded 2026-09-09 in [commit 11ca448](https://github.com/eli-jordan/etsy-listing-automation/commit/11ca44836a93db3015da54d08cd4e8ceb4e9ba9e).
