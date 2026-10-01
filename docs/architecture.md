# Architecture

This is the living description of module boundaries, data flow and invariants.
Feature requirements live in the [documentation index](README.md#features);
decision rationale lives in [ADRs](adr/README.md). The
[original PRD and plan](README.md#history) are retained as historical snapshots.

Last audited against the implementation on 2026-09-30. The
[audit report](research/architecture-audit-20260930.html) records evidence,
remaining violations and proposed repairs. The invariants below describe the
intended contracts; they are not a claim that every current caller obeys them.

The [module-structure specification](features/module-structure-20260930/spec.md)
and ADR-0052 define an accepted, pending restructure into transport-independent
core, server and CLI modules with React source at `src/ui`. Its
[stacked implementation plan](features/module-structure-20260930/plan.md)
requires current descriptions to stay truthful during migration and a complete
architecture reconciliation at completion. This document still describes the
current checkout; the specification governs changed ownership, and its one
user-visible change, removing the native host, is implemented: `ui` serves
HTTP in the foreground. The npm project has also moved to `src/ui`, and the
foundational backend packages (`engine`, `workspace`, `render`, `clients`,
`config`, `ai`, `market`, `batches`, `listing_templates`) plus
`connections.py` and `errors.py` now live under `etsy_listings.core`; module
paths such as `engine/run.py` below are relative to `src/etsy_listings/core/`.
Unrelated invariants below remain in force.

## Runtime and dependencies

The application is a synchronous Python 3.12+ core with a FastAPI server and
a React/TypeScript SPA. `pyproject.toml` declares runtime dependencies and
`uv.lock` records the Python resolution; the frontend's `package.json` and
`package-lock.json` do the same for Node. Versions here describe this checkout,
not the latest vendor releases.

| Area | Dependencies and current role |
|---|---|
| CLI and documents | Typer (locked 0.27.2, Click 8.5.0 transitively), pydantic v2 (2.13.5), pydantic-settings and PyYAML; questionary is used through `prompts.py` with a plain-input fallback |
| HTTP clients | httpx (0.28.1); vendor protocols and shared retry policy, without vendor SDKs |
| Images | `opencv-python-headless==4.10.0.84`, `pillow==10.4.0`, and NumPy (locked 2.5.2, currently supplied transitively by OpenCV); pure numerical passes plus explicit I/O/cache adapters |
| Videos | PyAV (`av>=15`, locked 18.1.0) probes streams, dimensions and duration; the tool uploads original video bytes rather than encoding them |
| Web server | FastAPI (0.141.1), python-multipart and uvicorn; `ui` runs the application under uvicorn in the foreground and the user opens it in a browser |
| Frontend | React/React DOM 19, React Router 7, Phosphor icons and openapi-fetch; TypeScript 5 and Vite 8 build the SPA; openapi-typescript generates `src/api/schema.ts` from `docs/openapi.json` (ADR-0011) |
| Development | uv/hatchling, ruff, strict mypy, Import Linter, pytest/pytest-cov, Playwright; frontend ESLint, Prettier, Vitest, Testing Library and V8 coverage; marver is a design dependency |
| AI processes | Installed, signed-in `codex`, `claude` and `grok` CLIs, invoked behind `AiProvider`; these are external executables, not Python SDK dependencies |

`hatch_build.py` rebuilds release-wheel assets in `src/ui` with `npm ci` and
`npm run build`; Node/npm are required even when `src/ui/dist/` already exists.
The hook maps that `dist/` to `etsy_listings/server/static` inside the wheel, where
`server/api/app.py` finds it once installed, so the wheel needs neither Node nor
the checkout. The sdist carries the npm source, lockfile and hook instead of
built assets. Editable installs map nothing: the server falls back to the
checkout's `src/ui/dist`, the hook reuses existing assets and, when npm is
absent, warns and allows Python-only development without the SPA. CI builds with
`npm ci` before editable `uv sync --frozen`. NumPy, Starlette,
prompt_toolkit and pydantic-core are imported directly but currently arrive
through other declared dependencies; the audit distinguishes that coupling
from a missing dependency at runtime.

## Module boundaries

```mermaid
graph TD
    CLI[CLI commands and wizards] --> ENGINE[Engine: plan, apply and lifecycle]
    UI[UI: FastAPI and React] --> ENGINE
    UI --> AI[AI runs and proposals]
    UI --> MARKET[Market research]
    AI --> WORKSPACE
    UI --> BATCHES[Batch staging and creation]
    UI --> CLIENTS
    BATCHES --> TEMPLATES[Frozen listing-template content]
    ENGINE --> WORKSPACE[Workspace: paths and file access]
    ENGINE --> CLIENTS[Clients: Printify and Etsy]
    ENGINE --> RENDER[Pure render passes]
    MARKET --> CLIENTS
    BATCHES --> WORKSPACE
    WORKSPACE --> CONFIG[Config models and validation]
    WORKSPACE --> RENDER
    ENGINE --> AI
    TEMPLATES --> WORKSPACE
    MARKET --> CONFIG
```

This diagram shows the main flows and notable cross-package dependencies,
rather than every import. The UI AI runner composes AI tasks with market
research; `ai` does not itself import `market`. The engine imports the AI
proposal store to clear accepted or discarded proposals after full apply.
`config.market_weights` owns the settings value types consumed by research;
market retains compatibility re-exports, while config does not import market.
Dependencies are not a strictly
downward tree. Entry points
adapt the engine's domain events and reports; clients own HTTP; the workspace
owns the data tree. Rendering takes arrays and frozen configuration, with file
I/O at its boundary. Each package's `__init__.py` documents its public interface
and what it deliberately withholds.

| Module | Owns | Boundary |
|---|---|---|
| `cli` | Typer commands and terminal presentation | Uses engine reports rather than computing a second diff; only the `ui` launcher (`cli/ui.py`) imports the server, and only `server.hosting` |
| `newcmd`, `setupcmd`, `authcmd` | Picker and workspace/credential workflows | Prompt sequencing is separate from their testable logic |
| `server` | HTTP contracts, hosting/startup, static assets, SSE framing and status mapping for deployment and AI resources | Constructs one of each core coordinator, store and lock set per process, and starts and stops the deployment and AI coordinators in the lifespan |
| `engine` | Stage protocol, comparison, lockfile, lifecycle and runs | Stages return values; the engine decides execution and records progress |
| `workspace` | Root discovery, layout, reference resolution, file loading, atomic writes, video probes and request facts | Owns workspace layout and containment; callers may do I/O on paths it supplies |
| `render` | Configuration and pure image passes | No workspace knowledge; callers supply images and geometry |
| `clients` | Typed protocols, transports, Printify catalog/product and Etsy APIs | Shared transport per vendor; separate caller authority through protocols |
| `config` | Validated documents, settings, money, slugs and local listing refusals | No knowledge of directory layout; path-based loaders and the design-resolution check currently perform file I/O |
| `ai` | Provider calls, prompts, saved-listing inputs, validation and cached proposals | Requests and comparison snapshots share one interpretation of saved facts; suggestions enter listing content only through acceptance |
| `listing_templates` | Template conversion and frozen document/assets/timestamp capture | Capture occurs under the template write lock before upload; shared references are revalidated at confirm and retry |
| `market` | Comparable-listing research, scoring and evidence snapshots | Read-only Etsy data informs wording rather than product facts |
| `batches` | Upload validation, staging, name allocation and idempotent local creation | Creates ordinary listings; AI dispatch belongs to `application/ai`, run only by the UI server |
| `application` | Operations shared by server and CLI: listing reads, edits, creation, rename/delete and pricing-plan choices; mockup-template calibration and preview scenes; listing-template create/edit/rename/delete; batch staging, confirm, retry, review and reads; per-listing write locks; deployment runs (`deploy`: coordinator, registry, FIFO executor, reviewed-apply check and run events); AI work (`ai`: coordinator, run registry, runner, batch queue, readiness, proposal read/resolve and run events) | Owns locking around read/merge/write and the records that follow a listing or listing template; answers with results or typed refusals, never status codes; takes only the Etsy state memo through an interface (ADR-0052); constructing a coordinator starts no thread; takes decoded images and upload streams, never request objects or caches |

`core/connections.py` builds clients and `RunContext`. Printify tokens and Etsy
bearers resolve at request time, but the Etsy app key pair is read during
construction to decide whether an optional client exists. `credentials.py`
owns credential capture, verification and storage. `prompts.py` chooses the
terminal backend and handles cancellation;
`terminal.py` is a standard-library leaf for encoding and presentation.

Three boundaries carry most of the weight. Only `workspace` knows the data
tree, including how to enumerate it. Only `engine` computes deployment changes
and folds a run's lockfile. Render passes are pure, so input hashes and golden
images describe deterministic work shared by calibration and deployment.

## What `plan` and `apply` actually do

```mermaid
sequenceDiagram
    participant User
    participant CLI as cli
    participant WS as workspace
    participant Engine as engine
    participant Stage as Stage (STAGES)
    participant Render as render
    participant Lock as state.lock.json

    User->>CLI: etsy-listings plan take-a-hike
    CLI->>WS: discover(--root / env / walk up)
    CLI->>Engine: plan_listings(ctx, names, STAGES)

    loop each listing, continue-on-error
        Engine->>Lock: read (or start empty)
        Engine->>Engine: build_plan(ctx, listing, lock, STAGES)

        loop each stage, in pipeline order (ADR-0007)
            Engine->>Lock: parse_applied_for(stage.name, stage.applied_model)
            Engine->>Stage: desired(ctx, listing, applied)
            alt desired is not Blocked
                Engine->>Stage: read_live(ctx, listing, lock, applied)
                Engine->>Stage: plan(desired, applied, live) → Verdict
            else desired is Blocked
                Engine->>Engine: record blocked StagePlan without live read
            end
        end

        Engine-->>CLI: on_planned(listing, PlannedRun)
        CLI->>User: format_plan(plan)
    end

    Engine-->>CLI: RunReport
    CLI->>User: exit 1 if report.failed

    Note over User,Lock: apply is the same walk, then the writes
    User->>CLI: etsy-listings apply take-a-hike
    CLI->>Engine: apply_listings(ctx, names, STAGES)
    Engine->>Engine: build_plan(...), then execute(ctx, planned, lock)
    Engine->>Stage: apply(...) — strictly sequential (ADR-0009)
    Stage->>Render: render(design, base, cfg) per colour
    Stage-->>Engine: StageApplyResult(applied, outputs)
    Engine->>Lock: write merged lockfile
```

The normal pipeline is `RenderStage`, `PrintifyProductStage`, `PublishStage`,
`EtsyListingStage`, `EtsyMediaStage`, then `EtsyVideosStage`, as exported by
`engine/stages/__init__.py`. Lifecycle handling selects a retract or
retire/resume path when needed. AI proposals are an editor workflow rather
than an engine generation stage.

After each successful stage, execute records the folded lockfile. Later stages
receive newly minted remote ids while still comparing against the previous
run's applied documents. A failure retains progress with an incomplete marker
so the next run can resume. Reviewed UI applies replan and verify the plan
fingerprint before executing; run resources stream progress and allow a
browser to reattach.

## The three-way comparison

Each stage's own `plan()` compares three states using the shared helpers in
`engine/change.py`:

```mermaid
graph LR
    D["<b>desired</b><br/>config files + rendered mockups"] --> Diff{"stage.plan()"}
    A["<b>last applied</b><br/>state.lock.json → applied.&lt;stage&gt;"] --> Diff
    L["<b>live</b><br/>Printify + Etsy<br/>or local output existence"] --> Diff
    Diff --> SP["StagePlan(will_run, changes, drift)"]

    D -. "≠ applied ⇒ a change you made".- A
    A -. "≠ live ⇒ drift, someone edited outside the tool".- L
```

`local = True` means there is no remote drift to report; it does not suppress
`read_live()`. Render reads the existence of previously applied output files
and recorded scene hashes, returning `RenderLive` when applied state exists.
It reports missing local outputs as work to redo. `None` can also mean a remote
resource has not yet been created; each stage interprets its own live type.

## Two hashes, doing different jobs

```mermaid
graph TD
    Design["design bytes"] --> IH
    Template["template.yaml + colour images"] --> IH
    Cfg["resolved RenderConfig per colour"] --> IH
    IH["<b>render input_hash</b><br/>canonical_hash(render input payload)"] --> Rerender{"re-render?"}

    Png[".cache/renders/*.png bytes"] --> OH["<b>outputs</b><br/>per-file content hash"]
    OH --> Reupload{"re-upload?"}
```

Separate hashes allow changed rendered bytes to trigger uploads independently
of input changes. They do not themselves force a re-render after a library
upgrade: current input and scene hashes have no renderer revision, so existing
renders and previews can survive such a change. Exact library pins constrain
this risk; an intentional renderer/library change needs cache invalidation
until that gap is repaired. `applied_at`, `tool_version`, `remote` and absolute
paths never enter a hash; paths that do are workspace-relative and
forward-slashed, so a Windows machine and a Linux runner agree.

`Lockfile.input_hash()` hashes the whole applied subtree. The render stage also
hashes its own input payload and each scene payload. Reviewed applies hash the
presentation `Plan` and stable stage review-input digests without snapshots; cache and OAuth code use hashes for
other purposes. The restriction on volatile deployment inputs is not a ban on
those separate keys. Render stages expose their input digest through the
optional `review_hash` hook: design/photo/template-byte edits invalidate a
reviewed apply even when action paths and reasons remain identical (ADR-0039).
Preview completion and transient CDN URLs remain excluded from review identity.

## The calibrator

```mermaid
graph LR
    Canvas["Calibrate tab<br/>quad handles + sliders"] -->|"POST /preview?scale=editor<br/>(debounced)"| API["server/api"]
    Tab["Preview tab<br/><i>on demand</i>"] -->|"POST /preview?scale=full"| API
    API --> Cache["server.api.imagecache<br/><i>decoded photo, design, maps</i>"]
    Cache --> RenderPipe["render.pipeline<br/><i>the same code apply runs</i>"]
    RenderPipe -->|WebP| Canvas
    RenderPipe -->|PNG| Tab
    Canvas -->|"PUT /config"| API
    API -->|writes| Yaml["mockup-templates/&lt;set&gt;/template.yaml"]
    Yaml -->|read by| Stage["engine render stage"]
```

The preview is the real renderer, not an approximation — that is the whole
point of calibrating in a browser. `template.yaml` is the artefact the
calibrator produces and the render stage consumes. Separately, UI deployment
plan runs call `preview_listing()` after planning and write full-size,
content-addressed previews. Apply copies a matching preview into render outputs
instead of rendering again, retaining the preview for reattachment (ADR-0040).
Those deployment previews are distinct from the calibrator's HTTP previews.

"Real renderer" is now structural rather than a claim maintained by hand. Both
paths ask `Workspace.scene_photo()` which photo a scene composites over and
what its derived maps cache under, and both composite through
`render_scene()`. The one thing the preview does differently is where its
geometry comes from — the unsaved boxes under the user's cursor, not the file
on disk — which is exactly the difference that makes it a preview.
`application.mockup_templates` decides the scene (photo, layers, design) and
composites it from images the server supplies out of its memo; encoding the
frame as WebP or PNG is the server's.

### Two sizes, one pipeline

A drag emits a preview request every few frames, and at a real garment photo's
resolution each one re-decoded the mockup PNG and the design PNG from disk,
warped at full size, and PNG-encoded several megabytes — seconds of work per
frame, for an image about to be replaced. So the two things a preview is *for*
were separated:

| | Calibrate tab | Preview tab |
|---|---|---|
| Request | `?scale=editor` | `?scale=full` |
| Base | downscaled to `EDITOR_MAX_EDGE` (900px) | the photo's own size |
| Encoding | WebP, low effort | `encode_png`, as `apply` writes |
| When | debounced, one in flight at a time | on opening the tab, then only on Re-render |

Both run `render_scene()` over the same photo and derived maps. What differs
is how many pixels the server is asked to spend, which is why the fast one is
still honest: it is the output, at a size you can drag against.

The Preview tab renders itself on first sight and then holds still. A config
edit afterwards does not re-run it — a full-size set is minutes of work, and a
nudged box is not a request for it — but it must not silently become a picture
of geometry that has moved on either, so Re-render turns red. The panel stays
mounted behind the canvas rather than unmounting, or flicking between tabs
would throw the renders away and "there is none, so render" would fire on a
set that had just been rendered.

Two consequences worth knowing:

- **Bounding boxes stay in the photo's true pixel space.** `template.yaml`
  stores them there, so `application.mockup_templates.scaled` scales them (and `displace.strength`,
  which is denominated in absolute pixels) onto the smaller canvas, and the
  client is *told* the true size in `TemplateSummary.width`/`height` rather
  than measuring the image it is drawing over. Measuring it would save every
  box a few times too small, with nothing on screen looking wrong.
- **`server.api.imagecache` memoises what the loop re-reads** — the decoded photo
  at each size, the decoded design, and the derived maps — keyed on path and
  mtime, bounded by total bytes rather than entry count. It sits in `server`, not
  in `render.io`: the render stage reads each file once per run and needs no
  cache, and giving it one would put mutable process state under the pure
  layer for nobody's benefit.

## UI resources, AI and batch creation

`server/api/app.py` assembles one workspace, deployment coordinator
(`core/application/deploy`), AI coordinator (`core/application/ai`: run
registry, runner and batch queue), proposal store, staging/batch stores and
write-lock collection per server process. Its lifespan starts deployments then
AI work, and stops AI work -- the batch queue, then the runs -- before
deployments. FastAPI serves the generated-contract
routes and built SPA. React Router provides the dashboard, listings and editor,
individual/workspace deployment, listing-template editor, batch upload/staging/
summary and mockup calibrator routes (`src/ui/src/main.tsx`). Setup and
authentication remain terminal workflows, not a web setup wizard.

Deployment uses one FIFO worker for the workspace, started and stopped by the server lifespan. The registry reserves
listing names when a run is queued; reviewed applies carry fingerprints and
the exact reviewed listing set (ADR-0039, ADR-0042). Engine events become SSE
events retained in memory, so a browser can reconnect while the server lives.
There is no SQLite run-history recorder. AI runs have their own registry and
thread per run, with cancellation propagated to provider subprocess trees.
Both registries are lost on process restart; listing state and cached proposals
persist on disk.

The AI runner optionally drafts an empty brief, extracts three buyer queries,
researches comparable Etsy listings, then generates and validates a proposal.
The default provider order is Codex, Claude, Grok, with availability fallback,
one same-provider repair for invalid output and a shared deadline. Market
search/stat caches live for seven days; the latest per-listing evidence snapshot
is separate. Research is read-only and supplies wording evidence rather than
new garment facts (ADR-0044). The runner may save an automatically drafted
brief after rechecking that it is still empty; SEO suggestions enter the listing
through the seller's acceptance workflow (ADR-0003).

`ProposalStore` retains one latest proposal with its input snapshot, generation
time, origin and per-section resolutions. Staleness is judged on every read
(`core/application/ai/listing_proposals.py`), never stored; stale proposals
remain reviewable. A proposal is persisted before its streamed
event, and full successful apply clears it through the engine, including CLI
apply (ADR-0049, ADR-0050).

Listing templates are distinct from mockup templates: they capture commercial
configuration and media references, while mockup templates define render
geometry. Upload staging freezes the selected listing-template document and
owned assets under its write lock. Bounded loose-PNG/ZIP inspection precedes
review; confirm and retry revalidate shared references and allocate names under
a name lock. They create ordinary listings and retained batch records,
idempotently, without deploying (ADR-0047, ADR-0051). Staging expires seven days
after its last edit and is swept at startup. `BatchQueue` dispatches queued
rows through the existing AI runner, defaults to one concurrent batch row,
reads the workspace concurrency setting, and recovers interrupted rows on
restart (ADR-0048).

Before a UI plan or apply begins, the deployment coordinator yields its
listings to the AI coordinator, which cancels their queued batch AI, stops and
awaits active AI, and holds those names against new AI
until deployment ends. CLI does not coordinate with this queue (ADR-0050).
`WorkspaceLocks` serializes UI read/merge/write operations and name changes
inside one process. There is no cross-process lock protecting concurrent CLI
and UI writes, nor a supported shared registry across multiple ASGI workers.
Atomic file replacement prevents torn files; it does not prevent lost updates.

## Workspace references and media ownership

`Workspace.discover()` honors an explicit root, then `ETSY_LISTINGS_ROOT`, then
walks upward for `shop.yaml`; user data belongs outside the application checkout.
The layout includes garment/pricing profiles, common media/copy, test designs,
prompts, listing templates and `settings.yaml` as well as the original listing,
design and mockup directories. Cache accessors cover catalog data, renders,
previews, market evidence, proposals, staging sessions and batch records.

File references without a prefix resolve from the workspace root. `./` resolves
from the owning listing or listing-template directory; subdirectories are
allowed, while absolute paths, backslashes and `..` segments are refused
(ADR-0046). Reference resolution checks the resolved target against the root.
Layout names are validated as single segments, but not all layout accessors
check symlink/junction containment; that remaining gap is audit finding F02.

The ordered `media` gallery combines explicit rendered scenes with image/video
file references (ADR-0045). Images use content hashes and an ordered remote-id
manifest; variation images use the configured template (ADR-0030, ADR-0031).
The video stage follows images because attachment position depends on image
count. PyAV facts feed shared local video checks before original bytes are
uploaded; vendor slot/budget refusals remain distinct from local validation.
Printify creates the Etsy draft; Etsy stages then own copy, image and video
updates. Selective publish flags and field ownership prevent Printify from
overwriting Etsy-owned content (ADR-0001, ADR-0021).

## Invariants

These are the things that are easy to break by accident and expensive to notice
later. Each traces to a decision.

### Engine and stages

- **Only `engine` computes a diff.** The CLI renderer and the UI serialiser both
  consume `Plan` / `StagePlan` / `Change` objects. Neither may compare states
  itself — that is what makes the CLI and UI enforce identical rules (ADR-0008).
- **Only `engine` runs a run.** The same rule, one level up: reading a
  listing's lockfile, planning it, executing it, writing the lockfile back and
  carrying on past a failure all live in `engine/run.py`, behind
  `plan_listings` / `apply_listings`. An entry point supplies the listings and
  formats the resulting `RunReport`. Read-only UI status queries currently
  open lockfiles through the engine's `Lockfile` type; that is not a second
  deployment walk, but interpreting stage-owned state there is an audit finding.
  The engine also exports `build_plan` / `execute` for callers owning an
  individual lockfile, without moving stage execution into those callers.
- **Only the lockfile merges a lockfile.** `Lockfile.fold()` owns the
  replace-versus-merge rules for all four axes, `applied_for()` owns the
  per-stage lookup and `parse_applied_for()` owns the decode. A stage returns
  a `StageApplyResult` and never touches the file; `execute` decides only
  which stages run, in what order.
- **A stage's applied document is a type, not a dict — and the stage does not
  decode it.** The lockfile stores it as JSON; `build_plan` hands `plan()` the
  model the stage declared in `applied_model` (`RenderApplied`,
  `AppliedProduct`). A stage that reads its own document with
  `applied.get("title")` ends up spelling the key names again in every
  function that touches them. Decoding answers `None` for both "never
  applied" and "will not decode", because a document we cannot read is one we
  cannot prove the live state matches. **Every question a stage is asked gets
  it**, `apply()` included. That rule is the lockfile's precisely because it
  was two stages' and they disagreed: one caught `ValidationError` and
  answered `None`, the other indexed the dict and raised `KeyError`, which is
  not a `UserFacingError` and so ended a whole `--all` batch.
- **A refusal is `Blocked`, whichever question produced it.** One vocabulary for
  "this cannot run", reaching the plan two ways because a refusal has two
  moments. A **pre-flight** refusal — no shop configured, copy still a
  sentinel, a design too small — is `desired()` returning `Blocked`, before a
  document exists for a run that was never going to happen. A refusal only the
  live state can prove — a retail price below Printify's cost, which needs
  `variants[].cost` and therefore cannot be known before `read_live` (ADR-0020's
  amendment) — is `plan()` returning `Verdict.refused(...)`, which the engine
  turns into the same `StagePlan.blocked`. Neither may raise, and a stage still
  never names itself. What is forbidden is the third shape: a stage that will
  not run reporting a `reason` instead. `format_plan` prints a reason only for
  stages that *do* run, so a listing priced under cost skipped `publish` in
  silence, under a plan reading "No changes."
  Missing render templates/photos, template-kind colour mismatches and
  unresolved artwork use shared config checks and return `Blocked`. Template
  load failures are adapted to the same stage refusal. Artwork resolution
  errors are actionable at exceptional boundaries and caught in desired state.
- **One rule behind that vocabulary, not one per reader.** `config/listing_validation.py`
  owns every local refusal about a listing — predicate, message and all — and
  `engine/stages/gates.py` is the adapter that turns one into a `Blocked` for a
  stage, exactly as `Issue`'s tab and severity turn one into a line in the
  editor's banner. These were once two modules and the garment-profile rule
  diverged: `.strip()` on the engine's side, a bare truth test on the editor's,
  so a `garment_profile: " "` passed `plan` and failed the banner about the same
  file. A new local refusal is a check function there and nothing else.
  The variation-template membership check is still duplicated in
  `EtsyMediaStage.desired()` (F15).
- **A check reads the workspace through `WorkspaceFacts`, gathered once.**
  `check_listing` takes no workspace, but currently opens design images through
  `check_design_resolution`; full purity is an unmet contract (F04). Build one
  `WorkspaceFacts` where a request begins and hand it down; never load a profile or a template
  config beside a check (each listings-table row used to re-parse the entire
  template catalogue).
- **`will_run` is derived from a reason, never computed beside one.** Two
  expressions of one rule are how a stage comes to run while reporting nothing
  to do.
- **`apply` is strictly sequential.** The current planner also walks stages
  in pipeline order. The original read-only fan-out design (`ADR-0009`) is not
  implemented; it is not permission to parallelise writes.
- **`plan` checks two things, not one: would the output differ, and is the
  output still there.** The render cache is gitignored and fully derivable, so
  it is a directory users delete. A stage's `read_live()` is called even when
  `local` is true — `local` means "no *remote* state", so no drift reporting
  and no thread-pool fan-out, not "reads nothing" (`ADR-0007`).

### Hashing

- **A hashed document must not depend on the order its inputs happened to
  arrive in.** Sort unordered collections before hashing; preserve intentional
  gallery order and compositing layer order. Variant ids reached
  `print_areas[].variant_ids` in the order a listing wrote `colors:`, so
  reordering that list changed `input_hash` and re-applied a product nothing
  about which had changed.
- **Nothing volatile enters a deployment input hash.** No timestamps, absolute
  paths, raw model responses or `tool_version`. The aggregate lockfile hash
  includes only its `applied` subtree via `canonical_hash()`; volatile bookkeeping
  stays outside it. Violating this makes every run show a spurious diff.
  `canonical_hash()` is also reused for render-input/scene
  payloads and review fingerprints; those are distinct from the aggregate
  lockfile input hash. Accepted AI copy is ordinary saved listing content;
  raw provider responses and proposal metadata are not deployment inputs.
- **Paths inside hashed content are workspace-relative and forward-slashed.**
  Non-negotiable on Windows, where the same content would otherwise hash
  differently than on Linux.
- **Two hash axes, not one.** `input_hash` decides whether to re-render;
  `outputs` (per-file) decides whether to re-upload. Collapsing them breaks the
  library-upgrade case described above.

### Rendering

- **Render passes are pure.** No I/O, no globals, no clock. Inputs are ndarrays
  and frozen config. This is what makes both the hash and the goldens meaningful
  (`ADR-0012`).
- **Geometric resampling specifies interpolation and border behavior.**
  `warpPerspective` uses `flags` and `borderMode`; `remap` uses `interpolation`
  and `borderMode`; Sobel/GaussianBlur specify `borderType`. Calls such as
  `cvtColor` and `getPerspectiveTransform` have different contracts and do not
  take those keywords. `test_no_bare_cv2.py` checks the applicable render calls.
- **Rendering is driven purely by `media`.** A scene renders only if some
  `media` entry references it — `listing.colors` drives which Printify
  variants sell, not which photos get rendered.
- **A template is exactly one of three kinds — never a mix.** `kind:
  colour-matrix | multiple | single`, a discriminated union (`ADR-0014`). **No
  garment-profile-level registry of listing templates** — a template lives
  purely in `mockup-templates/{name}/`, and any listing may reference any of
  them. A listing's `media:` always names `{template, colour?}` explicitly —
  there is no default template and no bare-colour shorthand (`ADR-0015).
  `GarmentProfile.preview_template` is the one exception: a single
  `colour-matrix` template the editor uses to judge colours, not a `media:`
  default.
- **`colour-matrix`-kind mockup filename = slugified Printify colour name.**
  Convention, not a mapping table. A sparse `exceptions.yaml` handles what
  will not slugify (ADR-0004). When nothing matches exactly, `template_base_image`
  falls back to a filename ending in the slug's hyphen segments — but only if
  exactly one photo in the directory qualifies; two candidates is refused, not
  guessed at. That fallback is lookup-only: `template_colours` still reports
  a non-matching filename as its own name, since deriving a colour from an
  unknown shared prefix (enumeration) isn't the same question as matching a
  known slug against one (lookup). `multiple`- and `single`-kind templates use a
  fixed `scene.png` instead (ADR-0014). **The browser is never told this rule**;
  it is served the answer. `TemplateSummary.photos` carries each scene's real
  workspace-relative path, resolved through `Workspace.scene_photo`, because the
  editor's caption used to compose one from the convention and so named a
  missing file for exactly the pack the fallback exists for.

### Workspace, credentials and prompts

- **Only `workspace` knows the directory layout — including how to *list* one.**
  Everything else asks for `workspace.lock_file(name)` rather than joining
  `listings/<name>/state.lock.json`, and for `workspace.template_photos(name)`
  rather than globbing `mockup-templates/<name>/*.png`. Two rules enforce it:
  `resolve()` rejects paths escaping the root (`ADR-0013`), and the layout accessors
  reject any name that is not a single path segment. Together they keep the UI's
  endpoints safe — template names arrive from URLs — so this is a security
  boundary, not a tidiness rule. A new path-taking CLI option or endpoint goes
  through them, and so does a new `glob`.
  `Workspace.prune_previews` owns stale-preview enumeration and removal;
  `relative_path` serializes paths for HTTP. Engine status operations decode
  remote identities and applied lifecycle, keeping stage persistence out of UI.
- **A client is built through `connections.py`.** Which credential is resolved
  when, what a missing one means, and where the Etsy token file lives are one
  set of answers, not four (`cli`, `setup`, `auth` and the e2e layer each used to
  assemble the Etsy client themselves). The rule the module exists to hold: **a
  credential is resolved when it is used, never when a client is built**, so a
  workspace that has only ever rendered mockups can still `plan`. Etsy app keys,
  bearers and Printify tokens are lazy sources; the explicit `etsy_app_key`
  availability query is reserved for readiness/setup operations. Setup still assembles an Etsy
  shop client outside this module (F06).
- **A credential is captured, verified and stored through `credentials.py`.**
  Where it already lives (environment, then the workspace `.env`), what to say
  before asking, how to ask, how to prove it, and what to say when it fails.
  Capturing stays separate from storing because `auth` writes per credential as
  it goes while `setup` writes once every question is answered.
- **Secrets never enter the repo.** Tokens in `.auth/`, keys in `.env`, both
  gitignored, and both in the *workspace*, not the repo. `config/secrets.py` is
  the reader for environment/file API keys; `clients/etsy/tokens.py` owns OAuth
  token-file reads, writes and persist-before-use refresh (ADR-0027). A missing
  credential is reported by name and file, never as a raw `401` traceback.
- **A cancelled prompt raises; it is never a `None` a caller might miss.**
  `prompts.choose`/`text`/`confirm` answer `None` because that is the honest
  shape for a backend, but no wizard uses them directly — `pick`, `ask_choice`,
  `ask_text` and `ask_confirm` raise `prompts.Cancelled`, caught once in
  `cli/app.py`. A missed `None` here writes a `None` to a file.
- **Every price carries an explicit currency.** Bare numbers are rejected at
  validation. Retail uses the configured Etsy channel currency (NOK in the
  fixture/default setup); Printify manufacturing costs are USD. Apply does not
  convert retail prices, and the below-cost check requires comparable currencies
  (ADR-0019, ADR-0020). A bare number is a bug
  waiting to be a refund (ADR-0006).

## Testing layers

| Layer | Answers |
|---|---|
| Unit | Does this function obey its contract? (`Money`, slugs, hashing, path safety) |
| Golden | Did the pixels change, and which pass changed them? |
| Behaviour | Does plan/apply do the right thing over time? (idempotency, re-render on change) |
| Browser | Do the React app, the API and the renderer work together? |
| Contract | Does the wire payload match what the API expects? |
| E2E | Does it work against the real Printify and Etsy? |

Reach for a fake to test behaviour and a cassette to test payload shape. The
browser layer exists because nothing below it can catch a wiring mistake
between three otherwise-tested pieces.

`scripts/check.sh` formats, lints, typechecks, checks the Import Linter
contracts in `pyproject.toml` (core/server/CLI dependency direction, ADR-0052)
and runs Python coverage, then
the equivalent frontend gates when npm is available. Both coverage gates use
an 85% floor with branch measurement. Browser tests skip when prerequisites
are missing unless `ETSY_LISTINGS_REQUIRE_EVERY_LAYER=1`; E2E tests have
credential guards and default pytest options exclude them.

CI runs Python and frontend gates on PRs, main pushes and manual runs, followed
by a browser job on every trigger. The Python job explicitly uses
`-m "not browser and not e2e"`: a command-line marker replaces the default,
so both exclusions must be stated. Browser checks require Chromium and the
built SPA and prohibit clean skips. Real-API E2E stays in its separate
main/manual workflow. No live API tests were executed during this audit or repair.

The CLI currently exposes `setup`, `auth`, `new`, `plan`, `apply`, `unlock` and
`ui`. Dedicated `render`, `generate`, `catalog refresh`, `status`, a persisted
run-history recorder and a general persisted rate-budget module are absent.
Current transports already share retries, and Etsy has a per-transport,
header-driven `RateGate`; their existence does not imply those future modules.
