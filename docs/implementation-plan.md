# Implementation Plan: Etsy Listing Automation

Companion to [prd.md](prd.md). The PRD settles *what* the tool does and 27 product
forks; this document settles *how* it is built — module boundaries, core contracts,
and the order of work. Where the two disagree, the PRD wins and this file is wrong.

---

## Architecture decision log

Fifteen forks, resolved. Numbered `A#` so they can be cited from code comments
and commit messages without colliding with the PRD's own decision log.

| # | Fork | Decision |
|---|---|---|
| A1 | plan/apply engine | Staged pipeline. A fixed ordered list of `Stage` objects sharing one protocol; `local: bool` marks a stage as having no *remote* state, which suppresses drift reporting and keeps its `read_live()` out of A3's fan-out — it does not mean the stage reads nothing, since a local stage still owns outputs on disk that `plan` has to verify. Dependencies are list order, not a graph. |
| A2 | State + diff | `state.lock.json` stores the **verbatim last-applied desired document**. Each stage writes its own `plan()` comparing desired/applied/live and emitting `Change` objects, over a shared vocabulary and shared comparison helpers. |
| A3 | Concurrency | Sync core throughout. `plan`'s live-state reads fan out over a bounded thread pool; `apply` is strictly sequential. One thread-safe token-bucket limiter shared by every path. |
| A4 | API layer | Narrow `Protocol` per API returning pydantic models. In-memory fakes drive the behavioural suite; a small set of cassette-replay contract tests pin payload shape; a manual `-m e2e` run exercises the real APIs on demand and doubles as the cassette recorder. |
| A5 | UI stack | FastAPI JSON API + React/TypeScript built with Vite. TS client **generated** from the OpenAPI schema — never hand-written. SSE for progress. |
| A6 | Run history | SQLite at `.cache/runs.db` in WAL mode, `runs` + `run_events`. One recorder shared by CLI and UI, so CLI runs appear in the dashboard. Disposable: drop-and-recreate rather than migrate. |
| A7 | Renderer | Pure functions over ndarrays composed in fixed order. Frozen pydantic `RenderConfig`; its canonical JSON is the hash. Explicit determinism controls. Goldens per pass *and* end-to-end. Extended by A12 for `multiple`-kind scenes: a **separate** `render_scene()`/`export_many()`, not a generalisation of the single-layer `render()`/`export()` — zero regression risk to the pre-existing goldens, verified by an explicit byte-identity test. |
| A8 | Workspace | The data tree is a separate directory you own, marked by `shop.yaml`, discovered by walking up from cwd. `--root` / `ETSY_LISTINGS_ROOT` override. All config paths resolve against the workspace root, never cwd. |
| A9 | Review gate | The Etsy draft is the only gate; `apply` generates and pushes in one run. `generate` remains standalone for when you want to read the copy first. |
| A10 | Build order | Strict PRD phase order, 0 to 6. |
| A11 | Template kind schema | Discriminated pydantic union on `kind` (`ColourMatrixTemplate \| MultipleTemplate \| SingleTemplate`, `Field(discriminator="kind")`), loaded via `load_template_config()` — no wrapping model, since the file *is* one of the three shapes. PRD 28. |
| A12 | Multi-layer rendering | `render_scene()`/`Layer`/`export_many()` in `render/pipeline.py`/`render/passes.py`, `multiple`-kind only. The existing single-layer `render()`/`export()` are untouched, not generalised — see A7. |
| A13 | Template ownership + media addressing | No profile-level registry — `Profile` carries no `templates` field. `listing.media` always references `{template, colour?}` explicitly, naming any template that exists in `mockup-templates/`; no default, no bare-colour shorthand. A template is purely local and Etsy-facing (Printify never sees it), unlike `blueprint`/`print_provider`/`sizes`, which genuinely are Printify product-creation inputs — that's why templates don't live on the profile the way those do. PRD 29. |
| A14 | Artwork resolution | `listing.artwork[colour]` > template/placement override > `profile.colour_tone`-derived key > design map's sole key. Implemented once, in the render stage (`engine/stages/render.py::_resolve_artwork`), reused unchanged by the future `printify_product` stage (Phase 2). PRD 30. |
| A15 | Render cache namespacing | `.cache/renders/{listing}/{template}/...`, not `.cache/renders/{listing}/{colour}.png` — namespaced by template, since a listing can reference more than one `colour-matrix`-kind template and a bare colour is no longer unique across them. |
| A16 | Calibrator test design | A **library**, not the fixed `BundledDesign` literal it replaces. The three bundled targets stay and keep their ids; the preview endpoint resolves an arbitrary id against those plus PNGs the user has uploaded into the workspace, and an unknown id is a 400 rather than a `KeyError`. The literal was right while the only designs were the ones shipped in `api/static/`, but calibration is judged by eye, and the grid target answers "is the warp right?" while saying nothing about how a real ink weight sits on a real garment. The set has to be open for the second question. Uploads land in the workspace, never the repo. |

