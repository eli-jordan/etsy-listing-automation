# Batch deploy UI implementation plan

Status: approved implementation design.

This plan turns the settled interaction design in
[ui-batch-deploy-interactions.md](ui-batch-deploy-interactions.md) and the
frames in
[`src/etsy_listings/ui/frontend/design/scenes/batch-deploy-lofi/`](../src/etsy_listings/ui/frontend/design/scenes/batch-deploy-lofi/)
into the workspace-wide equivalent of `plan --all` and `apply --all`.

It is subsidiary to [prd.md](prd.md) and
[implementation-plan.md](implementation-plan.md). The PRD wins if they
disagree. The implementation decision settled while writing this plan is A34:
planning has a first-class workspace scope resolved by the server; applying
uses the exact names and fingerprints from the reviewed plan.

## Outcome

The Listings page gains a **Deploy changes** entry showing local candidate
counts. Activating it starts a fresh server-resolved workspace plan and opens a
stable run URL. The review page then:

- shows planning and preview progress without exposing partial totals as final;
- groups the authoritative plans into Add, Change, Remove and Needs attention;
- aggregates stage progress without implying parallel writes;
- opens the existing per-listing step strip and buyer-facing comparison in a
  modal bottom drawer;
- applies exactly the reviewed plans, one listing and one stage at a time;
- survives navigation and browser reloads by replaying recorded run events;
- preserves successful work when another listing fails or goes stale; and
- refreshes listing statuses after the run instead of predicting them in the
  browser.

This work does not add process-restart persistence. A33 deliberately keeps UI
runs in memory until Phase 6's shared SQLite recorder exists. “Leave and come
back” therefore means while the UI server remains running, exactly as it does
for the individual deploy page.

## Existing foundation

Most of the hard behavior already exists and should be reused, not rebuilt.

| Existing module | What batch deploy gets from it |
|---|---|
| `engine.run.plan_listings` / `apply_listings` | All-listing iteration, continue-on-user-error, sequential writes, lockfile ownership and A31 fingerprint checks. |
| `engine.RunObserver` | Per-listing and per-stage planning/apply events. No batch-specific engine callbacks are needed. |
| `ui.runs` | FIFO execution, listing locks, event buffers, SSE replay, cancellation and unseen results. |
| `PlanDTO` / `StagePlanDTO` | The same plans, snapshots, changes, drift and blocked messages used by individual deploy. |
| `deployState.ts` | The event vocabulary and per-stage runtime semantics. Batch needs a collection-level projection over it, not a second interpretation of events. |
| `comparison.ts`, `ComparisonView`, `PriceTable`, `StepStrip` | The established individual-listing explanation of a plan. The drawer composes these modules unchanged apart from narrowing `ComparisonView`'s listing context. |
| preview rendering and promotion (A32) | Reviewable full-size images and byte-identical promotion during apply. Preview keys must become listing-scoped in batch state. |
| `GET /api/listings` | Local candidate counts, display names/design context and the post-run status refresh. |

The deletion test for the new batch module is useful here: deleting it should
put event aggregation, grouping, result classification and reattachment logic
back into the page and its visual children. It must not put diffing or stage
execution into the browser.

## Architecture

```text
ListingsPage
  -> POST /api/runs {kind: plan, scope: workspace}
  -> /listings/deploy/{plan-run-id}
       -> GET RunDetail + replay SSE
       -> batchDeployState(events)
       -> aggregate stages + grouped listing rows
       -> listing drawer
            -> buildComparison(plan)
            -> StepStrip / ComparisonView / PriceTable
       -> POST /api/runs {
            kind: apply,
            scope: workspace,
            listings: reviewed ordered names,
            expect: reviewed fingerprints,
            reviewed_run_id: plan-run-id
          }
       -> replace URL with /listings/deploy/{apply-run-id}
       -> replay reviewed plan run + stream apply run
       -> refresh GET /api/listings on terminal result
```

There are two important seams:

1. The runs HTTP interface owns scope, conflicts, identity and replay. It does
   not plan or apply; the existing executor still calls the engine.
2. The frontend batch-state interface accepts a reviewed plan event log and an
   optional apply event log, and returns one renderable batch view. Pages and
   visual modules do not fold events independently.

### A34: workspace scope and a frozen apply set

The current `CreateRunRequest` requires `listings: string[]`. That is correct
for the individual editor, but wrong for `plan --all`: the browser's table can
be stale or filtered and must not define the workspace.

Add a discriminated run scope:

```json
{
  "kind": "plan",
  "scope": "workspace"
}
```

