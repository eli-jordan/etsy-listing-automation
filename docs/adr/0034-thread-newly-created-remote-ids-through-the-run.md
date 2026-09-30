# ADR-0034: Thread newly created remote ids through the run

Pass the accumulating remote-id block to later stages while retaining the previous run's applied documents for comparison. A first apply must be able to publish and patch the product it just created rather than requiring another invocation to discover its ids. Outputs that do not yet exist remain pending during plan; apply hashes the bytes it actually uploads.

First recorded 2026-09-10 in [commit de9728e](https://github.com/eli-jordan/etsy-listing-automation/commit/de9728e46c88a8da0f59674f1c20831867f75ec9).