### Toolchain

uv + `pyproject.toml`, Python 3.12+, `src/` layout, hatchling, Typer, pydantic v2,
httpx, OpenCV + Pillow (both **version-pinned** — PRD risk 9), ruff, pytest.

The Vite build runs from a hatchling build hook only when `ui/frontend/dist` is
absent, so wheels published from CI carry the built assets and installing them
needs no node.

---

## Package layout

```
src/etsy_listings/
  cli/                  Typer app; one module per command
  workspace/            root discovery, path resolution, layout constants
  config/               pydantic models: defaults, profile, listing, exceptions
    money.py            Money type — parsing, currency validation
    slug.py             slugification rules + exceptions file + collision detection
  catalog/              Printify catalog fetch, TTL cache, name to id resolution
  engine/
    stage.py            Stage protocol
    change.py           Change vocabulary + comparison helpers
    lock.py             state.lock.json model, read/write, hashing
    context.py          RunContext (workspace, clients, limiter, event sink)
    plan.py             builds a Plan across stages
    apply.py            executes a Plan, resumable
    stages/             render, generate, printify_product, publish, etsy_copy, etsy_media
  render/
    config.py           frozen RenderConfig, TemplateConfig
    passes.py           warp, displace, shade, export — pure functions
    maps.py             derived height/luminance maps + _derived/ cache
    pipeline.py         render()
  clients/
    printify/           protocol.py http.py models.py fakes.py
    etsy/               protocol.py http.py models.py fakes.py oauth.py
    limiter.py          token buckets, incl. persisted daily budget
    retry.py            backoff policy
  ai/                   prompt loading, generation, hard validation
  fx/                   USD to NOK fetch + .cache/fx.json with TTL
  runs/                 SQLite recorder, schema, event types
  ui/
    api/                FastAPI app, routers, schemas, SSE
    frontend/           Vite project, dist/ shipped as package data
```

---

## Core contracts

### `Stage`

```python
class Stage(Protocol):
    name: str
    local: bool                      # True => no remote state, so no drift

    def desired(self, ctx: RunContext) -> Desired: ...
    def last_applied(self, lock: Lockfile) -> Applied | None: ...
    def read_live(self, ctx: RunContext, listing, lock) -> Live | None: ...
    def plan(self, desired, applied, live) -> StagePlan: ...
    def apply(self, ctx: RunContext, plan: StagePlan) -> StageResult: ...

STAGES = [Render(), Generate(), PrintifyProduct(),
          Publish(), EtsyCopy(), EtsyMedia()]
```