For this request the server calls `Workspace.listing_names()` as it accepts the
run and stores the sorted resolved names on `Run.listings`. An empty workspace
is a valid plan that reaches `ready` and renders **Everything is up to date**.

Apply is also marked `scope: "workspace"` so it is discoverable as the current
batch run, but it does not resolve the workspace again:

```json
{
  "kind": "apply",
  "scope": "workspace",
  "listings": ["after-rain-trail", "mountain-sunrise-tee"],
  "expect": {
    "after-rain-trail": "...",
    "mountain-sunrise-tee": "..."
  },
  "reviewed_run_id": "..."
}
```

The server loads the referenced ready plan run and validates that `listings`
and `expect` exactly match its ordered `listing_planned` events. Listings whose
planning ended in `listing_failed` have no fingerprint and are shown under
Needs attention, but are not apply targets. Blocked or clean plans do have a
fingerprint and remain in the checked set; they execute no stages unless the
fresh re-plan disagrees, in which case A31 marks them stale rather than allowing
new work through silently.

`reviewed_run_id` is also needed for reload correctness. An apply run re-plans
listings one at a time, so its event log does not yet contain plans for later
listings. On reload, the page reconstructs the approval surface from the linked
plan run and overlays apply progress from the current run.

### Locking and discovery

`Run` gains `scope`, `reviewed_run_id` and timestamps. `RunRegistry` keeps a
latest workspace-scoped holder in addition to its per-listing holders.

- Creating a workspace run conflicts with any queued/running listing run.
- Creating a listing run conflicts with a queued/running workspace run.
- A batch plan at `ready` is terminal and holds no execution lock; edits and
  other runs may happen, and A31 detects the resulting stale plan at apply.
- Creating the batch apply supersedes the batch plan as the current workspace
  run, while the plan remains addressable by id for replay.
- `GET /api/runs?scope=workspace` returns the current batch run for the
  Listings-page progress/result affordance.

A `409` continues to name the conflicting run. A batch entry can reattach when
that run is workspace-scoped; when it is an individual run, the UI explains the
conflict and links to that listing's deploy page.

### Stable run routes

Use `/listings/deploy/{runId}`, not a route that guesses which run to open.

- The Listings-page control creates the plan first, then navigates to its id.
- Reload fetches that exact run and resumes after the last recorded event id.
- Starting apply replaces the URL with the apply run id.
- The Listings-page **View progress/result** affordance gets the id from the
  workspace run summary.

This avoids a race between “start fresh” and “reattach”, and avoids making the
`seen` flag decide which plan a URL means.

## Backend changes

### Run models and validation

Extend the existing run models rather than adding a batch endpoint:

- `RunScope = Literal["listings", "workspace"]`;
- `CreateRunRequest.scope`, defaulting to `listings` only during the migration
  of existing callers;
- `Run.scope`, `Run.reviewed_run_id`, `Run.created_at`;
- `RunSummary.scope`, `reviewed_run_id`, `created_at`;
- a timestamp on phase events so “planned just now” and result times survive
  replay; and
- request validation for the legal plan/apply shapes.

The runs adapter resolves workspace plans and validates reviewed applies before
calling the registry. The registry remains the owner of conflict/retention
state; the executor remains the only module that invokes the engine.

No engine `Plan`, stage protocol, snapshot or fingerprint format changes are
required.

### Event behavior

The existing event union is sufficient. Batch UI uses:

- `stage_checking` for a compact current-planning message;
- `listing_planned` as the authoritative complete plan and fingerprint;
- `preview_rendered`, keyed by listing + template + colour;
- `stage_applying` / `stage_applied` / `stage_failed` for aggregate and row
  progress; and
- `listing_failed.stale_plan` to distinguish stale from other failures.

Incomplete `stage_planned` events may animate planning but never contribute to
the final Add/Edit/Remove totals.

## Frontend state and presentation

### One pure batch projection

Add `pages/batchDeploy/batchDeployState.ts` with a small interface along these
lines:

```ts
batchDeployState(reviewEvents, applyEvents?): BatchDeployState
applyBatchRunEvent(state, event, source): BatchDeployState
```

It owns:

- the plan and fingerprint per listing;
- plan-time failures with no plan;
- listing-scoped preview readiness;
- applying/applied/failed runtime per listing and stage;
- the current listing and stage;
- terminal success, partial success, stale and failure counts; and
- the generated/result timestamps from phase events.

The reducer stores engine answers; it does not compare desired and live values.
All change highlights continue to come from `ChangeDTO` through
`buildComparison` (A2/A30).

Add a second pure presentation module for projections that are useful to more
than one visual child:

