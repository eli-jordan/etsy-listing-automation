# Test suite quality specification

Status: planned; implementation has not started.

The [test-suite audit](../../../reports/test-suite-audit.html) identifies tests
that give weak assurance, repeat setup unnecessarily, or bind to incidental
implementation details. This work improves those tests while preserving the
application's existing behavior. The [plan](plan.md) divides delivery into a
linear PR stack; [coverage-map](coverage-map.md) assigns every audit finding
and supporting recommendation to an owner.

Current feature specifications and [architecture](../../architecture.md)
continue to govern application behavior. This specification changes testing
requirements, not listing, rendering, deployment, pricing or AI policy.
Existing ADRs remain in force, particularly ADR-0010's layers, ADR-0012's
render contracts, ADR-0013's workspace boundary and ADR-0052's ownership.
An actual behavior change discovered during this work needs an explicit
requirement amendment before its implementation.

## Requirements

### T01 — A test protects a named behavior at a stable boundary

Expected results come from literal examples, independently justified
invariants or an explicit specification. A test must reject a plausible wrong
implementation of its named behavior. Asynchronous refusal checks wait for
the refusal to settle; gesture checks require actual emitted changes; smoothing,
cache recency, cache reuse and invalidation have discriminating oracles.
Tests that promise execution, fresh reads, pagination or byte compatibility
must observe those outcomes rather than only planning, unchanged input or
fixture construction.

### T02 — Removing an upper test preserves its rule and its wiring

A replacement records the removed case, the lower test protecting its rule,
and the retained witness for any distinct routing, lifecycle, persistence or
browser behavior. Put rule permutations at pure value/module interfaces when
that retains validation. Keep real HTTP/SSE decoding, real filesystem safety,
process cleanup, actual browser geometry/image decoding and release installation
where those boundaries are the subject. Case counts and branch coverage alone
do not prove equivalence.

### T03 — Hermetic tests control their environment and ordering

Workspace discovery tests explicitly arrange `ETSY_LISTINGS_ROOT`, independent
of the contributor's shell. Intentional environment-override tests and live
e2e retain their overrides. Competing operations establish entry and release
through bounded events at owned dependency boundaries, with cleanup and joins
in `finally`. Do not impose ordering with fixed sleeps, globally slow all YAML
serialization/path operations, or leave completion threads unjoined.

### T04 — UI clocks and promises are separate dependencies

Debounce, autosave, mark-seen, animation and deadline tests advance controlled
clocks and separately settle pending requests. Negative assertions run after
the relevant work can have completed. DOM cleanup still precedes mock restore;
pending timers and global shims are cleaned up. Ordinary typing, focus and
keyboard behavior uses realistic interactions; low-level events remain valid
for SVG/pointer/media operations unsupported by the interaction helper.

### T05 — Expensive artifacts are reused only when their inputs match

The three successful wheel consumers share one immutable real built artifact
prepared with stale assets. Missing-index and sdist-to-wheel cases retain
independent build inputs. Installation stays outside the checkout with Node
absent. Non-resolution stage cases use matched smaller synthetic design,
profile and catalog facts. Resolution boundaries and reviewed render goldens
remain independent; gates are never bypassed to make fixtures smaller.

### T06 — Rule setup does not run unrelated workflows

Proposal-cleanup conditions use typed engine values and small Stage-protocol
implementations, with actual removal/preservation witnessed through the shared
runner. Proposal HTTP mappings use valid saved proposals with correct input
snapshots rather than rerunning AI to seed every case. Lifecycle, generation,
restart, cancellation and one complete successful deployment remain covered.
Market-block formatting uses explicit `MarketResult` values alongside one
research-to-block golden.

### T07 — Per-pass goldens identify the guilty pass

Downstream displace, shade and export cases take deterministic fixed upstream
inputs. Warp has its own golden; complete composites still validate composition.
Review changed golden inputs and image diffs before regeneration. Never loosen
OpenCV/Pillow pins or generate expected bytes with the pass being tested.

### T08 — Support code models public dependency contracts