| Stage | `desired` | `read_live` | `apply` |
|---|---|---|---|
| `render` | design/artwork bytes hashes + template assets + resolved `RenderConfig`(s) per referenced scene (A11–A14) | which rendered files still exist under `.cache/renders/` | render each scene actually referenced by `media` into `.cache/renders/{listing}/{template}/` (A15) |
| `generate` | brief + design hash + profile context + prompt template hashes | whether `generated.yaml` still exists | call the model, validate hard, write `generated.yaml` |
| `printify_product` | blueprint/provider ids, enabled variant matrix, per-variant prices in cents, print areas | `GET products/{id}`, incl. `visible` (below) | create or update product |
| `publish` | sync flag set `{variants: true, title/description/images/tags: false}` | product `external` block | `POST publish.json`, poll for `external.id` |
| `etsy_copy` | title, description, tags, materials, section, `should_auto_renew` | `getListing` | `updateListing` |
| `etsy_media` | ordered media manifest, each entry `(ref, content_hash)` | listing images + ids | full delete-and-reupload in rank order |

Local stages have no *remote* state — that is what `local: bool` encodes, and it
buys two things: drift is undefined for them, so the engine skips drift reporting
rather than each stage having to remember; and their `read_live()` is cheap and
local, so it never joins A3's live-fetch pool.

It does not mean they observe nothing. `render` writes PNGs into a gitignored,
fully derivable cache, which is precisely the kind of directory people delete;
`generate` writes `generated.yaml`. Those outputs are live state in every sense
that matters — they simply have no second writer to have drifted *from*. So
every stage's `read_live()` is called, local ones included, and a difference a
local stage finds is reported as work to redo rather than as drift.

This paragraph used to say local stages have no live state at all, which read as
licence to skip the read entirely. `plan` duly reported "No changes." over a
half-emptied render cache, and `apply` did nothing to refill it.

### Draft-vs-live cannot be set through the API — PRD risk 5, resolved in one direction

