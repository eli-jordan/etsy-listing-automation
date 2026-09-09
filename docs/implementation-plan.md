# Implementation Plan: Etsy Listing Automation

Companion to [prd.md](prd.md). The PRD settles *what* the tool does and 48 product
forks; this document settles *how* it is built — module boundaries, core contracts,
and the order of work. Where the two disagree, the PRD wins and this file is wrong.

---

## Architecture decision log

Twenty-two forks, resolved. Numbered `A#` so they can be cited from code comments
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
| A14 | Artwork resolution | `listing.artwork[colour]` > template/placement override > `profile.colour_tone`-derived key > design map's sole key. Implemented once, in `engine/stages/placement.py::DesignPlacement.artwork_for`, and used by both stages that place a design — the render stage's mockup and the product stage's print file. It lived privately inside the render stage until Phase 2, when the product stage had to import it through the underscore; a mockup and a print file disagreeing about which ink a colour gets is a failure neither stage's own tests would catch, so the rule got its own module rather than a second implementation. The order itself is unchanged. PRD 30. |
| A15 | Render cache namespacing | `.cache/renders/{listing}/{template}/...`, not `.cache/renders/{listing}/{colour}.png` — namespaced by template, since a listing can reference more than one `colour-matrix`-kind template and a bare colour is no longer unique across them. |
| A16 | Pricing plan resolution | `Listing.pricing_plan` stays a bare ref string, resolved by the caller via `Workspace.resolve()`, exactly like `design:` — `Listing` itself never touches `Workspace` or does I/O. `resolved_price()` takes an already-loaded `PricingPlan` as an optional keyword argument rather than loading it itself. Keeps `Listing` as pure and workspace-ignorant as it is today; the cost is every future price-resolving call site must remember to load and pass the plan, same cost `design:` resolution already carries. PRD 34. |
| A17 | Undocumented endpoint isolation | Printify's per-variant cost endpoint lives in `newcmd/unofficial_variant_costs.py`, outside the documented `CatalogClient` surface, so nothing built on that protocol can accidentally depend on an unauthenticated, undocumented API. Parsing (`parse_variant_costs`) is a pure function separated from the network call, fail-soft by construction. PRD 35. |
| A18 | Wizard-time FX module placement | The one-off FX fetch lives in `newcmd/fx_rate.py`, not the package layout's reserved `fx/` (this doc's own deferred, cached full-margin module, PRD 10b) — avoids name collision with, and confusion against, that future work. PRD 36. |
| A19 | Calibrator test design | A **library**, not the fixed `BundledDesign` literal it replaces. The three bundled targets stay and keep their ids; the preview endpoint resolves an arbitrary id against those plus PNGs the user has uploaded into the workspace, and an unknown id is a 400 rather than a `KeyError`. The literal was right while the only designs were the ones shipped in `api/static/`, but calibration is judged by eye, and the grid target answers "is the warp right?" while saying nothing about how a real ink weight sits on a real garment. The set has to be open for the second question. Uploads land in the workspace (`test-designs/`, kept apart from `designs/`), never the repo. |
| A20 | Stage-produced remote state | `StageApplyResult` gains a `remote: dict[str, Any]`, merged into the lockfile's `remote` block the same way `outputs` already is, with each stage owning a documented key prefix (`printify_*`, `etsy_*`). Until Phase 2 no stage produced remote ids, so `apply` copied `lock.remote` through untouched and there was no channel at all — `printify_product` is the first stage that has to write one. A dict merged by the engine, rather than the stage mutating a lockfile it was handed, keeps the rule that a stage returns a value and the engine decides what becomes of it. |
| A21 | Phase 2 concurrency scope | Retry-with-backoff lands in Phase 2, because it is needed the moment anything writes; the token buckets and the persisted daily budget stay in Phase 6 as planned. A3's `plan` thread-pool fan-out also stays unbuilt: with one remote stage and a single live read per listing there is nothing to overlap, and a pool that fans out over one call is machinery pretending to be an optimisation. Recorded as a decision rather than left as an omission, so the next reader does not take the empty pool for an oversight. |
| A22 | One Printify package, two protocols | `catalog/` and `clients/printify/` are **one package**, `clients/printify/`, over one shared `Transport`. The authority split that justified two packages is real and is kept — but it is a property of the *protocols*, not of the directory: a caller holding `CatalogClient` cannot reach `create_product` because the method is not on its type. What the two packages actually duplicated was plumbing — a `TokenSource` alias, a lazy token resolve, a `401/403` branch, an auth error, a base URL, an `httpx.Client` — and the copies had already drifted: the catalog reader had **no retries at all**, so a 429 on `blueprints.json` failed a `new` run outright while the identical 429 on a write rode out its backoff (A21). One transport, two protocols, one auth error naming every scope the single token needs. |
| A23 | Etsy auth, split four ways | `oauth.py` is pure (verifier, challenge, authorise URL, state check, response parsing), `callback.py` serves exactly one loopback request, `tokens.py` owns `.auth/etsy-tokens.json` and every rotation, `transport.py` carries both headers. The split is not tidiness. Refresh tokens **rotate on every use**, which makes the file write part of the protocol rather than a cache: it must land — atomically, `os.replace` over a temp file — before the new access token is used, or a crash mid-rotation burns the only credential that can recover without a browser. A `TokenStore` behind a lazily-resolved token source (A22's rule) keeps `plan` buildable with no credentials; an in-process lock with a double-check stops A3's read fan-out rotating twice; and an `invalid_grant` re-reads the file once before it is believed, because the rotation that invalidated it may have come from a second process. |

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
    money.py            Money type — parsing, currency validation; PriceField (A16)
    pricing_plan.py     PricingPlan — reusable per-size price table (PRD 33)
    slug.py             slugification rules + exceptions file + collision detection
  prompts.py            which prompt backend can drive this terminal at all --
                        shared by `new` and `setup`, a package-root leaf like
                        terminal.py rather than a member of either
  newcmd/               the `new` picker: logic.py (pure) + interactive.py (terminal
                        sequencing)
    unofficial_variant_costs.py    undocumented per-variant cost fetch, fail-soft,
                        isolated from catalog/'s documented surface (A17, PRD 35)
    fx_rate.py          one-off uncached FX fetch for the pricing-plan wizard only
                        — not the reserved fx/ package below (A18, PRD 36)
  setupcmd/             `setup` (PRD 43): logic.py (pure — skeleton, shop.yaml
                        merge, .env editing) + interactive.py (sequencing, I/O)
  authcmd/              `auth` (PRD 14, 49): every credential, verified before
                        it is stored. logic.py (pure — PKCE, authorise URL,
                        token bookkeeping) + interactive.py (the four
                        credential questions, browser, callback). Shares
                        setupcmd.logic's .env and .gitignore writers rather
                        than keeping a second copy of either
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
    printify/           everything said to Printify, catalog and shop alike (A22)
      transport.py      token, retries, auth + error decoding -- the shared half
      protocol.py       CatalogClient (reads) and PrintifyClient (writes)
      models.py         reference data and shop state
      catalog.py        blueprints/providers/variants/shipping (PRD 35)
      products.py       shops, uploads, product CRUD
      cache.py          TTL disk cache -- catalog only, deliberately
      resolve.py        name to id, the only place a config name becomes an int
      fakes.py          in-memory implementations of both protocols
    etsy/               everything said to Etsy, over one transport (A23)
      oauth.py          PKCE, authorise URL, state check — pure, no I/O
      callback.py       the one-shot loopback server that catches the code
      tokens.py         TokenStore: .auth/etsy-tokens.json, expiry, rotation
      transport.py      both auth headers, retries, error decoding
      protocol.py       EtsyClient
      models.py         listing, image, shop, section, return policy
      fakes.py          in-memory implementation
    limiter.py          token buckets, incl. persisted daily budget
    retry.py            backoff policy
  ai/                   prompt loading, generation, hard validation
  fx/                   USD to NOK fetch + .cache/fx.json with TTL
  runs/                 SQLite recorder, schema, event types
  ui/
    api/                FastAPI app, routers, schemas, SSE
      templates.py      kind assignment, colour report, config, preview,
                        rail thumbnails
      designs.py        the test-design library — bundled targets plus the
                        user's own uploads (A19)
    frontend/           Vite project, dist/ shipped as package data
```

The workspace gains one directory for the calibrator: `test-designs/`, holding
uploaded preview targets. Deliberately not `designs/`, which is artwork that
ships — a calibration target is not a product (A19).

---

## Core contracts

### `Stage`

```python
class Stage(Protocol):
    name: str
    local: bool                      # True => no remote state, so no drift

    def desired(self, ctx: RunContext) -> Desired: ...
    def read_live(self, ctx: RunContext, listing, lock) -> Live | None: ...
    def plan(self, desired, applied: dict | None, live) -> StagePlan: ...
    def apply(self, ctx, plan, desired, live, lock) -> StageApplyResult: ...

STAGES = [Render(), Generate(), PrintifyProduct(),
          Publish(), EtsyCopy(), EtsyMedia()]
```

`plan`'s `applied` is the stage's **own subtree** of the lockfile, looked up by
`build_plan` through `Lockfile.applied_for(name)`. There used to be a
`last_applied(lock)` method for this, and every stage implemented it as
`lock.applied.get(self.name)` — the same lookup written out once per stage, on
a protocol wide enough to reach every *other* stage's state. It arrives as the
raw document, because that is the form it was written in; a stage wanting a
typed view parses one at the top of its own `plan()`, where the parse sits
beside the comparison it feeds.

A stage's `apply` returns a `StageApplyResult` carrying three dicts, each
merged into a different part of the next lockfile — by the **lockfile**, never
by the stage and no longer by `apply`'s loop: `applied` **replaces**
`lock.applied[stage.name]` (it is a whole document, so a field the stage has
stopped emitting must not survive), while `outputs` and `remote` **merge** by
key into their respective axes (A20) — ids handed back by an API, excluded
from every hash, each stage owning a documented key prefix. See `Lockfile.fold`
below.

| Stage | `desired` | `read_live` | `apply` |
|---|---|---|---|
| `render` | design/artwork bytes hashes + template assets + resolved `RenderConfig`(s) per referenced scene (A11–A14) | which rendered files still exist under `.cache/renders/` | render each scene actually referenced by `media` into `.cache/renders/{listing}/{template}/` (A15) |
| `generate` | brief + design hash + profile context + prompt template hashes | whether `generated.yaml` still exists | call the model, validate hard, write `generated.yaml` |
| `printify_product` | title + description (PRD 44), blueprint/provider ids, enabled variant matrix with prices, print areas | `GET products/{id}`, incl. `visible` (below); `None` without a request when the lockfile has no product id | create (after the PRD 48 duplicate walk) or update product |
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

### Draft-vs-live — PRD risk 5, and a correction

This section used to read *"Draft-vs-live cannot be set through the API"*, and
concluded that nothing this tool sends could affect whether a publish lands as a
draft. **The premise was wrong, and Phase 2's recon caught it**
([api-findings.md](api-findings.md)).

The reasoning was sound as far as the documentation went: Printify's API
Reference (`developers.printify.com/docs/`) documents `visible` ("Used for
publishing. Visibility in sales channel", defaults to `true`) and marks it
**read-only**; it is absent from the `publish.json` body, which takes only
`images`, `variants`, `title`, `description`, `tags`, `shipping_template`, and
absent from the create/update product bodies and the Shop resource. From that,
"Hide in Store" looked like a web-app-only action.

Measured against the live API, `visible` **is** writable — accepted on
`POST products.json`, accepted on `PUT`, and it reads back as sent. The
reference is wrong about it, which is a good reason to keep measuring rather
than reading.

What that does *not* establish is the thing risk 5 cares about: whether a
hidden product publishes to Etsy as a draft. That needs a connected Etsy shop
and belongs to Phase 3. So the shop's Etsy-connection setting
(`docs/setup.md` §1.2) remains the documented lever and must still be set by a
human before the first `apply` publishes — but `visible` is now a candidate
second lever rather than a closed door.

Meanwhile `visible` comes back on `GET products/{id}`, so
`printify_product.read_live()` reads it and the stage surfaces a warning if a
product it manages ever comes back `visible: true`. That tripwire stands, and
may yet become a fix.

**Still open, and only answerable once an Etsy shop is connected:** whether the
shop's draft setting is a persistent per-shop default that holds for every
future publish, or something that reverts and needs re-confirming. Carried in
[api-findings.md](api-findings.md)'s open questions.

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
    "printify_product": { "title": "...", "description": "...",
                          "blueprint_id": 6, "print_provider_id": 29,
                          "variants": [{"id": 17887, "price": 4990, "is_enabled": true}],
                          "print_areas": [] },
    "publish":  { "sync_flags": {"variants": true, "title": false, "images": false} },
    "etsy_copy":{ "title": "...", "description": "...", "tags": [], "materials": ["cotton"],
                  "shop_section_id": 4455667, "should_auto_renew": false },
    "etsy_media": { "manifest": [{"ref": "mockup:black", "hash": "sha256:..."}] }
  },

  "remote":  { "printify_product_id": "...",
               "printify_upload_ids": {"default": "..."},
               "etsy_listing_id": 1234567890,
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

**`Lockfile` owns the merge, not just the file.** `fold(stage, result)` returns
the next lockfile with that stage's result absorbed under the replace/merge
rules above; `applied_for(stage)` hands a stage its own subtree back; and
`stamped(tool_version, applied_at)` records what wrote it and when, once per
run rather than once per stage. Those four axes used to be public dicts that
`execute` copied and combined by hand, with the rules for doing so written
down one module away in `StageApplyResult`'s docstring — rules stated in one
place and implemented in another are rules that drift. `StageApplyResult`
moved next to `fold` for the same reason. `execute` now decides only *which*
stages run and in what order, which is the part that is genuinely its
business (A3).

### Runs

```python
def plan_listings(ctx, listings, stages, *, on_planned, on_failure) -> RunReport: ...
def apply_listings(ctx, listings, stages, *, on_planned, on_failure) -> RunReport: ...
```

`engine/run.py`, one level above `build_plan`/`execute`: a whole run over a set
of listings, owning each lockfile's lifecycle — read it, plan, execute, write
it back — and PRD 16's continue-on-error. A `UserFacingError` abandons that
listing and no other; anything else is a defect and propagates.

This lived in `cli/app.py` as a private helper taking a callback until it was
lifted here. None of it is presentation: the lockfile's path and lifecycle are
engine concerns, so are the tool version and clock stamped into it, and PRD 16
is a product rule that has to hold whichever entry point drives it — the CLI
only added the words. It is the same seam `Plan`/`format_plan` already draws,
one level up: `cli` formats the `RunReport`, Phase 5's UI will serialise it,
and neither re-derives what a run does. PRD 16 is now assertable against a
value instead of against terminal output.

The two sinks exist because a batch has two moments worth watching, and output
must interleave with the work rather than arriving after it. `on_planned` fires
the instant a listing's plan is ready — before `apply` executes it, which is
the only point at which the plan is known and none of its progress events have
been emitted. `on_failure` fires when a listing is abandoned. The returned
`RunReport` is the same information in one piece, for a caller that wants it
that way, and `RunReport.failed` is what the CLI turns into an exit code.

### Workspace

```python
class Workspace:
    root: Path                       # dir containing shop.yaml
    defaults: Defaults

    @classmethod
    def discover(cls, start: Path | None = None) -> Workspace: ...
    def resolve(self, ref: str, relative_to: Path) -> Path: ...   # never escapes root
    def cache(self, *parts: str) -> Path: ...

    def pricing_plan_files(self) -> list[Path]: ...   # recursive discovery under pricing-plans/
    def load_pricing_plan(self, path: Path) -> PricingPlan: ...   # attaches workspace currency
```

Discovery walks up from cwd for `shop.yaml`, honouring `--root` then
`ETSY_LISTINGS_ROOT` first. `resolve()` rejects paths that escape the root, which
also makes the UI's file-serving endpoints safe by construction.

`pricing_plan_files()`/`load_pricing_plan()` are `Workspace`'s only
pricing-plan-specific surface (A16) — everything else about a plan reference
goes through the same `resolve()` used for `design:`, since a plan is
addressed by path, not by name.

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
`Retry-After`; no retry on other 4xx.

**The HTTP method decides more than the status does.** A 429 is a refusal to
process — Printify rejected the request before touching it — so resending is
free whatever the verb. A 5xx or a dropped connection says the opposite: the
write may well have landed. So idempotent methods are retried on both, and
**POST only on 429**. Without that split, retrying a `create_product` that
timed out is itself the duplicate-product bug the guard below exists to
prevent.

The last response is returned rather than raised, so the caller's own error
decoding still sees the real `errors.reason` instead of a wrapper's summary.
`sleep` and the jitter source are injected, which is what lets the whole
policy be tested instantly and deterministically.

`create_product` is the one non-idempotent call: it is guarded by the
lockfile's `printify_product_id` plus a pre-flight walk of the shop's
products, matching on title and description (PRD 48).

That clause used to say "plus a pre-flight lookup", which assumed a key the
product API does not have. There is none: `POST products.json` has no
idempotency key and no conflict — an identical spec makes a second product —
and `GET products.json` accepts `title`, `search` and `sku` parameters while
ignoring all three. So the guard is a **walk**, not a query, matched
client-side, and it is affordable only because it runs on the create path
alone. PRD 44's requirement that title and description be concrete text is what
makes that match key exist at all.

**Publish polling.** Backoff 2s to 60s against a ~10 minute ceiling. On timeout the
lockfile records the product as locked, which is what `unlock` later acts on.

**Etsy OAuth.** PKCE (`S256`, which Etsy requires on every flow) via a
localhost callback on the fixed registered port, with a `state` check.
Authorise at `https://www.etsy.com/oauth/connect`, exchange and refresh at
`https://api.etsy.com/v3/public/oauth/token`; scopes and callback URL are PRD
50. Tokens are written to `.auth/etsy-tokens.json`, and the mode is set to
`0600` where the platform means it — on the Windows filesystem this is
developed against, that call sets a read-only bit and is not an access control.
The docs say which of the two the user is getting rather than repeating a POSIX
promise the file does not keep.

Refresh happens on demand: when a run is about to speak to Etsy and the access
token has under five minutes left, or once in response to a `401`. Nothing
refreshes in the background, and a purely local `plan` still needs no
credentials at all. The refresh token's 90-day life is the one clock a user can
lose without noticing, so `auth --check` reports the days remaining and any
command that refreshes warns under fourteen. Whether a refresh restarts those
90 days is undocumented, so the stored `refresh_expires_at` is optimistic and
an `invalid_grant` is the authoritative answer — surfaced as "run `auth`
again", never as a bare OAuth error code.

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
POST /api/templates/{name}/kind           writes the starting template.yaml
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
`multiple` has states beyond "has a config at all": `placements: []` is what
assigning the kind writes, and a box can be positioned before anyone says which
colour it depicts.

**Every box is edited on the photo, and only there.** A `multiple` chart had a
bounding-box panel beside the canvas listing its placements with corner fields,
reorder buttons and a colour field. Everything on it except the colour was
already a gesture on the canvas — select, add, duplicate, reorder, delete,
drag — so the panel was a second place to look and a second place to be wrong
about which box is which. The colour was the exception because it is the one
fact about a box the photograph cannot show; it is a caption under the box now,
clicked to edit, drawn under exactly the boxes whose outline is drawn.

A box moves as a whole by dragging its interior or by the arrow keys, and
deforms only by its corner handles. Placing a box is the commonest move there
is, and dragging four corners the same distance by eye is not a way to do it.
Both gestures belong to the canvas, so every kind has them.

Every kind can also hide its box chrome. What that means differs — a chart
hides the boxes you are *not* working on, a colour set and a single scene hide
everything — but the reason is the same in all three: the outline and its
handles sit on top of the very artwork being judged.

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

*Exit:* a folder of photos can be given a kind, calibrated in the browser
against the bundled test design, and produce full-resolution mockups for every
colour; goldens are committed; `new` writes a profile and listing with no integer IDs typed by hand.

### Phase 2 — Printify

`setup` (PRD 43), which is what puts `printify.shop_id` and a verified token in
a workspace before any of the rest can run. Then: client, models and fakes;
variant resolution from colour slug × size; product create/update; the
design-resolution, immutable-garment and concrete-copy validation gates
(PRD 37, 38, 44); the first cassette contract tests.

Three smaller pieces land with it because Phase 2 is the first phase that needs
them: `StageApplyResult.remote` (A20), since `printify_product` is the first
stage to produce an id worth keeping; retry-with-backoff (A21), since it is the
first stage that writes; and the duplicate-create walk (PRD 48).

**Recon landed first**, before any of it:
[api-findings.md](api-findings.md) and `tests/e2e/test_printify_product_e2e.py`
establish what the product endpoints actually require, and several answers are
not the obvious ones — `variants` merges rather than replaces, `print_areas`
coverage differs between create and update, the product returns the whole
blueprint matrix, `visible` is writable. Build against that file, not against
the API reference.

*Exit:* `setup` takes an empty directory to a workspace `new` runs in, with a
token it verified and a shop id it discovered; a product is created against a
test shop carrying exactly the intended variant matrix, prices and print area;
a second `apply` is a no-op; retiring a colour actually disables its variants;
and a garment change, an undersized design and an unresolved `<generate>` in
the copy are each refused at `plan` time with an actionable error.

**Publishing is not in this phase's exit criteria, because this account cannot
reach it.** With no Etsy shop connected, `publish.json` returns
`400 code 8254`, so `external.id`, the publish lock, the selective-sync flags
and `unlock` — PRD risks 2, 3, 5 and 6 — move to Phase 3, where the shop that
can answer them exists. Phase 2 builds the product; Phase 3 publishes it.

### Phase 3 — Etsy

OAuth PKCE and `auth`; **publish with sync flags, polling for `external.id`,
and `unlock`**, inherited from Phase 2 because they need the connected shop
this phase creates; copy patch; full-replace media sync; renewal; the LIVE
banner and drift reporting on live listings. Two commands move in this phase
before any stage does: `auth` grows from a stub to the credential command PRD
14 describes, and `setup` — whose Printify token capture moves out to it —
grows the Etsy id resolution that `findShops` and friends make possible without
a bearer token (PRD 49). Everything downstream then opens on a workspace that
already knows which shop it patches.

> **File the Etsy app registration now, not at the start of this phase.** It is a
> form, not engineering work, and approval lead time is unknown — PRD risk 1. The
> phase order is unchanged; only the paperwork moves earlier.

> **Settle shipping before writing any of this — PRD risk 13.** Printify
> publishes its USD shipping rates to Etsy as bare numerals, so an NOK shop
> receives `kr 4,49` where `$4.49` was meant. The requirement is that both free
> and paid shipping work, starting with paid, which means this tool owns a
> shipping profile on the Etsy side and sends `shipping_template: false`. That
> is a decision about where rates live and whether a shipping stage exists — it
> shapes the stage list, so it cannot be discovered halfway through. Prices need
> no such care: NOK passes through unconverted (PRD 39, 40), and risk 12 is
> closed.

*Exit:* a complete draft listing exists in Etsy with our copy, tags and media in
rank order; the live-edit check from the PRD passes; PRD risks 2, 3, 5, 6 and 13
are answered empirically, along with the one confirmation risk 12 still owes
(does `29900` arrive as `299,00`?), and written into
[api-findings.md](api-findings.md).

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
