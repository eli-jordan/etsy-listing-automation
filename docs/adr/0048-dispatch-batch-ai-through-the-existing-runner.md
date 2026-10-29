# ADR-0048: Dispatch batch AI through the existing runner

Status: accepted.

Use one UI-server dispatcher to start ordinary AI runs, round-robin across batches and bounded by `batch_ai.concurrency`; manual runs do not count against that batch limit. Conflicts stay queued, interrupted running rows return to queued on startup, and manual AI is refused while the listing has pending batch work. Reusing the runner preserves cancellation and streamed progress. The queue is process-local: it does not guard two UI servers sharing one workspace.

First recorded 2026-09-27 in [commit c963e78](https://github.com/eli-jordan/etsy-listing-automation/commit/c963e78aa65ea254ac02886421a1b1607cce8845).

## Amendment 2026-10-29: stop batch generation after the brief

Batch-origin runs use the existing runner to draft an empty brief, then finish
with market research and SEO skipped. The seller can correct the saved brief
before starting AI Mode in the listing editor. Automatically researching and
generating suggestions first wasted that work whenever the brief needed editing.
Manual AI Mode keeps the full research and proposal chain and uses the current
saved brief.

Batch confirmation requires the brief prompt and a ready provider. Market
credentials and the research and SEO prompts are checked when AI Mode is
requested. Retry, Resume, and interrupted-row recovery remain brief-only and
preserve a brief already written, including seller edits. A successful batch row
means its brief is ready for review; it does not imply a proposal exists. Existing
cached proposals remain reviewable and are not removed by brief drafting.
