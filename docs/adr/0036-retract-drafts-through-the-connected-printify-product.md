# ADR-0036: Retract drafts through the connected Printify product

Status: accepted.

For remote deletion, mark the listing deleted, then apply only retraction: delete the still-connected Printify product and verify the Etsy listing returns 404 before removing local files. Unpublishing before deleting was measured orphaning the Etsy draft, whereas connected deletion cascaded correctly. If the draft remains, fail and keep the files for recovery. A listing with no remotes can be removed locally at confirmation.

First recorded 2026-09-16 in [commit 2d9911a](https://github.com/eli-jordan/etsy-listing-automation/commit/2d9911a4c603235b7157abfe7c086f078c0cb2b8).