Checked directly against Printify's API Reference (`developers.printify.com/docs/`):
Product has a documented `visible` field ("Used for publishing. Visibility in
sales channel", defaults to `true`) but it is marked **read-only**, and the
`publish.json` request body only accepts `images`, `variants`, `title`,
`description`, `tags`, `shipping_template` — `visible` is not among them, and it
is absent from the create/update product bodies and from the Shop resource too.

**"Hide in Store" is a Printify web-app UI action, not an API parameter.**
Nothing this tool sends can make a publish come in as a draft; the shop's
Etsy-connection setting (`docs/setup.md` §1.2) is the only lever, and it must be
set by a human in Printify's UI before the first `apply` ever publishes.

What the API *does* give us: `visible` comes back on `GET products/{id}`, so
`printify_product.read_live()` reads it and the stage surfaces a warning if a
product it manages ever comes back `visible: true` — a tripwire, not a fix,
since nothing here can correct it.

**Still open, and only answerable against the real Printify account (Phase 2's
job, not this doc's):** whether the shop's draft setting is a persistent
per-shop default that holds for every future publish, or something that reverts
and needs re-confirming — write this into `docs/api-findings.md` before Phase 2
exits, citing this section.

### `Change` vocabulary

Per A2 each stage writes its own comparison, so the shared surface is the
vocabulary and a handful of helpers — not a generic differ. Keeping the *mechanics*
shared is what stops six near-identical routines diverging.

```python
@dataclass(frozen=True)
class FieldChange:  path: str; before: Any; after: Any
class ListChange:   path: str; added: list; removed: list; reordered: bool
class PriceChange:  size: str; colour: str | None; before: Money; after: Money
class MediaChange:  rank: int; before: str | None; after: str | None
class StageRun:     stage: str; reason: str          # "design changed"
class Drift:        path: str; last_applied: Any; live: Any

# helpers every stage calls
def scalar(path, desired, applied) -> FieldChange | None: ...
def sequence(path, desired, applied) -> ListChange | None: ...
def drift(path, applied, live) -> Drift | None: ...
```

`StagePlan(stage, will_run, changes, drift)` and
`Plan(listing, is_live, etsy_listing_id, stage_plans)` are the units the CLI
renderer and the UI's JSON serialiser both consume. **Neither entry point may
compute a diff itself** — that is what guarantees the PRD's "one set of rules
regardless of route".

### Lockfile

```json
{
  "schema_version": 1,
  "tool_version": "0.3.1",
  "applied_at": "2026-09-03T10:14:02Z",

  "applied": {
    "render":   { "input_hash": "sha256:...", "config": {}, "colors": ["black", "moss"] },
    "generate": { "title": "...", "description": "...", "tags": [], "alt_text": {} },
    "printify_product": { "blueprint_id": 6, "print_provider_id": 29,
                          "variants": [{"id": 17887, "price": 4990, "is_enabled": true}],
                          "print_areas": [] },
    "publish":  { "sync_flags": {"variants": true, "title": false, "images": false} },
    "etsy_copy":{ "title": "...", "description": "...", "tags": [], "materials": ["cotton"],
                  "shop_section_id": 4455667, "should_auto_renew": false },
    "etsy_media": { "manifest": [{"ref": "mockup:black", "hash": "sha256:..."}] }
  },

  "remote":  { "printify_product_id": "...", "etsy_listing_id": 1234567890,
               "etsy_image_ids": [111, 112], "etsy_listing_state": "draft" },
  "outputs": { ".cache/renders/take-a-hike/black.png": "sha256:..." },
  "stages_completed": ["render", "generate", "printify_product", "publish",
                       "etsy_copy", "etsy_media"]
}
```

`applied` is the last-applied desired document, verbatim and normalised — so
`desired` vs `applied` is a comparison of two identically-shaped objects, and the
diff can show real before/after text without re-deriving anything.

**Hashing rules, enforced by a single `canonical_hash()` helper:** hash only the
`applied` subtree; `applied_at`, `tool_version`, `remote` and absolute paths are
excluded. Paths inside hashed content are always workspace-relative and
forward-slashed. A test asserts that two runs with no input change produce
byte-identical `applied` subtrees — this is the guard against the PRD's "every run
shows a spurious diff" failure.

`outputs` carries per-file **output** hashes and is the separate axis the PRD
requires: `input_hash` decides whether to re-render, `outputs` decides whether to
re-upload. A library upgrade that changes render bytes therefore triggers a
re-upload, correctly and visibly.

### Workspace

```python
class Workspace:
    root: Path                       # dir containing shop.yaml
    defaults: Defaults

    @classmethod
    def discover(cls, start: Path | None = None) -> Workspace: ...
    def resolve(self, ref: str, relative_to: Path) -> Path: ...   # never escapes root
    def cache(self, *parts: str) -> Path: ...
```

Discovery walks up from cwd for `shop.yaml`, honouring `--root` then
`ETSY_LISTINGS_ROOT` first. `resolve()` rejects paths that escape the root, which
also makes the UI's file-serving endpoints safe by construction.

---

## Renderer

```python
def warp(design: NDArray, bounding_box: BoundingBox, output_size: tuple[int, int]) -> NDArray: ...
def displace(img: NDArray, cfg: DisplaceConfig, height: NDArray) -> NDArray: ...
def shade(img: NDArray, cfg: ShadeConfig, luminance: NDArray) -> NDArray: ...
def export(base: NDArray, print_layer: NDArray) -> Image.Image: ...

def render(design, template_base, cfg: RenderConfig, *, height=None, luminance=None) -> Image.Image:
    x = warp(design, cfg.bounding_box, template_base_size)
    if cfg.displace.enabled: x = displace(x, cfg.displace, height)
    if cfg.shade.enabled:    x = shade(x, cfg.shade, luminance)
    return export(template_base, x)
```

`multiple`-kind scenes (several garments in one photo) use a separate
`render_scene()` over a list of `Layer`s, folded by `export_many()` — not a
generalisation of the single-layer path above, so it carries zero regression
risk to it (A12).

Every pass is pure: no I/O, no globals, no clock. All inputs arrive as arrays or
frozen config, which is what makes both the hash and the goldens meaningful.

**Determinism controls** (PRD risk 9): OpenCV and Pillow pinned to exact versions;
every `cv2` call passes explicit `interpolation` and `borderMode` rather than
relying on defaults; PNG encode is deterministic with no timestamp chunks; colour
handling is fixed at 8-bit sRGB with a documented alpha compositing order.

**Derived maps** cache to `mockup-templates/{name}/_derived/`, keyed by
`hash(source image bytes + map params)`, so a template edit invalidates them
without a manual clear. The calibrator additionally holds them in memory for the
life of a preview session.

**Goldens** live at two levels. `tests/golden/passes/` renders each pass alone
against a synthetic grid/ruler target, so a regression names the guilty pass;
`tests/golden/e2e/` covers finished composites per template. Comparison is
per-pixel with a small tolerance, and `--update-goldens` regenerates with the diff
shown in the failure output.

**Calibrator latency budget:** previews render at 1200px or less on the long edge
with maps held in memory, targeting sub-300ms round trips so slider drags feel
live. Final renders always run at full resolution.

---

## Clients, limiting and retries

```python
class PrintifyClient(Protocol):
    def blueprints(self) -> list[Blueprint]: ...
    def print_providers(self, blueprint_id: int) -> list[PrintProvider]: ...
    def variants(self, blueprint_id: int, provider_id: int) -> VariantSet: ...
    def get_product(self, product_id: str) -> Product | None: ...
    def create_product(self, spec: ProductSpec) -> Product: ...
    def update_product(self, product_id: str, spec: ProductSpec) -> Product: ...
    def publish(self, product_id: str, flags: SyncFlags) -> None: ...
    def clear_publish_lock(self, product_id: str) -> None: ...
```

`EtsyClient` mirrors this for `get_listing`, `update_listing`, `upload_image`,
`delete_image`, `shop_sections`, `return_policies`.

**Rate limiting.** One `TokenBucket` per named budget, all behind a single
`threading.Lock` so the `plan` thread pool and the sequential `apply` path share
them:

| Budget | Limit |
|---|---|
| `printify:global` | 600/min |
| `printify:catalog` | 100/min |
| `printify:publish` | 200/30min |
| `etsy:burst` | 10/sec |
| `etsy:daily` | 10 000/day |

`etsy:daily` must survive process restarts to be meaningful, so its counter is
persisted in `runs.db` — the one place the run store does real work beyond
history. `plan --all` reports what fraction of the daily budget it consumed, which
is the PRD's risk 10 made visible rather than merely noted.

**Retries.** Exponential backoff with jitter on 429 and 5xx, honouring
`Retry-After`; no retry on other 4xx. `create_product` is the one non-idempotent
call: it is guarded by the lockfile's `printify_product_id` plus a pre-flight
lookup, so a retried create can never produce a duplicate product.

**Publish polling.** Backoff 2s to 60s against a ~10 minute ceiling. On timeout the
lockfile records the product as locked, which is what `unlock` later acts on.

**Etsy OAuth.** PKCE via a localhost callback on a fixed port with a `state`
check; access tokens refreshed automatically, rotation handled; tokens written to
`.auth/etsy-tokens.json` with `0600`.

---

## UI

FastAPI serves JSON under `/api`; React talks to it through a client generated by
`openapi-typescript` + `openapi-fetch`, regenerated in CI with a check that fails
if the committed client is stale. Dev runs Vite with `/api` proxied to uvicorn;
production mounts the built `dist/` with an SPA fallback.

```
GET  /api/status                          auth + shop identity
GET  /api/listings                        grouped: draft | published | dirty, with drift flags
GET  /api/listings/{name}
POST /api/runs                            {kind: plan|apply, listings: [...]} -> run_id
GET  /api/runs                            history, paginated
GET  /api/runs/{id}/events                SSE, resumable via Last-Event-ID

GET  /api/templates
POST /api/templates                       upload a set
GET  /api/templates/{name}/config
PUT  /api/templates/{name}/config         writes template.yaml
POST /api/templates/{name}/preview        returns PNG through the real renderer

GET  /api/setup/state
POST /api/setup/etsy/start                returns authorise URL
GET  /api/setup/etsy/callback
POST /api/setup/printify                  {token}
GET  /api/setup/etsy/sections
GET  /api/setup/etsy/return-policies
POST /api/setup/defaults                  writes shop.yaml
```

Screens: **Setup wizard** (shown whenever no shop is connected), **Dashboard**
(listings by state, drift indicators, run history, live progress), **Calibrator**
(below), **Runner** (plan/apply per listing or batch, streamed output).

### The calibrator's shape

Three columns — template rail, canvas, inspector. The rail replaces what was a
template dropdown: it sorts templates that are not finished above the ones that
are, and says what each is missing. That ordering is the screen's whole
argument, and a dropdown cannot make it.

`TemplateSummary.status` is **derived on every read**, never persisted. A
`calibrated:` flag in `template.yaml` would be product state no PRD decision
covers, and it could disagree with the config sitting beside it. Only
`multiple` has states beyond "has a config at all": `placements: []` is what an
upload writes, and a box can be positioned before anyone says which colour it
depicts.

The inspector names controls after what they do to a photograph rather than
after the render pass behind them — "Follow fabric wrinkles" over `displace`,
"Pick up garment shading" over `shade`, and preset names over blend modes. The
raw values stay reachable under an *Advanced* disclosure, because the pass
names are what the config, the goldens and every error message use.

**Not surfaced yet, and owed:** `colour_coverage` (`exact`/`subset`) and the
per-placement `artwork` override. Both change render output and both are
currently editable only by hand in `template.yaml`. They were left out to keep
the redesign's default view as clean as the wireframe intends, not because they
stopped mattering; the *Advanced* disclosure is where they belong when they
come back.

Run endpoints call the same `engine` service functions the CLI calls, passing an
event callback. There is no UI-only execution path.

---

## Run store

```sql
PRAGMA journal_mode = WAL;

CREATE TABLE runs (
  id TEXT PRIMARY KEY, kind TEXT, listing TEXT, status TEXT,
  started_at TEXT, finished_at TEXT,
  n_changes INT, n_drift INT, error TEXT
);
CREATE TABLE run_events (
  run_id TEXT, seq INT, ts TEXT, stage TEXT, level TEXT, message TEXT,
  PRIMARY KEY (run_id, seq)
);
CREATE TABLE quota (name TEXT PRIMARY KEY, window_start TEXT, used INT);
```

```python
with recorder.run(kind="apply", listing="take-a-hike") as r:
    execute(ctx, on_event=r.emit)
```

The SSE endpoint tails `run_events` on `seq > last_seen`, so a UI reconnect
resumes exactly where it left off, and a run started from the CLI streams into an
already-open dashboard.

---

## Phases

Strict PRD order. Each phase lands behind its own exit criteria; nothing moves on
until they pass.

### Phase 0 — foundations

Workspace discovery and path resolution; pydantic models for `shop.yaml`,
profiles, listings, exceptions; the `Money` type with explicit-currency
validation; slugification rules plus collision detection; catalog fetch, TTL cache
and name-to-id resolution; `Change` vocabulary; lockfile model and
`canonical_hash()`; `Stage` protocol; a `plan` skeleton that walks the stages and
prints an empty plan.

*Exit:* `plan` runs against a fixture workspace with no network beyond the catalog;
bare-number and wrong-currency prices are rejected with actionable errors; the
byte-identical-`applied` determinism test passes.

### Phase 1 — renderer, calibrator, `new`

Render passes, `RenderConfig`, derived maps and `_derived/` caching; the golden
harness at both levels; the render stage wired into plan/apply; the FastAPI +
React skeleton carrying **only** the calibrator; the `new` interactive picker.

*Exit:* a template can be uploaded, calibrated in the browser against the bundled
test design, and produce full-resolution mockups for every colour; goldens are
committed; `new` writes a profile and listing with no integer IDs typed by hand.

### Phase 2 — Printify

Client, models and fakes; variant resolution from colour slug × size; product
create/update; publish with sync flags; polling; `unlock`; the first cassette
contract tests.

*Exit:* a product is created against a test shop and gains `external.id`; a second
`apply` is a no-op; PRD risks 2, 3 and 6 are answered empirically and written up in
`docs/api-findings.md`. Risk 5's API-surface question is answered already (see
"Draft-vs-live cannot be set through the API", above) — what Phase 2 must still
confirm empirically is whether the shop's Printify-side draft setting persists
across every future publish, and record that in the same file.

### Phase 3 — Etsy

OAuth PKCE and `auth`; copy patch; full-replace media sync; renewal; the LIVE
banner and drift reporting on live listings.

> **File the Etsy app registration now, not at the start of this phase.** It is a
> form, not engineering work, and approval lead time is unknown — PRD risk 1. The
> phase order is unchanged; only the paperwork moves earlier.

*Exit:* a complete draft listing exists in Etsy with our copy, tags and media in
rank order; the live-edit check from the PRD passes.

### Phase 4 — AI generation

Prompt templates in `prompts/`; vision + brief generation; `generated.yaml` as
cache; hard validation (13 tags or fewer, 20 chars each or fewer, title 140 or
fewer, banned-word and trademark screen); alt text alongside the copy.

*Exit:* validation failures abort before any upload with the offending field named;
a re-run never rewrites reviewed copy without `--regenerate`.

### Phase 5 — full UI

Setup wizard, dashboard, run history, plan/apply runner, SSE progress — built
around the calibrator that already exists.

*Exit:* a fresh machine goes from nothing to a connected shop entirely through the
wizard; a CLI-triggered run appears live in an open dashboard.

### Phase 6 — batch and polish

Rate limiter wired everywhere including the persisted daily budget;
continue-on-error batch with an end summary; `status`; FX fetch with age
reporting; gross margin display; `catalog refresh`.

*Exit:* `plan --all` over a multi-listing workspace completes, reports its share of
the Etsy daily budget, and a single failing listing does not halt the batch.

---

## Testing

| Layer | What it covers |
|---|---|
| Unit | slugification, `Money` parsing, hashing canonicalisation, path resolution, limiter maths |
| Golden | per-pass renders on a grid target; end-to-end composites per template |
| Behaviour | fake clients driving idempotency, drift, resume-after-failure, publish polling, `unlock`, batch continue-on-error |
| Contract | cassette replay through the real httpx client — payload shape, auth headers, error decoding, retry behaviour |
| E2E (`-m e2e`) | skipped by default; env-gated at a throwaway shop; creates a draft, asserts the round trip, re-applies to prove the no-op, tears down. Also the cassette recorder |

The four PRD verification scenarios — idempotency, live-edit, render regression,
offline pipeline — each map to a named test, not to a manual habit.

---

## Risks carried forward

The PRD's ten stand. These are added by the decisions above:

1. **Six hand-written differs drift apart** (A2). Mitigated by the shared `Change`
   vocabulary and helpers, and by a test asserting every stage emits only known
   change types with workspace-relative paths.
2. **Node enters the build path** (A5). Mitigated by the conditional build hook and
   CI-built wheels; the fallback if it becomes painful is committing `dist/`.
3. **The generated TS client goes stale** (A5). Mitigated by a CI check that
   regenerates and fails on a diff.
4. **`runs.db` holds the Etsy daily quota** (A6), so deleting the cache silently
   resets the counter. Acceptable — over-counting is the safe direction — but
   worth remembering when debugging a 429.
5. **Renderer determinism across machines** (A7). The pinned-versions and
   explicit-flags rules only hold if enforced; a lint rule or review checklist for
   bare `cv2` calls is cheap insurance.
