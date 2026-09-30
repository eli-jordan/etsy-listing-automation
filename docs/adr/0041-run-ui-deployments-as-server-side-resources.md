# ADR-0041: Run UI deployments as server-side resources

Status: accepted.

Represent a deployment run as an ordered listing set with one workspace-wide FIFO executor and listing locks. Stream a closed engine-event vocabulary through replayable SSE so a browser can reattach without starting another execution path. Commands, phases and stage outcomes are discriminated unions, preventing illegal flag combinations. Planning can stop between stages or preview submissions; apply is not cancellable. Runs remain in memory rather than claiming a durable history store.

First recorded 2026-09-17 in [commit c455e61](https://github.com/eli-jordan/etsy-listing-automation/commit/c455e616bc59c0340ab410d3c2b813bb61f466a3).
