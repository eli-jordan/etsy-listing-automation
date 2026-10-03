# ADR-0029: Observe processing time without replacing inventory

Status: accepted.

Never call Etsy's `updateListingInventory`: it replaces the complete variant matrix owned by Printify, risking an unsellable listing. Processing profiles live on those offerings, while measured writes to `processing_min` and `processing_max` silently do nothing. Read and report processing-time drift instead of changing it. Printify applies the shop's profile on publish, so avoiding this full-replace endpoint has a small practical cost.

First recorded 2026-09-10 in [commit de9728e](https://github.com/eli-jordan/etsy-listing-automation/commit/de9728e46c88a8da0f59674f1c20831867f75ec9).
