# Deploy changes

How the listing editor gets a **Deploy changes →** button: a real `plan`
against Printify and Etsy, a before/after review a buyer would recognise, and
an `apply` that runs exactly what was reviewed and streams its progress.

Subsidiary to [prd.md](prd.md) and [implementation-plan.md](implementation-plan.md),
in the same way [phase-3-etsy.md](phase-3-etsy.md) is: the decisions are
recorded there as **A29–A33**, and this document holds the reasoning, the
module-by-module shape and the build order that a row in a decision log cannot
carry. It is PRD 20's plan/apply runner, scoped to one listing from the editor.
Where it disagrees with the PRD, the PRD wins.

It builds two design artifacts into something that can ship:

| Artifact | What it settles |
|---|---|
| [Plan & Apply Designs](https://claude.ai/artifact/Jf4seY6sHQkCeuYcsYBCv1) | The mock: the editor with the new button, and the deploy view in three examples (changes pending, blocked, nothing to do). |
| [Deploy Changes Spec](https://claude.ai/artifact/9jxBwhRDnoZ4RuRACj3eP3) | The interaction: phases, control states, the unmocked failure cases, and why each element is there. |

The spec was written before its assumptions were checked against the engine.
Several did not hold. The gaps are listed first, because every decision below
is shaped by one of them, and the spec has been corrected to match
(see [Spec corrections](#spec-corrections)).

---

## What the spec assumed, and what is there

| The spec assumed | What the code does | Consequence |
|---|---|---|
| `plan` fans live reads out over a thread pool, so stages resolve out of order | A21 left the pool unbuilt; `build_plan` walks stages one at a time | Plan progress is reported in pipeline order (A33) |
| An endpoint can project `PlannedRun.states` into listing views | Stage types are erased (`AnyStage`); only the stage that produced a type looks inside it | Stages expose snapshots and the frontend composes (A30) |
| The live side has the listing's images | `EtsyMediaLive` keeps a `frozenset` of image ids; `ListingImage` drops the URL | `etsy_media` keeps rank and URL |
| A failed stage leaves earlier stages done, and Plan again continues | `apply_listings` writes the lockfile only after `execute` returns | Nothing is recorded, and PRD 48 then refuses the re-create (A29) |
| `apply` can be tied to the plan the user saw | `apply_listings` re-plans internally, blind to any earlier plan | A fingerprint and `expect` (A31) |
| The status pill turns Live after apply | A first apply leaves an Etsy **draft**; only a human activates (non-goal 1) | The pill is re-derived from the server |
| The below-cost refusal is the Printify product stage's | PRD 40's amendment put it in `publish`, whose `read_live` has `variant_costs` | The mock's blocked example belongs to `publish` |
| Drift can be shown by name | `Drift` carries ids; only the *last-applied* name is in the lockfile | `Drift` gains labels from the in-run catalog (A30) |
| There is somewhere to run a plan from the UI | No runs endpoint, no SSE, no executor exists | The runs resource (A33) |
| Browser tests can drive an apply | `create_app(workspace)` builds real clients through `connections` | The app factory takes a context factory |

---

## Decisions

### 1. A failed apply keeps what it did — A29

The deploy view's failure case says: steps before the failure stay done, and
Plan again continues from wherever the shop now is. The engine does not
support that today. `execute` folds each stage's result into a local
`Lockfile`, and `apply_listings` writes it only once `execute` returns. When
`etsy_listing` raises after `printify_product` created a product, the product
id is never recorded. The next plan sees no product and plans to create one,
and PRD 48's duplicate-create guard then refuses, because a product with that
title and description already exists. No re-run can get past that, from the
CLI or from the UI.

So `execute` takes a recording callback and calls it with the stamped, folded
lockfile after every stage that succeeds. `apply_listings` supplies one that
writes `state.lock.json`. When a stage raises, `execute` records the lockfile
it has so far, with `incomplete: {"stage": name}` set, and then re-raises.
`Lockfile.fold` stays the only place that merges, and the marker is set and
cleared through two methods beside `stamped`, never by hand.

The marker exists because of a second-order effect. `edited_since_apply`
compares mtimes, and a per-stage write makes `state.lock.json` newer than
`listing.yaml` partway through a deploy that then failed. Without the marker,
a listing whose Etsy copy was never patched would read as clean.
`listing_status` treats a set marker as **dirty**. That needs no new status
value and no change to the phase-5 status table, and the pill agrees with
the editor's *Deploy failed — view* affordance.

The marker lives outside `applied`, so it never enters `input_hash`. It is
omitted from the JSON when unset, so every clean lockfile stays byte-identical
to today's and `SCHEMA_VERSION` does not move. A retract that succeeds removes
the listing directory as it does now, so there is nothing to mark.

This lands first, as its own PR, because it is a correctness fix for the CLI
as much as a prerequisite for the UI.

### 2. Planning reports stage by stage, in pipeline order — A33, A21 stands

The spec's step strip resolves stages "in whatever order its read finishes",
justified by A3's thread pool. A21 deferred that pool, deliberately and on the
record, so it does not exist. We are not reopening A21 here: a pool buys
little with one live read per stage, and it would pull thread-safety work
into every client and the Etsy token refresh.

`plan_listings` gains observer callbacks that fire as `build_plan` walks the
pipeline: a stage starts being checked, a stage has resolved (its `StagePlan`,
snapshot included), and the listing's plan is complete. The strip shows the
spinner and read line on the stage being checked, and each stage resolves in
turn. The spec's wording is corrected, because a strip that pretends to fan
out would misrepresent the tool, which is the same thing the spec's own
rationale objected to.

The two existing sinks, `on_planned` and `on_failure`, become fields of one
`RunObserver` dataclass of no-op-by-default callbacks, alongside the new
plan-time ones and the apply-time ones in §7. The CLI passes the two it uses.
One parameter that grows beats a signature that gains a keyword per event.

### 3. Stages expose snapshots; the frontend composes the comparison — A30

The comparison needs every field, unchanged ones included, and a `Plan`
carries only changes. The spec's R1 had the plan endpoint project
`PlannedRun.states` into two listing views. That fails on two counts. The
states are `Any`, and `StageState`'s own contract is that only the producing
stage looks inside them; an API casting `state.live` to `Product` is coupled
to five internal types that the type checker cannot follow. And a listing
view assembled on the server is presentation living in the backend.

Instead each stage may implement

```python
def snapshot(self, desired: D, live: L | None) -> BaseModel | None: ...
```

returning a **public pydantic model of domain facts**, never layout.
`build_plan` calls it after `plan()` and stores the result on
`StagePlan.snapshot`. A stage without the method, or a blocked stage with no
desired document, has `None`.

| Stage | Snapshot | Why this stage |
|---|---|---|
| `render` | per scene: `{scene, template, colour?, state: cached \| stale \| missing, preview: bool}` | Only it knows which scenes will re-render |
| `printify_product` | `desired` and `live` variants: `{size, colour, price}` | Variant id → size/colour needs the resolved matrix, which only it holds |
| `publish` | `below_cost: [{size, colour, price, cost}]` | Uses its own `_below_cost`, so the price table's red marker is not a second copy of the rule |
| `etsy_listing` | `desired` and `live`: `title`, `tags`, `shop_section`, `shipping_profile` | Already holds both documents |
| `etsy_media` | `desired: [{rank, ref, file}]`, `live: [{rank, image_id, ref?, url}]` | `ref?` maps a live id back through `lock.remote`'s image ids, the way A27 already does |

The frontend turns these facts into the two columns, the price table and the
thumbnails, and decides every visual treatment. The CLI ignores snapshots.

Snapshots are **excluded from the fingerprint** (§5). They carry Etsy CDN
URLs and preview availability, which can change between two plans that are
otherwise the same.

**"On Etsy now" images** use the live `url` (Etsy's `url_570xN`). This works
for drafts, which have images on Etsy, and for images uploaded by hand in Shop
Manager. When an entry has no URL, the tile falls back to the local render for
its `ref`. A listing with **no Etsy listing id at all** gets a single "After
apply" column with a *Not on Etsy yet* note. If a Printify product already
exists, its live variants still fill the price table's before side.

### 4. Highlights come only from `Change` objects — A30, A2

A2 does not move: the frontend never works out *whether* something changed.
Snapshots make unchanged context drawable, but every tint, badge and `+`
comes from a `Change`. Three places emit what they did not before:

| Emission | Where | Replaces |
|---|---|---|
| `ListChange("colors", added, removed)` | `product_diff._changes` | The UI diffing two colour lists to ring a new colour (R2) |
| One `MediaChange(rank, before, after)` per rank that differs | `etsy_media.plan` | A single "manifest changed" reason, from which *New / was 2 / Removed* badges cannot be drawn |
| `Drift.last_applied_label` / `live_label` | `etsy_listing._drift`, from the `EtsyShopCatalog` A25 resolved this run | The API fetching shipping profiles again to name an id (R3) |

`MediaChange` already exists in `engine/change.py` and has no emitter. The
drift labels are optional and default to `None`, so `publish`'s and
`product_diff`'s drift is unaffected. The CLI renderer prints a label in
place of the raw id when one is present, which improves `plan` in the
terminal at no extra cost.

The title's word-level marking still formats one `FieldChange`'s own before
and after and compares nothing else, as the spec already argues.

### 5. Apply refuses a plan nobody reviewed — A31

`engine/run.py` gains `plan_fingerprint(plan: Plan) -> str`: `canonical_hash`
over a canonical dict of the `Plan` (money as strings, tuples as lists), with
every `StagePlan.snapshot` removed. `apply_listings` takes an optional
`expect: Mapping[str, str]`. For each listing it re-plans exactly as it does
today, compares the new fingerprint with the expected one, and on a mismatch
raises a `StalePlanError` (a `UserFacingError`) carrying the new `PlannedRun`,
**before `execute` is called**. PRD 16 applies, so in a many-listing run the
next listing still goes ahead.

The check lives in the engine because only the engine runs a run. An API
comparing hashes would be a second implementation of "is this the plan you
saw".

Hashing the whole plan, drift and `actions` included, is deliberate. If Etsy
drifts between review and apply, the apply would revert something the user
never saw reverted. A preview being rendered in between does not change the
fingerprint, because preview existence never enters a `Plan` (§6).

### 6. Previews render during plan, and apply promotes them — A32

The "After apply" column should show the images apply will upload, including
scenes that have not been rendered yet. A plan must stay read-only for the CLI
and for the lockfile, and a full-size render takes seconds per scene.

`RenderStage` gains `preview(ctx, desired, live, *, should_stop)`. It renders
every scene whose snapshot state is `stale` or `missing`, full size, through
the same code path `apply` uses, to
`Workspace.preview_file(listing, template, colour, scene_hash)`, which sits
under `.cache/previews/{listing}/{template}/`. `scene_hash` is a new per-scene
hash over the inputs `input_hash` already folds (the artwork hashes that scene
uses, its template's hash, its resolved `RenderConfig`), restricted to that
scene. A preview that already exists for the current hash is not rendered
again. Files for this listing whose hash is no longer current are pruned in
the same pass. At most two full-size scenes render concurrently (bounded to
avoid multiplying their substantial image-array memory), and `should_stop` is
checked before each new submission. A cancelled plan drains only the small
batch already in flight (§7).

`RenderStage.apply` looks for the preview file for each scene it is about to
render. If one exists its exact bytes are copied into `render_file(...)`;
otherwise the scene renders as today. The content-addressed preview stays in
place so a deploy page refreshed during later apply stages can still display
the reviewed image. Render passes are pure and OpenCV and Pillow are pinned
exactly (A7), so a promoted file is the same bytes a fresh render would have
produced. The `outputs` hash axis cannot tell the difference, and nothing is
uploaded twice. CLI `apply` gets promotion for free whenever a UI plan ran
first. `Workspace.remove_listing` also removes
`.cache/previews/{listing}/`.

Previews are **not** part of `build_plan`. The UI's plan run calls
`preview_listing(ctx, planned, observer, should_stop)` in `engine/run.py`
after the plan is complete. It finds the render stage's state and asks it,
and the stage is still the only thing that understands its own types.

On the page, the review appears as soon as the plan resolves. Tiles whose
preview is pending show a spinner and fill in on each `preview_rendered`
event. **Apply stays disabled until previews finish**, with the footer note
*Rendering previews (2 of 4)…*, which is what guarantees apply promotes rather
than renders.

A preview is served by `GET /api/listings/{name}/previews/{template}[/{colour}]`,
resolved through `Workspace.preview_file` and the current snapshot's hash,
never through a path from the URL, because the layout accessors are the
security boundary.

### 7. Runs live in the UI server — A33

A run is the unit the UI starts, watches, reattaches to and, for a plan,
cancels.

```
POST   /api/runs              {kind: "plan"|"apply", listings: [name], expect?: {name: fp}}
                              -> 202 RunSummary | 409 {active_run: id}
GET    /api/runs?listing=     active and recent runs for a listing
GET    /api/runs/{id}         RunDetail: phase, listings, events so far
GET    /api/runs/{id}/events  text/event-stream; replays after Last-Event-ID
DELETE /api/runs/{id}         cancel a queued or running plan; 409 for apply
POST   /api/runs/{id}/seen    the result of a finished run has been looked at
```

**Many listings in the backend, one from the editor.** `listings` is a list
from the start, and PRD 16's continue-on-error holds inside a run because the
run calls `plan_listings`/`apply_listings`, which already do. The editor
always sends one. A batch runner later changes the frontend, not the API.

**Locks per listing, one executor across the workspace.** Creating a run
takes a lock on every listing it names. If any is already held by an active or
queued run, the request is refused with `409` and the holder's id, which the
editor uses to reattach instead. Locks are released when the run finishes,
fails or is cancelled. Runs execute on **one** FIFO executor thread, so a run
for another listing waits in a `queued` phase (*Waiting for another run…*).
Serial execution keeps A3's strictly-sequential writes and sidesteps Etsy's
refresh-token rotation racing itself. Raising the worker count later is the
whole of parallelising, because the lock model is already per listing.

**Run phases.** `queued → planning → planned → previewing → ready` for a plan
run (`previewing` is skipped when no scene needs one), and
`queued → applying → applied | failed` for an apply run. `stale` is an apply
run refused by §5, and its event carries the new plan. `cancelled` is a plan
run whose `DELETE` landed. Every run ends in exactly one terminal phase.

**Events.** Each event is a pydantic model in one discriminated union,
`RunEvent`, with a monotonically increasing `id` per run:

| Event | Carries | Emitted by |
|---|---|---|
| `phase` | run phase | registry |
| `stage_checking` | listing, stage | `RunObserver`, plan walk |
| `stage_planned` | listing, serialised `StagePlan` (snapshot included) | `RunObserver` |
| `listing_planned` | listing, `Plan`, fingerprint | `RunObserver` |
| `preview_rendered` | listing, template, colour | `RunObserver` via `preview_listing` |
| `stage_applying` | listing, stage | `RunObserver`, from `execute` |
| `progress` | listing, stage, message, swatches | `ctx.emit`, tagged with the running stage |
| `stage_applied` | listing, stage | `RunObserver` |
| `stage_failed` | listing, stage, message | `RunObserver` |
| `listing_failed` | listing, message, `stale_plan?` | `RunObserver.on_failure` |

`ctx.emit`'s existing `Event(message, swatches)` stays as it is. The executor
builds the run's `RunContext` with an `on_event` that tags each message with
the stage the observer last reported, so no stage changes how it reports
progress.

A `UserFacingError` reaches the page word for word, keeping one message for
the CLI and the UI. Anything else ends the run `failed` with *Internal error,
see the server log*, and the traceback is logged. That is still a defect, and
it still gets a traceback.

**Typing the stream (A5).** `RunDetail.events: list[RunEvent]` puts the union
into `openapi.json`, so `gen:api` generates every event type. The SSE route
sends the same models serialised as JSON. The only hand-written client code is
`runStream.ts`, a typed wrapper around `EventSource` that parses into those
generated types. No new Python dependency is needed: the route is a
`StreamingResponse` over the run's event buffer, woken by a
`threading.Condition` bridged to the event loop.

**Contexts are injected.** `create_app(workspace, *, context_factory=connections.run_context)`.
The executor builds each run's `RunContext` through the factory, so
credentials still resolve lazily (a plan in a workspace without Etsy still
blocks cleanly), and browser tests pass one wired to the in-memory fakes.

**Shutdown.** The executor thread is not a daemon. On shutdown (the native
window closing, Ctrl-C on `ui --browser`) a stop flag is set: a queued run is
cancelled, a plan run stops at its next boundary, and an apply run finishes
the stage it is in, which records itself (A29), and starts no other. The
native window's close handler shows *Finishing Etsy listing…* until the thread
joins. Runs are in memory only, so a restart forgets them, and history stays
Phase 6's `runs/` SQLite recorder.

**Retention.** A finished run is kept until the next run for any of its
listings is created. That is enough to reattach after a reload, and to show
*Deployed ✓ View result →* until the result has been seen.

### 8. Back leaves; it never cancels an apply

The spec disabled Back during apply, so that it would not suggest a cancel that
does not exist. Reattachment makes a different answer honest: **Back is
enabled in every phase.** During planning or previewing it sends
`DELETE /api/runs/{id}`, and the plan is discarded as the spec says. During
apply it only navigates, and the apply carries on.

The editor tells you so. `ListingEditorPage`'s page head asks
`GET /api/runs?listing=` on mount and swaps its button:

| Run state for this listing | Page-head control |
|---|---|
| none, or finished and seen | **Deploy changes →** |
| queued / applying | **Applying… View progress →** |
| applied, not seen | **Deployed ✓ View result →** |
| failed or stale, not seen | **Deploy failed — view** |

Each link opens `/listings/:name/deploy`, which reattaches. The deploy view
marks a finished run seen when it renders that run's result. The browser's
*leave site?* prompt is dropped, because nothing is lost by leaving.

### 9. Routing and reattaching

The deploy view is a route, `/listings/:name/deploy`, rendered inside
`AppShell` like the editor. On mount it asks `GET /api/runs?listing=`:

1. An **active** run (queued, planning, previewing or applying): fetch
   `RunDetail`, rebuild the view from its events, then open the SSE stream
   with the last event id.
2. A **finished, unseen** run: rebuild from `RunDetail` and show its result.
3. Otherwise: save any pending autosave, then `POST` a plan run.

**Deploy changes →** navigates to the route, and the route performs the save
itself, so a reload cannot skip it. Back, and the breadcrumb, navigate to
`/listings/:name`. The editor re-fetches its `ListingDetail` on mount, which
is local and fast, so the spec's instant return holds without keeping the
editor mounted behind the route.

### 10. Status after apply is re-derived

When an apply run ends, the view re-fetches `ListingDetail` and shows the
`status` the server derives. A first deploy leaves an Etsy draft (non-goal 1),
so the pill reads **Deployed**, not Live. A failed deploy reads **Dirty**
(§1).

The applied phase's single "On Etsy now" column is the reviewed plan's
*after* side, relabelled, not a fresh read. The run applied exactly that plan
(§5), so the column states what was sent. Checking what Etsy did with it is
the next deploy's plan.

### 11. Lifecycle deploys use the same view

The editor's status control can mark a listing to retire, delete or renew, and
all three go through `plan`. Nothing in the view hard-codes five stages. The
step strip draws `plan.stage_plans` as returned, so a `deleted` listing shows
the one `retract` stage, and a listing-level block (`_all_blocked`) shows
every stage with one refusal. After a successful retract the listing
directory no longer exists, so the applied footer's only button is
**← Back to listings** and goes to `/listings`. Renew and retire are ordinary
deploys.

---

## Engine changes, by module

| Module | Change | Decision |
|---|---|---|
| `engine/lock.py` | `incomplete: IncompleteApply \| None`, omitted when `None`; `marked_incomplete(stage)`, `completed()` | A29 |
| `engine/apply.py` | `execute(ctx, planned, lock, observer, record)`: record after each fold; on raise, record the marked lockfile, notify `stage_failed`, re-raise; `stage_applying`/`stage_applied` | A29, A33 |
| `engine/status.py` | `listing_status(..., incomplete=bool)`, where a set marker means dirty | A29 |
| `engine/change.py` | `StagePlan.snapshot: BaseModel \| None`; `Drift.last_applied_label`, `live_label` | A30 |
| `engine/stage.py` | Optional `snapshot()` documented on the protocol; `RenderStage.preview` stays specific to that stage, not part of the protocol | A30, A32 |
| `engine/plan.py` | `build_plan(..., observer)`: `stage_checking` before each walk, `snapshot()` after `plan()`, `stage_planned` after | A30, A33 |
| `engine/run.py` | `RunObserver`; `plan_fingerprint`; `apply_listings(..., expect)` and `StalePlanError`; `preview_listing`; the lockfile writer passed to `execute` | A29, A31–A33 |
| `engine/stages/product_diff.py` | `ListChange("colors")` | A30 |
| `engine/stages/printify_product.py` | `snapshot()` | A30 |
| `engine/stages/publish.py` | `snapshot()` with `below_cost` | A30 |
| `engine/stages/etsy_listing.py` | `snapshot()`; drift labels from the catalog | A30 |
| `engine/stages/etsy_media.py` | `EtsyMediaLive.images: tuple[{rank, image_id, url}]`; per-rank `MediaChange`; `snapshot()` | A30 |
| `engine/stages/render.py` | `scene_hash`; `snapshot()`; `preview()`; promotion in `apply()` | A32 |
| `clients/etsy/models.py` | `ListingImage.url_570xN` | A30 |
| `workspace/workspace.py` | `preview_file(...)`, `preview_dir(listing)`; `remove_listing` removes previews | A32 |
| `cli/render.py` | print drift labels when present | A30 |

## UI server

| Module | Holds |
|---|---|
| `ui/runs/registry.py` | `Run` (id, kind, listings, phase, event buffer, seen), per-listing locks, retention |
| `ui/runs/executor.py` | the FIFO worker thread, stop flag, cancellation, `RunObserver` → events |
| `ui/runs/events.py` | the `RunEvent` union and `StagePlan`/`Plan` serialisation |
| `ui/api/runs.py` | the six endpoints above |
| `ui/api/listings.py` | preview file endpoint |
| `ui/api/app.py` | `context_factory`; executor start and join on lifespan |
| `ui/desktop.py` | close handler waits for the executor |

`ui/runs/` is not the top-level `runs/` package the layout reserves for Phase
6's SQLite recorder. This one holds live runs in memory, and that one will
record finished runs. When Phase 6 lands, the recorder subscribes to the
registry rather than replacing it.

## Frontend

| Module | Holds |
|---|---|
| `pages/DeployPage.tsx` | the route: reattach or start, composing the parts below |
| `pages/deploy/runStream.ts` | typed `EventSource` wrapper with `Last-Event-ID` resume |
| `pages/deploy/deployState.ts` | pure reducer: `RunEvent[]` → phase, per-stage state, plan, previews |
| `pages/deploy/comparison.ts` | pure: snapshots + changes → before/after blocks, impact tags, price rows, image badges |
| `pages/deploy/wordDiff.ts` | pure: formats one `FieldChange`'s before/after |
| `pages/deploy/Comparison.tsx`, `PriceTable.tsx`, `StepStrip.tsx`, `Callouts.tsx`, `ApplyFooter.tsx` | presentation |
| `pages/editor/DeployControl.tsx` | the page-head swap (§8) |
| `api/runs.ts` | generated-client calls for the REST endpoints |

The control-state table in the spec gains three rows and changes one:

| Phase | ← Back | Plan again | Apply | Footer note |
|---|---|---|---|---|
| Queued | Enabled (cancels) | Hidden | Disabled | Waiting for another run to finish. |
| Previewing | Enabled (cancels) | Shown | Disabled | Rendering previews (2 of 4)… |
| Stale | Enabled | Shown, highlighted | Disabled | This listing changed after it was planned. Plan again to review the current version. |
| Applying | **Enabled (leaves; apply continues)** | Hidden | Spinner, disabled | Running steps in order. You can leave; this keeps going. |

---

## Spec corrections

Republished into the Deploy Changes Spec alongside this document:

1. Planning resolves stages **in pipeline order**. The out-of-order rationale
   is replaced by A21's.
2. The status pill is **re-derived** after apply, and a first deploy reads
   Deployed.
3. The below-cost refusal belongs to **`publish`** (PRD 40's amendment).
4. **Back is enabled during apply** and does not cancel it. The editor offers
   *View progress*, and the *leave site?* prompt is gone.
5. R1 becomes **stage snapshots composed by the frontend**, not a server-side
   projection.
6. R3's names come from the **stage's in-run catalog**, not an endpoint lookup.
7. R4 is precise: a **fingerprint of the whole plan, snapshots excluded**,
   checked in the engine.
8. New: **preview renders** during plan, Apply gated on them, and promotion at
   apply.
9. New: the **queued**, **previewing** and **stale** phases, and lifecycle
   deploys drawing whatever stages the plan returned.
10. New: a **partial apply is recorded** and reads Dirty.

---

## Build order

Five stacked PRs, each green on its own, with CI's hermetic tier and
`check.sh` passing and the coverage floor held.

| PR | Contents | Done when |
|---|---|---|
| ① Partial apply | A29: `execute` recording, `incomplete` marker, status reads it | A stage failing after a create leaves the product id recorded, the next plan does not re-create, and the listing reads dirty |
| ② Engine for review | `RunObserver`; plan-time events; `snapshot()` on all five stages; `ListChange("colors")`, per-rank `MediaChange`, drift labels; `EtsyMediaLive` images and `url_570xN`; `plan_fingerprint`, `expect`, `StalePlanError`; CLI prints labels | `plan` output is unchanged except for names in place of ids, and every new emission has a behaviour test |
| ③ Previews | `scene_hash`, `preview_file`, `RenderStage.preview`, promotion, pruning, `preview_listing` | A preview followed by `apply` renders nothing and yields byte-identical `outputs` |
| ④ Runs | `ui/runs/`, `ui/api/runs.py`, preview endpoint, `context_factory`, lifespan and desktop shutdown, `openapi.json` and `gen:api` | A plan run and an apply run stream their full event sequence through `TestClient` |
| ⑤ Deploy view | route, reducer, comparison, components, `DeployControl`, browser test | The browser loop in Testing passes against fakes |

① lands before ② because it changes `execute`'s signature, which ② extends.
③ is independent of ② apart from the render snapshot, and can be reviewed in
parallel once ② is up.

---

## Testing

| Layer | What it covers |
|---|---|
| Unit | `plan_fingerprint` stability (same plan, same hash; snapshot changes, same hash; any change or drift, different hash); `scene_hash` changes only with its own scene's inputs; `listing_status` with the marker |
| Behaviour | Partial apply records earlier stages and the marker, and a clean re-run clears it; each stage's `snapshot()` against fakes; `ListChange("colors")`, per-rank `MediaChange`, drift labels; `expect` mismatch refuses before any write, and in a two-listing run the second still applies; preview then apply promotes and renders nothing; stale previews are pruned; registry locks (409), FIFO queueing, cancel at a boundary, apply refusing `DELETE`, stop flag finishing the in-flight stage, retention and `seen` |
| Golden | A promoted preview is byte-identical to a direct render of the same scene |
| Contract | The SSE route through `TestClient`: event framing, ordering, `Last-Event-ID` replay; `RunEvent` in `openapi.json`; a cassette with `url_570xN` on `getListing?includes=Images` |
| E2E | Read-only: `get_listing(include_images=True)` returns `url_570xN` on the real shop. No new write tests, because the shop is real (see the e2e credentials note) |
| Frontend unit (Vitest) | `deployState` over recorded event sequences (plan, blocked, nothing to do, stale, failed mid-apply, reattach mid-apply); `comparison` blocks and badges; `wordDiff`; `DeployControl` states; `ApplyFooter` notes per phase |
| Browser | One loop through `create_app(context_factory=fakes)`: open a listing, Deploy changes, see previews fill, Apply, Back during apply, *View progress* reattaches, the run finishes, the pill is re-derived |

The browser test is the only one that proves the reducer, the SSE route and
the executor agree about a real sequence, so it stays even though every part
is unit-tested.

---

## What stays open

- **A batch runner.** The API takes many listings, but no screen sends more
  than one. PRD 20's dashboard runner is its own piece of work.
- **A3's fan-out.** Still A21's call. If it is built, only the plan-time
  events' order changes, and nothing else here depends on it.
- **Run history across restarts.** Phase 6's recorder.
- **Cancelling an apply.** Deliberately absent (A3). A stage boundary is the
  only safe point, and the shutdown path already uses it. A user-facing
  *Stop after this step* is possible later without changing the model.
