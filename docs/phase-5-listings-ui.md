# Phase 5: listings UI

The app shell, the listings list, and the listing editor — the part of
`docs/implementation-plan.md`'s `## UI` section's `/api/listings*` surface and
Dashboard/editor screens this covers. Subsidiary to [prd.md](prd.md) and
[implementation-plan.md](implementation-plan.md) the way
[phase-3-etsy.md](phase-3-etsy.md) is: detail those two point at rather than a
third authority. Where it disagrees with the PRD, the PRD wins.

Unlike `phase-3-etsy.md`, none of this is numbered PRD/A decisions yet — this
is a fresh plan for unbuilt work, not measurements behind an existing one. It
was produced against a UI design mockup (three screens: app shell, listing
editor, and the mockup-template calibrator wrapped in new chrome) after
checking the mockup's assumptions against the real domain model and resolving
the places they disagreed.

The mockup-template calibrator screen needs no new work beyond mounting the
existing `ui/frontend/src/App.tsx` under the new shell chrome — everything
below is the listings list and the listing editor.

---

## Decisions made against the mockup

The mockup is illustrative: its data (colours, templates, designs, validation
issues) is invented demo state, not wired to the real domain model. These
places where it didn't match what the system can actually do were resolved
before planning further:

- **Previews use real renders, not invented hex swatches.** Nothing in the
  domain model (`GarmentProfile.colors` is just `{name: "light"|"dark"}`) or
  the Printify client carries a colour's hex value, but the calibrator already
  has endpoints that render the real photo (`GET /api/templates/{name}/thumbnail`,
  `POST /api/templates/{name}/preview`). A colour row therefore carries no
  swatch dot — it is name + light/dark badge, and the *photo* of that colour
  is what the preview stage shows.
- **"+ New listing" is a simplified inline flow**, not a port of the `new` CLI
  wizard — pick a design, an *existing* garment profile, and colours; creating
  garment profiles/pricing plans from the UI is deferred to a later pass.
- **Autosave, not an explicit Save button** — the first autosave precedent in
  this codebase (the calibrator uses explicit Save/Reset).
- **Validation is local/config-only, not live-plan-based.** The mockup's two
  "shop-side" checks (price vs. Printify cost, section validity) need a real
  `plan()` against live Etsy/Printify data — out of scope here. In scope is a
  thorough pass over the *configuration's own* invariants (required fields,
  media/colour cross-references, template-kind mismatches, colour-swatch
  coverage), reusing what already exists (`Listing`'s own pydantic
  validators, `gates.py`'s pure checks) rather than inventing a parallel rule
  set, and built to grow — more checks are expected later.

This phase explicitly does **not** cover: a Runner/plan-apply trigger from the
UI, or garment-profile/pricing-plan creation from the UI.

### Amendment: what the conformance pass changed

The first implementation was reviewed screen-by-screen against the mockup
afterwards, and three of this section's original decisions did not survive
contact with the built UI. They are corrected above and below rather than
left standing with the code disagreeing with them:

- **A listing's `design:` is editable from the editor.** Deferring it to "+
  New listing" left the field write-once from the UI, while
  `check_design_resolution` still reports a design too small for the garment's
  print area — an issue banner pointing at a tab with no control to fix it.
  The mockup's design-select strip (thumbnail, name, path, `Change ▾`, recent
  designs, "Find a design…" modal) is in scope, sitting above the tab strip
  so Variants and Listing Images share it.
- **`etsy.variation_images` gets a control.** The validation module warns
  about the swatch template's colour coverage, so the UI warned about a field
  nothing in the UI could set or clear. The mockup's per-template "Use for
  Etsy colour swatches" toggle is in scope (PRD 56): it appears only on a
  `colour-matrix` template this listing's `media:` already references, and
  turning it on adds any missing colours — which is what makes the gate
  `EtsyMediaStage.desired()` enforces unreachable from the UI.
- **The Dashboard is no longer a stub.** Its two counts (published, drafts)
  are already carried by `GET /api/listings`, so the mockup's stat cards cost
  nothing beyond the markup the `.stat-*` CSS was already ported for.

