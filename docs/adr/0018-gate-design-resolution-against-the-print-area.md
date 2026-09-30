# ADR-0018: Gate design resolution against the print area

A design must reach at least 90% of the garment profile's print area on each axis before deployment. Printify silently accepts dramatically undersized images, so API acceptance cannot protect print quality. Comparing pixel dimensions to the profile is more checkable than an approximate DPI statement, while the 10% tolerance avoids refusing small, visually harmless differences.

First recorded 2026-09-08 in [commit 869ab0e](https://github.com/eli-jordan/etsy-listing-automation/commit/869ab0e0e58dd438062de601b1ffd0fcde718ad0).
