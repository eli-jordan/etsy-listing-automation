# ADR-0047: Create ordinary listings from template snapshots

Status: accepted.

A listing template is reusable production configuration under `listing-templates/`, not a design-less listing or a live link. Batch creation stages at most 25 unique PNG designs for review, then snapshots the selected template into ordinary local listings. This keeps templates out of discovery and deploy and lets each created listing evolve independently. Templates, artwork and listings are workspace data; staging, batch progress and proposals are disposable cache. Batch creation queues AI but never deploys.

First recorded 2026-09-27 in [commit c963e78](https://github.com/eli-jordan/etsy-listing-automation/commit/c963e78aa65ea254ac02886421a1b1607cce8845).