- candidate Add/Edit/Remove names from `ListingSummary`;
- plan group (`add`, `change`, `remove`, `attention`);
- buyer-facing impact summary from `buildComparison(plan).impacts`;
- aggregate stage order and counts; and
- per-listing stage totals and progress.

Grouping rules for successfully planned listings are deliberately small:

- any returned `retract` stage -> Remove;
- otherwise no Etsy listing id -> Add;
- otherwise -> Change;
- no runnable stage plus a block, or a plan-time failure -> Needs attention.

Needs attention is an exception group, not a fourth change type and not part of
the Apply count.

For aggregate order, take the returned order from a normal multi-stage plan,
append previously unseen stage names as encountered, and place a disjoint
retract-only lifecycle stage after the normal pipeline. This preserves future
stages without assuming every listing has today's five-stage pipeline.

### Reuse the individual review

The drawer must compose the existing `StepStrip`, `ComparisonView` and
`PriceTable`. Do not create batch variants of their diff vocabulary.

Narrow `ComparisonView` from an entire `ListingDetail` to the two facts it
actually uses (`name` and `design`). The individual page supplies those from
its detail; batch supplies them from the listings summary, with a name-only
fallback for a listing removed during apply. This improves the module's
interface and avoids one detail request per row.

The drawer should use the native `<dialog>` modal behavior, styled as the
bottom sheet in the mockup. It provides background inertness, focus trapping
and Escape semantics; the implementation adds focus restoration, scrim-click
dismissal, independent body scrolling and reduced-motion handling. Apply
closes the drawer before creating the run.

### Listings entry and run affordance

The candidate popover is an orientation aid derived only from the already
loaded listing summaries:

- Add: draft with no Etsy listing id;
- Edit: dirty, a draft with an Etsy id, or a pending lifecycle change;
- Remove: pending-delete.

It remains available with no badges so the seller can check remote drift. The
popover appears on both hover and keyboard focus.

The page also asks for the current workspace run:

- active apply -> **Deploying... View progress ->**;
- unseen applied result -> **Deployed - View result ->**;
- unseen failed/stale result -> **Deploy failed - view**;
- otherwise -> **Deploy changes** with candidate counts.

After a terminal batch result, both the review page and Listings page refetch
`GET /api/listings`; neither guesses the new lifecycle statuses.

## Result rules

The frontend derives results only from the reviewed plans and run events:

- A listing succeeds when every runnable reviewed stage has a matching
  `stage_applied` and it has no `listing_failed` event.
- A listing fails when `listing_failed` has no `stale_plan`.
- A listing is stale when `listing_failed.stale_plan` is present.
- Completed stage counts never decrease after a later failure.
- A terminal apply with both successes and failures is partial success, even
  though the run phase is `failed`.
- **Plan again** always starts a fresh workspace plan; it never patches the old
  event log or retries only a browser-selected subset.

The aggregate stage tile denominator is the number of reviewed listings whose
plan says that stage `will_run`. Blocked and skipped stages remain visible in
the listing drawer but do not inflate `N`.

## Testing strategy

Tests follow the existing split.

### Unit and frontend unit

- request-shape validation and A34 target resolution;
- workspace/listing conflict behavior in both directions;
- exact reviewed-set validation, including omission, extra name, wrong
  fingerprint and missing/unfinished source plan;
- batch event folding from replay and live events produces identical state;
- preview keys do not collide across listings using the same template/colour;
- grouping, impact summaries, stage union/order and progress counts;
- partial success and mixed stale/failure outcomes;
- candidate counts with zero-count availability; and
- modal focus restoration, Escape, scrim and independent scrolling hooks.

### Behaviour and contract

- workspace scope uses `Workspace.listing_names()` rather than a client list;
- one bad listing does not stop later plans or applies;
- writes remain in listing/stage order;
- a listing created after review is not applied;
- a reviewed clean or blocked listing that changes becomes stale;
- reload can fetch the linked review run while apply has not reached later
  listings; and
- OpenAPI generation exposes scope, linkage, timestamps and the unchanged
  event union.

### Browser

Use the built SPA and injected fake clients to cover one complete batch:

1. Listings shows candidate names and counts on hover and focus.
2. Starting deploy reaches the planning state and then authoritative review.
3. Opening a row traps focus and shows the same comparison/step vocabulary as
   individual deploy.
4. Apply closes the drawer and advances sequential aggregate/listing progress.
5. Navigate back during apply, follow **View progress**, and reattach.
6. Finish with one success and one failure/stale result; inspect both drawers.
7. Plan again and reach the remaining-work review.

A smaller browser case covers the no-changes result. Component tests carry the
larger state matrix so browser tests remain observable end-to-end checks rather
than an exhaustive state machine.