Share small typed builders, deferred promises and event gates where multiple
subjects need them. Overrides remain explicit in each scenario. AI doubles
recognize equivalent supported response schemas by content/shape and reject
unknown schemas; object identity does not select task behavior. Keep coherent
fake state, FIFO/exhaustion, actual no-write counts and meaningful HTTP payload
contracts. Do not introduce production task identifiers for a fake's convenience.

### T09 — Frontend geometry has a cohesive testable boundary

Move coordinate transformations used by calibration into a small pure module
consumed by `QuadEditor`, preserving the component's public props, gesture
anchoring, modifier behavior and callback routing. Rule matrices need no React,
identity CTM shims or global element-rectangle patches. Retain actual browser
screen-to-image projection, pointer and clipping witnesses. This is an internal
extraction, not a new interaction design.

### T10 — Deletions remove duplicate or unsupported obligations

Remove the audit's bounded DTO/fake/lockfile/ANSI duplicates, repeated parent
presentation checks and dead CSS/no-layout claims only with their stated
retained coverage. Keep actual defaults, frozen semantics, fake fidelity,
focus, swatches, output order, encoding and safety contracts. Reset promises
restoring the latest saved configuration; this work adds no no-refetch policy.
Provider-order rules belong below the browser, while any distinct fallback
warning still has a presentation witness. Lower-confidence alias/storage-only
cases are assessed individually and their keep/consolidate outcome is recorded.

### T11 — Screenshot artifacts have an honest role

The five screenshot-file-existence cases become opt-in manual capture artifacts,
not ordinary regression tests. A documented command still produces all five
scenes. Browser CI continues to require its real layer and never passes by
silently skipping it. Existing appearance contracts and decoded-image/persistence
checks remain. Automated visual baselines are outside this scope.

### T12 — Live tests arrange their own meaningful milestones

The failed-publish test itself proves unlock; no later case relies on it having
run. Phase 3 becomes a deliberate journey or independently valid prepared-state
assertions, retaining all nine meaningful milestones and cleanup. Remove the
never-set SKU and vendor-title trivia from the application gate. Pagination
gets explicit distinct pages through the client contract, and a meaningful
live smoke only where it adds provider validation. Preserve actual provider
shape verification, read-only market checks and persistent AI completion;
incidental progress notifications are not prescribed unless the public stream
contract requires them. All real-shop execution remains serial.

### T13 — Execution environments reflect actual dependencies

The eleven identified pure frontend subjects (172 audit-time cases) run in a
Node Vitest project without DOM setup. Hooks, storage/DOM and components remain
in jsdom; transport tests move only after checking their dependencies. The four
prototype cases have an explicit design-test command and still run in a
required verification job. Each test is collected exactly once, production
coverage remains aggregated and its 85% branch floor is unchanged. Real process
tests live in a behavior/process subject; pure CLI application cases move to
their core subject without moving terminal/picker concerns out of CLI.

### T14 — Evidence closes the work

Record baseline and final collection, dependency classification, wall time,
setup/call/teardown where available, and kept/replaced/deleted cases. Compare
matched workloads on the same machine/toolchain, using repeated focused runs
for the expensive targets and environment split. Keep the audit's exploratory
timings distinct from the execution baseline. No required speedup percentage,
numerical pyramid quota or blanket test deletion is imposed. All findings and
supporting recommendations close with implementation evidence or a documented
requirement-based retain decision; none vanish into an unnamed follow-up.

## Preserved UI and application contracts

[Interactions](interactions.md) states the unchanged UI promises.
[Mockups](mockups.md) links the existing design frames and requires a current
calibrator baseline where a historical frame does not represent the shipped
screen. API error tests describe the existing adapter accurately: this stack
does not silently change how a 500 is presented while fixing a misleading 404
test. Any conflict between present behavior and current requirements is handled
as an explicit amendment, not decided by renaming a failing assertion.

Idempotent second applies, safe retries, sequential writes, lazy credentials,
currency, path security, lockfile ownership, reviewed-plan fingerprints, SSE
replay, cancellation, restart recovery and full render composition remain
required. The audit's good-test examples are preservation constraints, not
candidates for broad consolidation.
