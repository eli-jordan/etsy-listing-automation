# ADR-0035: Delete never-live listings; retire published ones

Deletion retracts local-only listings, Printify-only products and Etsy drafts. Once a listing has left draft, block deletion and use retirement to make it inactive while retaining its files and Printify product. This preserves sales history and the native order connection. Resuming can restore a previously published listing; it never activates a draft for the first time.

First recorded 2026-09-16 in [commit 2d9911a](https://github.com/eli-jordan/etsy-listing-automation/commit/2d9911a4c603235b7157abfe7c086f078c0cb2b8).