The `Listing` fields the editor reaches are otherwise unchanged: `etsy.materials`
joins the Details tab because it is an ordinary `Listing` field the editor was
simply missing, not a new capability.

## Architecture decisions

- **Router**: introduce `react-router` (the only new frontend dependency this
  needs). Nothing today uses a router — `App.tsx` (the calibrator) is
  currently the whole page, mounted directly by `main.tsx`. The backend's SPA
  fallback in `src/etsy_listings/ui/api/app.py` already serves `index.html`
  for any non-`/api` path, so client-side routing works with zero backend
  change. Routes: `/` (Dashboard stub), `/listings`, `/listings/new`,
  `/listings/:name`, `/templates` (mounts the existing `<App/>` unmodified).
- **Design tokens**: extend `src/etsy_listings/ui/frontend/src/index.css`
  in place — it already defines the exact palette/fonts the mockup uses
  (`--color-bg`, `--color-accent`, Caprasimo/Figtree, spacing/radius/shadow
  scale, `.btn`/`.card`/`.tag`/`.seg`/`fieldset` primitives). Do not introduce
  a second token source; add a "Shell layer" section below the existing
  "Calibrator layer" marker for sidebar/nav/table-specific classes.
  The first pass read "already-shared primitives" too generously and skipped
  the mockup's **form-field** block, which the calibrator layer only partly
  covers: the calibrator's `.input` has no width (its fields sit in a fixed
  240px rail, so they never needed one) and nothing styles `textarea` at all.
  Ported into a form layer, those are `.field` spacing, `width: 100%` on
  `.input`/`textarea`/`select` inside a `.field`, the `textarea` rule itself,
  and `.details-tab { max-width: 640px }` — without which a 1115px card holds
  175px pills and a monospace UA textarea. A class named in JSX with no rule
  in `index.css` is the tell; there were 27 of them after the first pass.
- **State/data fetching**: no library exists or is needed — follow the
  calibrator's convention (local `useState`, hand-rolled `useEffect` fetches,
  wrapper functions in an `api/*.ts` module). A new `api/listings.ts` mirrors
  `api/calibrator.ts`'s shape exactly: typed wrapper functions over
  `openapi-fetch`, the only thing components import.
- **Validation ownership**: a new pure module reuses `Listing`'s own pydantic
  validators (attempt `Listing.model_validate` on the candidate document —
  structural rules for free, no duplication) plus the two existing pure gates
  in `engine/stages/gates.py` (`check_copy_is_concrete`,
  `check_design_resolution`) plus new pure cross-reference checks (media vs.
  colours, template kind vs. colour, `variation_images` coverage, garment
  profile existence). It is deliberately **not** a `Stage` — stages diff local
  vs. remote; this only ever looks at local config, callable synchronously on
  every autosave with no network I/O.
- **Autosave / create split**: pydantic-**invalid** states (bad money, a
  `price_overrides` colour not in `colors:`, >20 media entries, a tag over 20
  chars) block the write and surface as inline field errors — the same shape
  the mockup already uses for Title/Section. Pydantic-**valid** but
  business-incomplete states (empty media, `<generate>` title, an enabled
  colour missing from the swatch template) get written to disk and surface in
  the issues banner. This means `listing.yaml` is always a structurally valid
  `Listing` the moment it exists, even mid-edit.
