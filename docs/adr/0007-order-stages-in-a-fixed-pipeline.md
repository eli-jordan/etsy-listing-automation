# ADR-0007: Order stages in a fixed pipeline

The engine uses one `Stage` protocol and a fixed ordered stage list, with dependency expressed by position rather than a graph. A local stage has no remote state, but still reads its outputs on disk so a deleted cache is noticed during planning. Stages own their documents; entry points consume the engine's plans and reports.

First recorded 2026-09-03 in [commit 3959ee0](https://github.com/eli-jordan/etsy-listing-automation/commit/3959ee0c08172195bc726d81d2c98ed4a4f4efef).
