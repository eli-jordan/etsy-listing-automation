# Marigold implementation stack

Status: execution contract, 2026-10-04. This expands the seven delivery stages in
[the plan](plan.md) without changing the [requirements](spec.md) or
[interaction contract](interactions.md). The [approved mockups](ui-mockups/README.md)
remain the UI reference. Each row below is one PR, based on the previous PR.

## Shared gates

| Gate | Exit condition |
| --- | --- |
| G1 | Targeted tests demonstrate each new behaviour through a public interface. Photo warp golden bytes remain unchanged. |
| G2 | Repository check script passes: formatting, lint, mypy, import contracts, Python and frontend coverage. Browser tests pass for available prerequisites; missing prerequisites are reported. |
| G3 | Changed HTTP contracts regenerate OpenAPI and frontend types. Core has no server/CLI dependency. No user data, secrets or weights enter the repository. |
| G4 | PR is open against its predecessor, registered with T3, and CI is green. The existing real-shop e2e workflow runs serially and its result is recorded. |
| G5 | UI changes are compared with approved mockups at 1280 by 800. The integrated feature is clicked through and its APIs spot-checked after all builders finish. Found defects are fixed on the lowest owning branch and propagated upward. |

All PRs require G1 through G4. PR5 and PR7 also require G5. The gates are evidence
requirements; a simulated worker cannot establish native model capability or
visual quality. Record actual measurements and failures honestly.

## PR scopes and exit conditions

| PR | Title and scope | Specific exit conditions |
| --- | --- | --- |
| 1 | Add renderer configuration and recoverable calibration storage. New kind/renderer models, stable multiple IDs, conventional masks, inactive settings and coherent save transactions; convert fixtures and existing readers/writers. | Old YAML is rejected; Photo warp still renders identical bytes; mask edits/Undo/Reset survive the specified cache/restart cases; revision conflicts and duplicate saves cannot overwrite newer state. Marigold configuration cannot silently render through Photo warp. |
| 2 | Add the native Marigold runtime and inference worker. Explicit setup/update/status, isolated pinned dependencies, complete installation lock, JSON-lines protocol, warm model lifecycle and cancellation. | Real Windows smoke inference succeeds for normals/lighting/depth; setup is explicit; worker protocol rejects unsafe/malformed artifacts; cancellation finishes the current call; idle exit and update compatibility work. Record practical limits rather than inventing success. |
| 3 | Prepare durable maps and render artwork on the CPU. Port crop/coverage, mask proposal, fitting, baking and composition, artifact validation and generation acquisition/publication. | Map roundtrips are validated and deterministic; both lighting modes and all appearance controls work without fitting; CPU-only rendering imports no torch; all placements use the correct maps and composition order. |
| 4 | Coordinate durable preparation jobs. Core queue, snapshots, deduplication, one GPU lane, one CPU lane, safe cancellation, resume/retry, stale result rejection and prediction cleanup. | Tests cover restart at publication/save checkpoints, edits during work, cancellation persistence, reference-aware cleanup and the complete required placement set. Save never starts GPU inference. |
| 5 | Integrate preparation and masks into the editor. Server contracts, status/SSE, renderer selection, settings, placement overlay, brushes, Save/Prepare, full-quality preview and errors. | Approved interactions work for all three kinds; reconnection starts no duplicate job; late preview responses are ignored; stale maps disable rendering with an actionable explanation; OpenAPI/types and browser tests cover the complete flow. |
| 6 | Integrate maps with listing checks and deployment rendering. Shared readiness facts, map content hashes, engine rendering and preview-byte promotion. | CLI/UI agree on refusals; missing/stale required maps block deployment; repeat apply is idempotent; cache deletion and compatible engine updates do not invalidate accepted renders; matching previews promote without re-rendering. |
| 7 | Validate integrated Marigold quality and performance. Full-resolution shared-colour comparisons, every multiple placement, native memory/latency/cancellation measurements and corrective fixes. | Record real results for all release gates, including unsuitable photos. Complete independent UI click-through and API spot checks. No feature is declared ready from mock evidence alone. |

The first builder branches from the committed design/stack contract. Each next
builder branches from its predecessor's accepted build tip. Once another builder
uses a tip, add commits only; do not rewrite that predecessor. If finish fixes
arrive before a child freezes, rebase the child as instructed; otherwise propagate
fixes upward as new commits. Real-shop e2e access is serialized by the orchestrator.

There is no approved numerical diff-size cap. Report total diffstat, distinguish
generated contracts and fixtures from handwritten logic, and split an oversized
PR only if its scope can be preserved with explicit exit conditions. Never omit
a requirement to hit an invented line-count target.

## Delivery ledger

Record branch, worktree, agent, base/tip, PR URL and build/finish/check state as
work proceeds. The orchestration log is working state; delivery links belong in
this feature after the PRs open.

PR7 is [#135](https://github.com/eli-jordan/etsy-listing-automation/pull/135),
branch `stack/marigold-07-validation`, based on PR6 tip `126d0121`. Native
measurements and unsuitable-photo decisions are in
[quality validation](quality-validation.md). Local full and dedicated browser
gates pass; CI, independent integrated UI/API review and serial real-shop e2e
remain pending.