- **No file locking / conflict handling** for autosave racing a concurrent CLI
  `apply` — last-write-wins is an accepted simplification given this is a
  single-operator tool (per the PRD's own framing).

## Backend

### New pure validation module — build and test this first

`src/etsy_listings/config/listing_validation.py` (or `engine/listing_health.py`
— name TBD during implementation, but it must not become a `Stage`). Input:
the candidate `Listing` fields, the resolved `GarmentProfile`, and a map of
`{template_name: TemplateSummary}` (from the calibrator's existing
`GET /api/templates`, so kind/colours are real, not re-derived). Output: a
list of `Issue{severity: block|warn, tab: variants|images|details, where: str,
message: str}` — the exact shape `ListingEditor.dc.html`'s `issues`/`raw`
array already expects, so the frontend's presentation code from the mockup
carries over almost unchanged; only the *source* of the list changes from a
hardcoded demo array to this module's real output.

Rules, each reusing or citing its real source — do not invent beyond this list
(the module should be structured as a list of independent check functions, not
a monolith, since more checks are expected later):

**Structural** (pydantic `Listing.model_validate` failure → blocks the write,
shown as inline field errors, not the issues list):

- Money parse failure on any price/`price_overrides` entry (`config/money.py`)
- Currency mismatch across prices (`Listing._validate`'s context currency check)
- `price_overrides`/`artwork` colour keys not a subset of `colors:`
- `media[].colour` not a subset of `colors:`
- `media` longer than `MAX_MEDIA_ENTRIES` (20)
- `etsy.title` over 140 chars when concrete; `etsy.tags` over 13 entries or
  any tag over 20 chars
- neither `pricing_plan` nor `prices` set

**Business** (pydantic-valid but incomplete → issues banner, block or warn):

- `check_copy_is_concrete` (title/description still `<generate>` or blank) —
  reused directly from `gates.py`, block
- `check_design_resolution` (design file missing/unreadable, no alpha
  channel, resolution <90% of the garment's print area) — reused directly
  from `gates.py`, block
- no media entries at all → block
- no colours enabled (`colors:` empty) → block
- `garment_profile` doesn't resolve to a real file under
  `workspace.garment_profile_names()` → block
- a `media[].template` entry whose real kind (from `TemplateSummary`) is
  `colour-matrix` but has no `colour` set, or is `multiple`/`single` but
  *has* a `colour` set → block (kind/colour mismatch)
- `etsy.variation_images` set but that template isn't referenced anywhere in
  `media:` → block (mirrors `EtsyMediaStage.desired()`'s real refusal)
- `etsy.variation_images` set but doesn't have a media entry for every colour
  in `colors:` → warn, with the uncovered colour names (this is exactly the
  mockup's `swatchWarning` computation — it was already local/config-only,
  just fed by demo data)
- no tags → warn
- a colour in `colors:` not present in the selected garment profile's
  `colors` dict → warn (best-effort local proxy; the authoritative check
  needs live Printify catalog matching, out of scope)

**Explicitly deferred** (not built): price-below-Printify-cost and
shop-section-validity — both need a live `plan()`. The issues banner should
not claim to check these; if useful, a static note can point at
`etsy-listings plan` for shop-side checks.

Tests: `tests/unit/test_listing_validation.py`, table-driven, no workspace
needed for the pure parts — mirrors the "pure passes" testing philosophy
already used for `render/`.

### New API endpoints — `src/etsy_listings/ui/api/listings.py`

Follows `templates.py`'s conventions exactly: a `target()` dependency for
existence-checking, reuse `config/listing.py`'s `Listing` model directly for
the read/write body (same rule as templates reusing `render/config.py` — the
wire shape *is* `listing.yaml`), new API-only schemas in `schemas.py` only
where the shape genuinely differs (`ListingSummary`, `ListingDetail`,
`Issue`), catch expected domain errors locally and raise `HTTPException`
rather than relying on a shared handler (per `app.py`'s own precedent, which
was a deliberate move *away* from a generic catch-all).

```
GET   /api/listings                 -> list[ListingSummary]
GET   /api/listings/{name}          -> ListingDetail
POST  /api/listings                 -> create (simplified flow, see below)
PATCH /api/listings/{name}          -> partial update; the autosave endpoint
```

- `ListingSummary`: name, garment profile name, colour count, status
  (`draft`/`published`, derived — never persisted, same "derived on every
  read" principle already stated for `TemplateSummary.status` —
  `published` iff `Lockfile.read(workspace.lock_file(name))` is not `None`
  and `.remote.get("etsy_listing_id")` is set), issue counts by severity (for
  the row's badge, computed via the same validation module).
- `ListingDetail`: the full `Listing`, plus `status`, `issues: list[Issue]`,
  and (when published) `etsy_listing_id`/`printify_product_id` from
  `lock.remote` for the "Open on Etsy/Printify" menu — reuse
  `engine/stages/etsy_target.py`'s `etsy_listing_id()` and
  `printify_product.py`'s `PRODUCT_ID_KEY` lookup rather than re-deriving.
- `PATCH` merges the given fields into the on-disk `Listing`, runs it through
  the validation module, writes only if pydantic-valid, and always returns
  the fresh `ListingDetail` (issues included) — the frontend never
  re-implements validation, it only renders what the server returns.
- `POST` (create): request carries `{name, design, garment_profile, colors}`
  (colours default client-side to every colour the chosen garment profile
  offers — a new listing starts with every colour the garment profile offers
  enabled). Server also requires a compatible pricing plan to exist
  (`Listing._validate` needs `pricing_plan` or `prices`) — reuse
  `newcmd/logic.py`'s `load_candidate_pricing_plans` +
  `build_pricing_plan_choices(plans, garment_profile_slug)` to pick the
  best/only compatible one automatically, or refuse creation with a clear
  message ("no pricing plan exists for this garment profile — create one
  with `etsy-listings new` or by hand") if none exists — matches the agreed
  scope of deferring plan creation from the UI. Writes a minimal valid
  `Listing` (empty `media: []`, `etsy` all defaults/`<generate>`) and returns
  its `ListingDetail`; the frontend navigates to `/listings/{name}`.
- Listing name validation for creation reuses `workspace.py`'s private
  `_segment()` rule (single safe path segment) — this may need exporting, or
  a thin public wrapper, since a listing's identity is its directory name
  and there's no separate slugification for it (unlike colours/garment
  profiles/pricing plans, which do get auto-slugified).

### Supporting read-only endpoints

- `GET /api/garment-profiles` -> `[{name, sizes, colors}]` from
  `workspace.garment_profile_names()` + `load_garment_profile` — feeds the
  Variants tab's garment dropdown and the new-listing picker.
- `GET /api/pricing-plans?garment_profile=X` -> compatible plans, via the
  same `newcmd/logic.py` pure functions used by creation.
- Real listing designs: `workspace.design_files()` under `designs/` — **not**
  the same thing as the existing `GET /api/designs`, which lists the
  calibrator's `test-designs/`. Name the new one distinctly, e.g.
  `GET /api/listing-designs`, to avoid colliding with `designs.py`'s router.
- Templates: reuse `GET /api/templates` (`templates.py`) as-is for the
  Images tab's locator — it already returns `{name, kind, colours,
  has_config, status}`, exactly what a "browse templates + colours" locator
  needs. Reuse `GET /api/templates/{name}/thumbnail` and
  `POST /api/templates/{name}/preview` for the real preview pane and reel
  thumbnails (per the "real renders" decision) rather than drawing SVG art.
- `GET /api/templates/{name}/thumbnail?colour=X` — **added by the amendment
  above.** Without it every colour of a `colour-matrix` template returns the
  same photo (`template_preview_photo` is deliberately "any one of them"), so
  `flat-lay-01 · black` and `flat-lay-01 · blue-jean` drew pixel-identical
  reel tiles. The colour resolves through `workspace.template_base_image`,
  which already owns PRD 7a's filename convention *and* its trailing-segment
  fallback — the endpoint must not glob for `{colour}.png` itself.
- `GET /api/listing-designs/{name}/thumbnail` — **added by the amendment
  above**, for the listings row thumbnail, its hover card, and the editor's
  design-select strip. Distinct from `designs.py`'s calibrator library for
  the same reason `GET /api/listing-designs` is: `designs/` is artwork that
  ships, `test-designs/` is calibration targets. `ListingSummary` grows a
  `design` field so a row can address it.

### Tests

`tests/behaviour/test_listings_api.py`, same pattern as
`tests/behaviour/test_calibrator_api.py`: `TestClient(create_app(workspace))`
against a writable copy of the fixture workspace, parametrized tables for
cross-cutting rules (bad name → 400 everywhere), docstrings on pinned status
codes.

## Frontend

`src/etsy_listings/ui/frontend/src/`:

```
shell/
  AppShell.tsx            sidebar nav (Dashboard/Listings/Mockup templates),
                           from the design mockup's app-shell markup
pages/
  DashboardPage.tsx        published/draft stat cards + "+ New listing"
  ListingsPage.tsx         table + search + status filter pills, from the
                           mockup's listings section; backed by
                           GET /api/listings. A row carries its design
                           thumbnail, a hover card, and (when published) the
                           open-on-Etsy/Printify menu
  ListingEditorPage.tsx    tabs container + issues banner + page head
                           (name/status/path/autosave indicator/open-menu)
  editor/
    DesignSelect.tsx        the design-select strip above the tabs: current
                           design + picker + "Find a design…" modal
    VariantsTab.tsx        garment dropdown, sizes, colour list (name +
                           light/dark badge, no invented hex swatch) beside
                           a preview stage showing the focused colour's photo
    ImagesTab.tsx           locator (templates) + preview pane (real
                           renders) + reel (drag-reorder), plus the
                           per-template Etsy colour-swatch toggle
    DetailsTab.tsx          title/tags/description/section/materials, with
                           Etsy's own limits shown as counters; pricing display
api/
  listings.ts              wrapper functions, mirrors api/calibrator.ts
hooks/
  useAutosave.ts            debounced (~800ms after last change, also flushed
                           on blur/tab switch/unmount) PATCH, returns latest
                           ListingDetail including server-computed issues
```

- `main.tsx` changes to mount a router with `AppShell` as the layout route,
  `<App/>` (the calibrator, unmodified) mounted at `/templates`.
- Reel drag-reorder: no DnD library exists anywhere in this codebase and
  `QuadEditor.tsx` sets the precedent of hand-rolling pointer/drag
  interaction rather than pulling in a dependency — hand-roll plain HTML5
  `dragStart`/`dragOver`/`drop` handlers rather than adding `@dnd-kit` or
  similar.
- Reusable pieces already in the codebase to lean on: `components/ViewTabs.tsx`
  for the Variants/Images/Details segmented control, `components/Lightbox.tsx`
  if a "view large" affordance is wanted on reel tiles.
- New-listing flow, concretely: "+ New listing" opens a small inline
  step (not the full editor) collecting name + design + garment profile,
  since colours default from the garment profile and pricing plan is
  resolved server-side. On submit, one `POST /api/listings`, then
  `navigate("/listings/{name}")` — the editor page itself is *always*
  backed by a real, already-created listing, so it never has to juggle a
  "not yet saved anywhere" state or a POST-then-PATCH transition.

### Tests

- Co-located `*.test.tsx` per component/page, mocking `api/listings.ts`
  module-level with `vi.spyOn` — same pattern as `App.test.tsx`.
- One `tests/browser/test_listings_browser.py` (pytest, `-m browser`,
  Playwright over the built SPA + real FastAPI app), asserting on the
  written `listing.yaml` on disk after a create → edit → autosave sequence —
  per `CLAUDE.md`, this layer's job is proving the React app, the FastAPI
  endpoints, and the real system work *together*, checked through observable
  effects, not internal state.
- 85%-branch coverage floor applies via the existing gates
  (`npm run test:coverage`, `scripts/check.sh`) — nothing new to configure.

## Suggested sequencing

1. Pure validation module + its unit tests (no UI dependency, fastest
   feedback, and the part most likely to need a second look at "did I miss
   an invariant").
2. `GET /api/listings` + `GET /api/listings/{name}` + `ListingsPage` against
   real (read-only) data.
3. `AppShell` + router, wrapping the existing calibrator unchanged at
   `/templates`.
4. `ListingEditorPage` rendering real data read-only (no autosave yet).
5. `PATCH` + `useAutosave` wired in.
6. `POST` create flow.
7. Reel drag-reorder + real preview/thumbnail wiring.
8. Browser end-to-end test.

## Verification

- `uv run pytest tests/unit/test_listing_validation.py` and
  `tests/behaviour/test_listings_api.py` for the backend.
- `npm run test` / `npm run test:coverage` in `ui/frontend/` for the new
  components.
- `npm run gen:api` after any endpoint change (`export_openapi.py` →
  `openapi-typescript`), per the README's existing manual step.
- Manual pass via `etsy-listings ui` against the fixture/dev workspace:
  create a listing, edit each tab, confirm autosave lands in `listing.yaml`
  (`cat` it between edits), confirm the issues banner matches hand-broken
  states (empty media, GENERATE title, a colour missing from the swatch
  template), confirm the calibrator still works unchanged at `/templates`.
- `uv run pytest -m browser` once the new browser test exists.
