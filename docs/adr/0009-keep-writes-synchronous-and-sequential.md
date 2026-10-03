# ADR-0009: Keep writes synchronous and sequential

Status: accepted.

Keep the core synchronous and execute apply stages strictly in order. Remote ids and successful writes must be available to the next stage, and concurrent writes would complicate recovery from partial failure. The original decision allowed bounded fan-out for read-only live fetches; the current planner walks stages sequentially because progress and dependencies follow pipeline order. Fan-out remains an option for independent reads, not a description of implemented behaviour.

First recorded 2026-09-03 in [commit 3959ee0](https://github.com/eli-jordan/etsy-listing-automation/commit/3959ee0c08172195bc726d81d2c98ed4a4f4efef).
