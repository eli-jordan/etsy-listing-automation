# Listing templates and batch creation implementation plan

Status: shipped. Delivered by [#83](https://github.com/eli-jordan/etsy-listing-automation/pull/83), [#84](https://github.com/eli-jordan/etsy-listing-automation/pull/84), [#85](https://github.com/eli-jordan/etsy-listing-automation/pull/85), [#86](https://github.com/eli-jordan/etsy-listing-automation/pull/86), [#87](https://github.com/eli-jordan/etsy-listing-automation/pull/87), [#88](https://github.com/eli-jordan/etsy-listing-automation/pull/88), [#90](https://github.com/eli-jordan/etsy-listing-automation/pull/90), [#91](https://github.com/eli-jordan/etsy-listing-automation/pull/91), [#92](https://github.com/eli-jordan/etsy-listing-automation/pull/92). This plan records the
implementation sequence; later feature amendments describe current requirements.

The [interactions](interactions.md) override the [spec](spec.md)
where their requirements differ.

## Outcome

A seller saves a finished listing as a **listing template**, drops up to 25
design PNGs (loose, or one ZIP) onto it, fixes any names staging flags, and
presses **Create N listings**. Each design becomes an ordinary local listing.
The `ui` server then drafts a brief, runs market research and generates an SEO
proposal for each one through a shared, resumable batch queue. The seller
reviews the results from the batch summary, accepts suggestions in the ordinary
listing editor, and deploys through the existing deploy flow. Nothing in batch
creation deploys.

Proposals move from browser `localStorage` to server cache for every AI run,
manual ones included. A stale proposal stays usable, and the drawer heading is
the warning.

## Settled decisions this plan builds

| Topic | Decision | Source |
|---|---|---|
| Authority | The UI doc wins over the spec where they differ | Reviewed interactions |
| Listing templates | Their own resource under `listing-templates/<name>/`, never a listing kind. Snapshot instantiation with no live link. Created only by Save-as or Clone | spec *Listing templates* |
| Save-as interaction | Opens the unsaved template straight away with the name field focused. Nothing is written until it is named, and there is no confirmation dialog | UI doc §1 |
| Template editor | The listing editor minus design-specific parts. Autosaves only complete templates. The head has no actions | UI doc §3 |
| Input | One ZIP *or* loose PNGs, at most 25 unique designs, refused before staging otherwise | spec *Accepted input* |
| Names | `slugify(stem)` drives `listings/<n>/` and `designs/<n>.png`. Generated names get the smallest free `-2…`; typed names are flagged, not changed; confirm re-allocates atomically | spec *Cleaning and editing names* |
| Dedupe | By PNG bytes, within the upload and against `designs/`, scoped to the batch | spec *Content deduplication* |
| Batch queue | Workspace-wide, `batch_ai.concurrency` (default 1), round-robin across batches, restart-resumable. Manual runs don't count against the limit | spec *Batch AI queue* |
| Where the queue runs | Only inside the `ui` server. There is no guard against two servers on one workspace; in-process locks are enough | grilling |
| Batch runs | Ordinary `AiRun`s with origin `batch`, started through the existing `AiRunner` and the same 180 s limit | grilling |
| Proposals | One latest proposal per listing in server cache, with per-field resolution state. No expiry, no history. Browser-local proposals are discarded | spec *Durable AI proposals* |
| Staleness | Computed on the server from the proposal snapshot. A stale proposal is usable directly; the drawer heading is the warning | UI doc §8, grilling |
| Listings table | No batch filter. The batch summary is the only review surface | UI doc *Departures* |
| Recent batches | A table on the Listing templates page with a derived status | UI doc §2, open question 1 closed |
| Refused card drop | Navigates to New batch with the template preselected and the refusal shown | UI doc open question 2 closed |
| Deploy precedence | UI apply cancels and awaits the listing's AI work and refuses new runs while it owns the listing. CLI apply does nothing special about AI work | grilling |
| Proposal cleanup | Both UI and CLI apply delete the listing's proposal after a **full success** | spec *Deployment interaction*, grilling |
| Cache format | Schema-versioned JSON files with atomic writes, like the existing caches | grilling |

## Architecture decisions

These are recorded in [history/implementation-plan.md](../../history/implementation-plan.md) as A35–A46. They are summarised here because every PR below
cites them.

**A35 — Listing-template storage.** `listing-templates/<name>/template.yaml` plus
`assets/`. The names live in `workspace/layout.py` (`LISTING_TEMPLATES_DIR`,
`TEMPLATE_FILE`, `TEMPLATE_ASSETS_DIR`); the only accessors are on `Workspace`
(`listing_template_dir`, `listing_template_file`, `listing_template_names`,
`remove_listing_template`), and names are checked with `_segment`.
`ListingTemplate` is a new pydantic model in `config/listing_template.py` with
`extra="forbid"`. It reuses `MediaEntry`, the price models and a
`TemplateEtsyConfig` that has `description` (text or ref only), `renewal`,
`section`, `shipping_profile` and `variation_images`, and no title, tags or lead.
`./` refs in a template resolve against the template directory, so
`resolve_ref` gains a template-owner variant rather than a second resolver. Listing
discovery already scans only `listings/`, and a test pins that templates never
appear in it.

**A36 — Template completeness.** `check_listing_template(template, facts)` in
`config/listing_validation.py` composes the existing checks (garment profile,
colours enabled and in profile, price source, media present, gallery, variation
images, videos, template-kind colour match) and none of the design, brief or copy
checks. Any `block` issue refuses the write. The server never stores an
incomplete template: `PUT` returns `200 {saved: false, issues}` and leaves the
file alone, which the editor turns into the *Not saved* state. Saving never calls
a provider.

**A37 — Cache records.** A single helper, `workspace/atomic.py`
(`write_bytes_atomic`, `write_json_atomic`: tmp file in the same directory, then
`os.replace`), replaces the per-module copies as they are touched. New layout
names:

```text
.cache/staging/<id>/session.json      # frozen template + rows + names
.cache/staging/<id>/template/         # frozen template-owned assets
.cache/staging/<id>/uploads/<sha256>.png
.cache/batches/<id>.json              # batch record, rows, queue + review state
.cache/batches/<id>/template/         # frozen template, kept for Retry
.cache/proposals/<listing>.json
```

Every record has a `schema` integer. A record with an unknown schema is treated
as absent (cache is disposable). Stores are plain classes over `Workspace`:
`StagingStore` and `BatchStore` in a new `batches/` package, and `ProposalStore` in
`ai/proposals.py`, so the engine can reach it without importing the UI. Mutations
go through the store under a per-record `threading.Lock`.
A proposal file is named by the listing's exact name, as PRD 4's layout and the
market snapshot are, not its casefold: a casefolded key makes two listings that
differ only in case share one file on a case-sensitive filesystem, and on a
case-insensitive one such listings cannot coexist anyway.

**A38 — Name allocation.** `batches/naming.py`: `allocate(base, taken) -> str`
returns `base` or the smallest free `base-N` (N ≥ 2), where `taken` is the
casefolded union of listing names, design stems, the other rows' names and the
names already allocated in this batch. Staging computes a preview and flags
typed conflicts with a suggestion. Confirm re-runs allocation per row while
holding `WorkspaceLocks.listing(name)` and writes the result into the batch record
*before* creating any file.

**A39 — Idempotent row creation.** The batch record is written first, with each
row's allocated name, design target and `creation: pending`. Creating a row:
(1) write or reuse `designs/<design>.png`; (2) copy the frozen template assets
into `listings/<name>/`; (3) write `listing.yaml` atomically; (4) set
`creation: created`. Retry or resume re-enters at the recorded step. A listing
directory that already exists at the recorded name counts as this row's work only
when its `design` ref equals the row's design target. Otherwise the row
re-allocates a name. A write failure sets `creation: failed` with the message and
the loop continues. This is the first code that writes to `designs/`.

**A40 — Batch queue.** `ui/batchqueue.py` holds `BatchQueue` on `app.state`: one
dispatcher thread woken by a `Condition` on row, batch and run changes. Each
wake it reads `workspace.load_settings().batch_ai.concurrency`, counts running
batch-origin runs, and picks the next `queued` row round-robin across batches in
creation order. Starting a row means `registry.create(listing, draft_brief=<brief
is empty>, origin="batch")` then `runner.start(run)`. If that returns `Conflict`
(a manual run holds the listing), the row stays queued and is skipped this
round. A finish callback on `AiRun` maps `done|failed|cancelled` onto the row. On
startup every `running` row returns to `queued`. The manual `POST /api/ai/runs`
returns `409 {reason: "batch_pending"}` while the listing has a queued or running
row. Retry leaves an already-written brief alone: `draft_brief` is false once the
brief is non-empty, so only research and SEO rerun. **Cancel batch** moves
queued rows to `stopped` and requests a stop on running ones; **Resume** moves
`stopped` and `cancelled` rows back to `queued`.

**A41 — Durable proposals.** `ProposalStore` holds one record per listing:
`{proposal, snapshot, generated_at, origin, resolution: {title, tags, lead}}`.
`AiRunner._chain` writes the record before it emits `AiProposalEvent`, for manual
and batch runs alike. `ui/api/seo.py` loses `_PROPOSAL_TTL`. New endpoints:
`GET /api/listings/{name}/proposal` returns the record plus
`stale: {is_stale, reasons[]}`, and `PATCH …/proposal/resolution` records
accepted or dismissed sections. `proposal_staleness(listing, snapshot)` in
`ai/proposals.py` ports the frontend `isStale` field by field (brief, section,
colours, materials, garment profile, product type, garment brand/model, design
identity, `design_content_hash`) and returns a reason per changed input, which
gives *Stale: brief edited since*. The frontend deletes `aiSeoStorage`'s proposal
store and clears its `ai-seo-proposal:*` and `ai-seo-received:*` keys once on
load.

**A42 — Listing rename and delete.** Rename, under the existing
`locks.listing(old, new)`, also moves `.cache/proposals/<old>.json` and rewrites
every batch row whose `listing` is `old` (via `BatchStore.rename_listing`).
Delete removes the proposal, requests a stop on any active run, and marks
matching rows `deleted`. Batch rows reference listings by current name only;
there is no hidden listing id.

**A43 — UI deploy precedence.** Before the executor's `_run_plan` or `_run_apply`
reads a listing, it calls `BatchQueue.yield_to_deploy(names)`. That marks the
listings' queued rows `cancelled_by_deploy`, requests a stop on their active AI
runs (batch or manual), and waits for those runs to finish. While the run holds
the listing, `POST /api/ai/runs` returns `409 {reason: "deploying"}`. Resume
never re-queues `cancelled_by_deploy` rows; only an explicit per-row Retry does.
The CLI is deliberately left out (grilling): a CLI apply during batch AI can end
with a proposal on a deployed listing, and the seller regenerates or ignores it.

**A44 — Proposal cleanup after full success.** `engine/run.py` gains
`fully_applied(outcome, lockfile)`, which requires all three of: `outcome.ok`, no
`stage_plan.blocked` in the planned stages, and the lockfile's `incomplete`
marker clear. `ok` alone is not enough, because blocked stages count as `ok`
(`cli/app.py:165-175`). `apply_listings` calls
`ProposalStore.remove(listing)` after `after_apply` when that holds, so the CLI
and UI clean up identically.

**A45 — Upload and archive limits.** These are safety limits, not settings:

| Limit | Value |
|---|---|
| One PNG | 64 MiB |
| One upload, loose PNGs combined | 512 MiB |
| ZIP, compressed | 512 MiB |
| ZIP, expanded total | 1 GiB |
| ZIP entries | 2,000 |
| Expansion ratio of one entry | 100:1 |

Uploads stream to disk with a running byte count instead of `await file.read()`.
ZIP handling uses `zipfile` entry by entry, never `extractall`. It refuses
absolute paths, `..`, backslash-rooted names, symlinks (from the
`external_attr` mode bits), encrypted entries, and duplicate normalised names.
PNG is decided by the entry's magic bytes; the extension doesn't matter. The
25-design limit counts unique content hashes and is checked before a session is
created. Any refusal leaves nothing on disk.

**A46 — Staging lifetime.** A session expires seven days after `updated_at`.
`StagingStore.sweep()` runs on server start and whenever the staging or batch
index is listed. Confirm keeps the uploads until every row has been
materialised (created, or failed with its input copied into the batch
directory), then deletes the staging directory. Cancel deletes it straight away.

### New HTTP surface

| Route | Purpose | PR |
|---|---|---|
| `GET/POST /api/listing-templates` | Index (cards: gallery, garment, colour count, plan, batch count), create from `{name, from_listing \| from_template}` | 1 |
| `GET /api/listing-templates/draft?from_listing=` / `?from_template=` | Unsaved template preview for the *name it* state; writes nothing | 1 |
| `GET/PUT/DELETE /api/listing-templates/{name}`, `POST …/rename` | Editor load, valid-only save, delete, rename | 1, 6 |
| `POST /api/staging` (multipart: `template`, `files[]`) | Validate the input, freeze the template, create the session | 2, 7 |
| `GET/PATCH/DELETE /api/staging/{id}` | Reattach, edit names/label/remove rows, cancel | 2 |
| `POST /api/staging/{id}/confirm` | Create the batch and its listings, return the batch id | 2 |
| `GET /api/staging/{id}/rows/{row}/thumbnail` | A staged design's thumbnail for the review | 2 |
| `GET /api/batches`, `GET/PATCH/DELETE /api/batches/{id}` | Recent batches, summary, rename, delete record | 2, 5 |
| `POST /api/batches/{id}/rows/{row}/retry` | Retry a row's creation (PR 2); PR 4 adds its AI half | 2, 4 |
| `POST /api/batches/{id}/{cancel,resume,retry}` | Queue control | 4 |
| `PUT /api/batches/{id}/rows/{row}/reviewed` | Mark reviewed / needs review | 5 |
| `GET /api/listings/{name}/batch` | The listing's batch membership, for the editor's row | 5 |
| `GET /api/listings/{name}/proposal`, `PATCH …/resolution` | Durable proposal | 3 |

The OpenAPI export and `npm run gen:api` are regenerated in every PR that
changes this surface.

### New frontend routes

`/listing-templates`, `/listing-templates/new?from_listing=|from_template=`,
`/listing-templates/:name`, `/batches/new?template=`, `/batches/staging/:id`,
`/batches/:id`, and `/listings/:name?batch=<id>`. The query parameter shows
**Back to batch** and survives a reload. A **Listing Templates** sidebar item
goes between Listings and Templates.

## PR sequence

Every PR targets the PR before it, stays under **5,000 changed lines**
(insertions plus deletions in `git diff --shortstat <base>...HEAD`, with
generated `docs/openapi.json` and `src/api/schema.ts` included), and leaves the
suite green on its own.

```
docs ─► PR 1 templates (thin) ─► PR 2 staging + create (thin) ─► PR 3 durable proposals
      ─► PR 4 batch AI queue ─► PR 5 review + batch index ─► PR 6 template editor
      ─► PR 7 ZIP + dedupe ─► PR 8 deploy precedence
```

PRs 1–2 are the thin end-to-end path: template → loose PNGs → listings on disk,
with no AI. The order after that puts durable proposals before the queue,
because a batch run with nowhere to keep its proposal is useless, and puts
deploy precedence last because it only guards the queue.

The stack is based on PR 81 (`t3code/listing-template-batch-generation`), which
carries the spec, the UI doc, the mockups and this plan. PR 1 targets that
branch.

### Definition of done — every PR

A PR is done only when all of these hold. The PR-specific conditions below are
added to this list, not substituted for it.

1. **Local suite green.** `./scripts/check.sh` exits 0: ruff format/check, mypy
   strict, the full non-e2e pytest run, and the frontend's
   prettier/eslint/tsc/vitest.
2. **Coverage gates met.** ≥85% branch coverage for Python and the frontend.
   The threshold is not lowered and no `# pragma: no cover` is added.
3. **Browser layer green locally.** `uv run pytest -m browser` passes, not
   skipped.
4. **PR created with green checks.** Opened with `gh pr create`, registered
   with this thread's `link_pull_request`, and every CI check is green on
   ubuntu and windows, plus the frontend gate.
5. **e2e green on the branch.** `gh workflow run e2e --ref <branch>`, with the run
   URL in the PR description. A stale `ETSY_TOKENS_JSON` is refreshed and
   re-run, not treated as a pass.
6. **Size.** `git diff --shortstat <base>...HEAD` under 5,000 lines, with the
   number in the PR description.
7. **Decisions cited.** Commit messages and any arbitrary-looking code cite the
   spec section, the UI doc section or A35–A46.
8. **Naming.** Code, API and UI say *listing template* (`listing_template`,
   `ListingTemplate`, `/listing-templates`), never bare *template*, which
   already means mockup templates.

---

### Documentation commit (this branch, before PR 1) — done

The initial documentation landed in
[#82](https://github.com/eli-jordan/etsy-listing-automation/pull/82). It aligned
template and batch requirements with durable proposals, rename ownership,
stale-proposal acceptance and deploy precedence before the implementation PRs.
The reviewed UI departures were folded into the spec at that checkpoint.

---

### PR 1 — `feat(listing-templates): save a listing as a listing template`

**Target: about 3,500 lines.**

1. `ListingTemplate` model, the layout names and `Workspace` accessors (A35).
   The template-owner variant of `resolve_ref` is included.
2. `check_listing_template` (A36).
3. `listing_templates/convert.py`:
   - `from_listing(listing, workspace) -> (ListingTemplate, assets)` copies the
     fields in the spec's copy table and drops the excluded ones.
   - Every `./` media file is planned as a template-owned asset copy, and a
     missing or unreadable one refuses with the ref named.
   - `from_template` does the same for clones.
   - Nothing is written until `save(name, …)`, which copies assets and then
     writes `template.yaml` atomically.
   - A clash is refused, never suffixed.
4. API: index, draft preview, create, get, delete. `PUT` exists but is used only
   by PR 6.
5. Frontend:
   - **Save as listing template** in a row above `EditorHead`, the row PR 5 later
     adds to.
   - The `/listing-templates/new` page in its *name it* state: head with
     `EditableName` focused and *Not saved — name this template to save it*, and
     a read-only summary of garment, colours, pricing, gallery thumbnails and
     description source.
   - The Listing templates page: cards with **Start batch** (disabled until
     PR 2) and **Delete**, plus the sidebar item.

**Success conditions (added to the common list):**
- Unit tests for the conversion cover: every copied and every excluded field;
  a shared ref stays shared; a `./` image and a `./` video are copied and
  rewritten; a missing `./` file refuses; inline description text is kept.
- A behaviour test shows `listing_names()`, `plan --all` and the deploy
  workspace index never include a template.
- Contract tests cover: a name clash returns 409 with nothing written; an
  incomplete source listing (no colours enabled) is refused with issues; the
  draft endpoint writes nothing.
- Browser test: Save as listing template → name → the card appears on the page.

### PR 2 — `feat(batches): stage loose PNGs and create listings`

**Target: about 4,700 lines.** This completes the thin end-to-end path.

Shipped as two PRs to stay under the size limit: **PR 2** is items 1–3 (the
`batches/` package and the API), and **PR 2b** is item 4 (the frontend). The
browser success condition belongs to PR 2b.

1. `batches/` package:
   - `StagingStore` and `BatchStore` (A37), with `write_json_atomic`.
   - `naming.allocate` (A38).
   - `staging.stage_pngs(template, files)`: stream each upload to
     `uploads/<sha256>.png` (A45 per-file and total limits); merge identical
     bytes within the upload into one row with both source names; enforce the
     25 limit; freeze the template document and its assets; validate each row
     with `check_design_resolution` against the frozen garment profile; compute
     `slugify` names and the suffix preview.
   - `creation.create_rows(batch)` (A39).
2. Staging operations: rename a row (typed-conflict flag plus a suggestion;
   empty names flagged), remove a row, edit the label, cancel, confirm. Confirm
   revalidates the frozen document's workspace-shared refs. The AI readiness
   gate is added in PR 4. The sweep (A46) runs at startup.
3. API: `POST /api/staging` (loose PNGs only; a ZIP is refused with *coming
   soon* until PR 7), `GET/PATCH/DELETE /api/staging/{id}`,
   `POST …/confirm`, `GET /api/batches/{id}`.
4. Frontend:
   - New batch page with the template picker, the drop zone and the refusal
     callout. The size hint comes from the chosen template's print area.
   - Staging review: count strip, rows, name editing, suggestion button,
     *Fix N names* gating, *Using X as saved at HH:MM*, Cancel staging.
   - A minimal batch summary: label, then one row per listing with its final
     name and creation state, Retry for failed creation, and an Open link.
   - Start batch is enabled on the cards.

**Success conditions:**
- Unit tests for `allocate` cover: the base name free; `-2` when taken;
  skipping a taken `-2`; clashes with design stems as well as listings;
  casefolded collisions; names already allocated in the same batch.
- Behaviour tests:
  - opaque and undersized PNGs become *not created* rows with the existing
    message;
  - 26 unique PNGs are refused with nothing on disk, while 26 files that
    collapse to 25 are accepted;
  - a name claimed between staging and confirm gets a fresh suffix;
  - a write failure injected on one row leaves the other rows created, and
    Retry creates the failed one;
  - repeating confirm or retry after a simulated crash between each A39 step
    never creates a second listing.
- A behaviour test shows an edit to the template after staging does not reach
  the created listings, and deleting the template doesn't break confirm.
- A contract test shows a reload reattaches to the session: `GET` returns the
  same rows and names.
- Browser test (PR 2b): drop three PNGs → fix one name → Create 3 listings →
  summary shows three rows, and each opens an editor whose design is the dropped
  file.

### PR 3 — `feat(ai): durable server-side proposals`

**Target: about 3,500 lines.** Independent of batches; it benefits manual runs
straight away.

1. `ai/proposals.py`: `ProposalStore`, and `proposal_staleness` ported from
   `isStale` with a reason per changed input (A41).
2. `AiRunner._chain` persists the proposal before emitting it. `_PROPOSAL_TTL`
   and `expires_at` handling are removed.
3. The proposal endpoints. Rename and delete hooks for proposals (the batch half
   of A42 comes in PR 5).
4. Frontend:
   - `useAiSeoMode` loads the proposal from the server on open and records
     resolution through `PATCH`.
   - The `aiSeoStorage` proposal store is deleted, and legacy keys are purged
     once.
   - `AiChoiceDrawer` and `AiTagsDrawer` no longer disable choices when stale.
     The heading reads *Out of date: {reason}. Still usable*.

**Success conditions:**
- Unit tests for `proposal_staleness` cover every input the frontend `isStale`
  covered, with its reason text. Order-insensitive fields are covered too.
- A behaviour test shows a manual run's proposal survives a new `TestClient` (a
  server restart), and a regenerated proposal replaces it.
- A contract test shows resolution survives reload, and resolved sections don't
  reopen as new.
- A contract test shows renaming moves the proposal and deleting removes it.
- vitest: a stale proposal's choices are clickable and the heading names the
  reason.
- Browser test: generate → reload → the suggestions are still waiting.

### PR 4 — `feat(batches): batch AI queue`

**Target: about 4,200 lines.**

1. `Settings.batch_ai: BatchAiSettings(concurrency: int = 1, ≥1)`, with the
   `_absent_is_empty` validator.
2. `AiRun.origin: "manual" | "batch"` and a finish callback. Registry
   `create(..., origin=)`.
3. `BatchQueue` (A40): dispatcher, round-robin, restart recovery, and the
   `batch_pending` 409 on manual runs. It is wired into the app lifespan
   alongside `AiRunner.shutdown`.
4. Row AI states `queued | running | done | failed | stopped | cancelled`, set
   by the queue. Confirm queues every created row.
5. Staging gains the AI readiness gate: prompts, at least one ready provider,
   and Etsy market credentials. It reuses `readiness`' provider and prompt
   checks. Failure shows the blocking callout and disables Create (wording from
   `staging.note.md`).
6. API: cancel, resume, retry-all-failed, retry-row.
7. Frontend:
   - The batch summary gains the progress bar, the count strip and an AI column
     that mounts `AiWorkflowIndicator` for running and failed rows (*done* for
     finished ones), plus Cancel batch, Resume and Retry N failed. It polls
     while any row is queued or running.
   - The editor shows the batch run live by reattaching through the existing
     `GET /api/ai/runs?listing=`. The manual AI control is disabled with a hint
     while the listing has batch work.

**Success conditions:**
- Behaviour tests with `ChainProvider` and the fake market client:
  - concurrency 1 runs rows strictly one at a time; concurrency 2 runs two;
  - two batches interleave round-robin;
  - a failed row leaves later rows running;
  - Retry on a market failure keeps the saved brief, including a seller edit,
    and reruns research and SEO only;
  - a brief the seller wrote before the row's turn is kept and used;
  - a timeout becomes a failed row.
- A behaviour test shows restart recovery: stop the app with a running row,
  create a new app, and the row reruns to completion with one listing and one
  proposal.
- A behaviour test shows Cancel batch stops the running row and leaves queued
  rows `stopped`, and Resume completes them.
- A contract test shows a manual run is refused with `batch_pending` while the
  row is queued, and allowed once it is done.
- A contract test shows confirm is refused before any listing is written when a
  prompt file is missing.
- Browser test: create a batch of two with the fake provider → both rows reach
  *done* → the editor shows the suggestions waiting.

### PR 5 — `feat(batches): review flags, batch index and listing hooks`

**Target: about 3,800 lines.**

1. Row `reviewed: bool` and `PUT …/reviewed`. The endpoint refuses queued,
   running, deleted and never-created rows.
2. A derived batch status (`staging | drafting | in_review | complete |
   stopped`), a failure count, and `GET /api/batches`, which includes staging
   sessions with their expiry. The derivation is a pure function with the
   UI doc §2 table as its tests.
3. Batch rename (the label only) and delete record. Delete cancels queued and
   running work first and never touches workspace files.
4. The batch half of A42: rename rewrites rows; delete marks them `deleted` and
   cancels the run.
5. Frontend:
   - **Recent batches** on the Listing templates page, with `BatchStatusTag`,
     the red *N need retry* count, and rows opening staging or the summary.
   - On the batch summary: the Reviewed column and actions, `EditableName` for
     the label, Delete batch record, and struck-through deleted rows. Open
     passes `?batch=`.
   - In the listing editor: the row above the head gains **Back to batch …**
     (only with `?batch=`) and **Mark reviewed / Mark needs review** (only when
     `GET /api/listings/{name}/batch` finds membership).

**Success conditions:**
- Unit tests for the status derivation cover each UI doc §2 row, and show a
  failed row never changes the status.
- Behaviour tests:
  - marking the last row reviewed makes the batch Complete, and marking one back
    returns it to In review;
  - a later listing edit or a regenerated proposal leaves Reviewed alone;
  - `plan` and `apply` ignore Reviewed;
  - renaming a batch listing updates the row and the proposal, and the summary
    opens the new name;
  - deleting a listing leaves a deleted row and cancels its run;
  - deleting a batch record leaves every listing, design, brief and proposal.
- A behaviour test shows removing `.cache` leaves templates, designs, listings
  and accepted copy, and the batch index is empty.
- Browser test: the summary → Open → Back to batch → Mark reviewed, reflected on
  the summary.

### PR 6 — `feat(listing-templates): listing-template editor`

**Target: about 4,500 lines.**

1. `PUT /api/listing-templates/{name}` with A36 valid-only semantics, plus
   `POST …/rename`. Template-owned file uploads and the media file list are
   scoped to the template's `assets/`.
2. Frontend: `ListingTemplateEditorPage` reuses `ListingEditorShell` with a
   `kind="listing-template"` prop:
   - `DesignSelect` in preview mode: *Preview design: Bundled grid*, listing
     calibrator test designs plus recent workspace designs, not saved, and reset
     on every open.
   - `MediaLocator` says *This template*.
   - `IssuesBanner` uses the template wording with no *Prevents deploying* tag.
   - `DetailsTab` has a template mode without Brief, Title, Tags, Lead, AI Mode
     or the market panel, and shows the lead-placement hint.
   - The head has no status, Deploy or actions.
3. `useAutosave` gains an *unsaved* outcome for `{saved: false}`. It keeps the
   client values, retries when they become valid, and warns before navigation
   through the existing blocker.
4. The PR 1 read-only *name it* page becomes this editor in its unsaved state.
   Clone on a card opens it with `from_template=`. Delete gets a confirmation
   stating that batches and listings are unaffected.
5. Every card is a drop target. The overlay reads *Drop to stage N PNGs with X*
   and posts straight to staging. A refused drop navigates to New batch with the
   template preselected and the refusal shown.

**Success conditions:**
- A contract test shows an incomplete `PUT` returns issues and leaves the file
  byte-identical, and a complete `PUT` writes it.
- vitest: the preview design is absent from the saved document and resets on
  remount; the template Details tab has none of the design-specific fields.
- Browser tests:
  - switch every colour off → *Not saved* and the badge → switch one back on →
    saved;
  - navigating away while unsaved warns;
  - clone → name → two independent templates.
- A browser test shows dropping PNGs on a card lands on staging with that
  template chosen.

### PR 7 — `feat(batches): ZIP input and content dedupe`

**Target: about 2,800 lines.**

1. `batches/archive.py` (A45): streaming, per-entry validation, recursive PNG
   discovery by magic bytes, a count of ignored non-PNG entries and their names,
   and refusal of mixed or multiple ZIPs.
2. Dedupe against `designs/`: the row records `reuse: designs/<existing>.png`,
   and creation references that file instead of writing a new one. A different
   image at an occupied path takes the listing's suffix (already true from A38).
3. Staging UI: the *merged* and *ignored* counts, the expandable ignored list,
   and the reused-design note on a row. New batch drops the *coming soon*
   refusal.

**Success conditions:**
- Unit tests over hand-built archives: nested PNGs found; ZIP folder names
  absent from row names; non-PNG entries ignored and counted; each of traversal,
  absolute path, symlink, encrypted entry, too many entries, expansion ratio and
  total expanded size refused, with nothing written; a PNG with a `.dat`
  extension accepted.
- Behaviour tests:
  - identical bytes already in `designs/` produce a listing whose design ref is
    the existing file and whose name is the staged name;
  - the same artwork in a second batch creates a new suffixed listing.
- Browser test: drop a ZIP with nested folders, a duplicate and a `.txt` → the
  counts and rows match.

### PR 8 — `feat(deploy): deploy precedence over batch AI and proposal cleanup`

**Target: about 1,800 lines.**

1. `BatchQueue.yield_to_deploy(names)` (A43), called at the start of the
   executor's `_run_plan` and `_run_apply`, and the `deploying` 409 on
   `POST /api/ai/runs`.
2. The `cancelled_by_deploy` row state: Resume skips it, per-row Retry
   re-queues it, and the summary shows *Cancelled for deploy*.
3. `fully_applied` and the `ProposalStore.remove` call in `apply_listings`
   (A44), so the CLI gets it with no CLI-specific code.

**Success conditions:**
- A behaviour test shows a UI apply started while a row is running waits for the
  run to stop before planning reads the listing, and Resume afterwards does not
  re-queue that row.
- A behaviour test shows a UI apply with a queued row cancels it and no proposal
  appears after the deploy.
- Behaviour tests cover `fully_applied`: ok → proposal removed; ok with a
  blocked stage → kept; failed → kept; lockfile `incomplete` → kept.
- A behaviour test shows the CLI `apply` removes the proposal after a full
  success.
- e2e (definition of done 5) exercises a deploy of a batch-created listing, not
  only the fixture listing.

## Acceptance criteria

The feature is complete when the spec's acceptance criteria, as amended by the
documentation commit, are observable. The table maps each one to the PR that
proves it.

| Spec criterion | Proven in |
|---|---|
| 1 Save as listing template with copied assets | PR 1 |
| 2 Templates never in discovery or deploy | PR 1 |
| 3 Reload-safe staging, ZIP discovery, validation, dedupe, names | PR 2, PR 7 |
| 4 Confirm creates local listings, continues past a row failure | PR 2 |
| 5 Restart or resume never duplicates a row | PR 2, PR 4 |
| 6 Concurrency, round-robin, resume, continues past failure | PR 4 |
| 7 Fresh brief and one server-cached proposal per row | PR 3, PR 4 |
| 8 Stale proposals labelled and usable (amended) | PR 3 |
| 9 Summary, Retry, Cancel/Resume and Reviewed survive restarts (no table filter, amended) | PR 4, PR 5 |
| 10 Cache clearing loses exactly the documented state | PR 5 |
| 11 UI apply cancels AI; both entry points clear the proposal after full success (amended) | PR 8 |
