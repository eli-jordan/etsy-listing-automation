# ADR-0030: Choose variation images by an explicit template

Status: accepted.

Variation images are opt-in through a named colour-matrix template, rather than a boolean that lets media order choose swatches. Identify Etsy's colour property by its values and join slugified names to listing colours; property names and ids vary by blueprint. The media stage owns the links because it owns the image ids. Replaced images leave apparently healthy dangling links, so changed ids require re-asserting swatches and checking that linked images still exist.

First recorded 2026-09-10 in [commit de9728e](https://github.com/eli-jordan/etsy-listing-automation/commit/de9728e46c88a8da0f59674f1c20831867f75ec9).
