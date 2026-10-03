# ADR-0049: Keep the latest proposal in server cache

Status: accepted.

Store one proposal per listing with its input snapshot, generation time, origin and per-section acceptance or dismissal state. Persist it before emitting the proposal event and compute staleness on the server. Browser-local state and a short TTL would lose reviewable work on navigation or restart; stale proposals instead remain usable with a warning. Replacement, deletion, a fully successful apply or cache clearing removes the old proposal.

First recorded 2026-09-27 in [commit c963e78](https://github.com/eli-jordan/etsy-listing-automation/commit/c963e78aa65ea254ac02886421a1b1607cce8845).