## Pull request plan

Every estimate includes production code, generated schema changes, tests and
documentation. The upper bound stays below 3,000 changed lines.

### PR 1 — `feat(runs): add workspace-scoped reviewed runs`

Estimated change: 1,000–1,600 lines.

Scope:

- implement A34 request/summary models, timestamps and `reviewed_run_id`;
- resolve workspace plan names server-side;
- add workspace-vs-listing conflict and current-workspace-run lookup;
- validate batch apply against the linked ready plan's exact names and
  fingerprints;
- retain the linked plan for apply replay;
- update contract, registry and executor behavior tests;
- regenerate the TypeScript schema; and
- land A34 in the architecture log.

Validation: targeted Python unit/behavior/contract tests, OpenAPI generation,
ruff and mypy for touched modules, frontend typecheck for the generated types.

Dependencies: none. This is the sequential foundation for every later PR.

### PR 2 — `refactor(deploy): add the pure batch run projection`

Estimated change: 900–1,400 lines.

Scope:

- add batch event folding and presentation projections;
- cover grouping, aggregate stages, listing-scoped previews and result math;
- narrow `ComparisonView` to its actual listing media context; and
- add Vitest coverage without mounting the final page.

Validation: frontend unit tests, typecheck, lint and coverage.

Dependencies: PR 1's generated run types. Can be developed in parallel with
PR 3 after PR 1 lands.

### PR 3 — `feat(batch-deploy): productionize the batch review modules`

Estimated change: 1,200–1,900 lines.

Scope:

- turn the mock's candidate control, aggregate strip, grouped rows and bottom
  drawer into production modules using design tokens;
- compose the existing individual `StepStrip`, `ComparisonView` and
  `PriceTable` in the drawer;
- implement native-dialog accessibility, responsive layout and reduced
  motion; and
- test visual states and interactions with fixture plans.

Validation: frontend unit/component tests, typecheck, lint and coverage.

Dependencies: PR 1 for final types. It touches new presentation files and can
be developed in parallel with PR 2.

### PR 4 — `feat(batch-deploy): plan and review all listings`

Estimated change: 1,600–2,400 lines.

Scope:

- add the stable `/listings/deploy/{runId}` route;
- wire plan creation, conflict handling, detail replay and SSE reattachment;
- mount the Listings-page candidate control and current batch affordance;
- render planning, preview, review, blocked and nothing-to-do states;
- keep Apply disabled until every required preview is ready; and
- add server-backed integration/component tests for review and reload.

Validation: targeted Python contract tests, frontend tests/typecheck, and a
browser planning/review case.

Dependencies: PRs 1, 2 and 3. Sequential integration point.

### PR 5 — `feat(batch-deploy): apply reviewed plans and report results`

Estimated change: 1,500–2,400 lines.

Scope:

- create the linked workspace apply run and replace the route run id;
- overlay apply events on the preserved reviewed plan after live updates or a
  reload;
- implement aggregate/listing progress, back-without-cancel, partial success,
  stale, failure, unseen result and Plan again states;
- refetch listing statuses after completion;
- add the full browser scenario, including leave/reattach and continue-on-error;
  and
- update the interaction document only if implementation uncovers a genuine
  contradiction, never to silently change settled behavior.

Validation: full targeted frontend and Python suites, both coverage gates,
browser tests, `uv run mypy src`, ruff, Prettier and the production frontend
build.

Dependencies: PR 4. Sequential final slice.

### Dependency graph

```text
PR 1: workspace run contract
   ├── PR 2: pure batch state ───────┐
   └── PR 3: presentation modules ──┤  parallel development
                                    v
                         PR 4: plan/review integration
                                    |
                                    v
                         PR 5: apply/results/recovery
```

PRs 2 and 3 are the only parallel pair. PR 1 must land first because it fixes
the wire types. PR 4 must merge their two interfaces, and PR 5 must build on
the stable review route and its replay model.

## Definition of done

- Activating **Deploy changes** never sends the browser's listing table as the
  definition of all listings.
- Apply cannot execute a listing or plan fingerprint absent from the linked
  review.
- Planning performs no Printify, Etsy, listing-file or lockfile writes; preview
  cache writes remain the A32 exception outside `build_plan`.
- Writes remain sequential and continue past user-facing listing failures.
- Reload and leave/return reconstruct the same review and progress from run
  events while the server remains alive.
- Batch and individual drawers render through the same comparison and step
  modules.
- No frontend module computes whether remote/local state changed.
- All new controls work by keyboard, the drawer is modal, and focus returns to
  its opener.
- Each PR stays under 3,000 changed lines and carries tests for the behavior it
  introduces.
