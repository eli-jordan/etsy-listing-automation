# ADR-0040: Promote matching full-size previews during apply

The UI plan run renders full-size previews into a separate preview cache after the read-only plan is built. Apply promotes a preview with the matching scene hash instead of rendering again, and retains it for refreshes during deployment. Pure rendering and exact dependency pins make promotion byte-equivalent to rendering. Downscaled previews would require paying for a second full render, while writing deployment outputs during planning would blur the review boundary.

First recorded 2026-09-17 in [commit c455e61](https://github.com/eli-jordan/etsy-listing-automation/commit/c455e616bc59c0340ab410d3c2b813bb61f466a3).
