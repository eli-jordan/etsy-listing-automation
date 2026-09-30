# ADR-0048: Dispatch batch AI through the existing runner

Use one UI-server dispatcher to start ordinary AI runs, round-robin across batches and bounded by `batch_ai.concurrency`; manual runs do not count against that batch limit. Conflicts stay queued, interrupted running rows return to queued on startup, and manual AI is refused while the listing has pending batch work. Reusing the runner preserves cancellation and streamed progress. The queue is process-local: it does not guard two UI servers sharing one workspace.

First recorded 2026-09-27 in [commit c963e78](https://github.com/eli-jordan/etsy-listing-automation/commit/c963e78aa65ea254ac02886421a1b1607cce8845).
