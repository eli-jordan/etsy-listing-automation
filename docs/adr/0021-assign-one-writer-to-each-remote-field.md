# ADR-0021: Assign one writer to each remote field

Printify owns the variant matrix: colours, sizes, prices and SKUs are updated there and selectively republished with only variants enabled. Etsy API writes own buyer-facing copy, media and listing settings. Printify creates the connected listing once, but later variant updates must leave those Etsy-owned fields alone; otherwise one integration could silently undo the other's work.

First recorded 2026-09-08 in [commit 869ab0e](https://github.com/eli-jordan/etsy-listing-automation/commit/869ab0e0e58dd438062de601b1ffd0fcde718ad0).
