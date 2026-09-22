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
  is what the preview stage shows. **Superseded, see the amendment below**: a
  colour row now also carries a dot, sampled off the real photo rather than
  invented, and the preview stage now overlays the listing's real artwork
  instead of showing the bare photo.
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
  set, and built to grow — more checks are expected later. Price-vs-cost is
  still out of scope, unchanged; section is addressed a different way (see
  the amendment below) — sourcing the Section field's *choices* from the live
  shop rather than adding a live check to this validation module, so a value
  picked from the dropdown is correct by construction and there is still
  nothing here to keep in sync with Etsy.

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
- **The Dashboard is no longer a stub.** Its counts are already carried by
  `GET /api/listings`, so the mockup's stat cards cost nothing beyond the
  markup the `.stat-*` CSS was already ported for. (One card per lifecycle
  state since the status amendment below — four, not two.)

The Details tab shows the selected garment profile's materials read-only. A
listing does not own composition, so it cannot override the shared garment
definition from the editor.

### Amendment: three deferrals that stopped being true

A manual pass after the first ship found three of this section's original
"deferred" calls resting on infrastructure that has since been built for
other reasons, not on the underlying question still being unanswered:

- **Colour swatches are no longer invented.** The original call rejected a
  hex dot because nothing in the domain model carried one. `render/swatch.py`'s
  `sample_swatch()` (median-pixel sampling off a mockup photo, used since
  Phase 1 to colour `apply`'s log lines) answers the same question without a
  new field: `GET /api/templates/{name}/swatch` samples the real garment
  photo inside its own saved bounding box. The Variants tab's colour rows
  carry a dot from it; the real-render preview panel (next point) is still
  what answers "does this suit the design", unchanged.
- **Section is a dropdown.** The original call needed a live `plan()` to
  validate a section name. It does not need one to *list* the shop's
  sections: `EtsyShopClient.shop_sections` (`clients/etsy/shops.py`) was
  already unscoped for `setup`'s own use, so `GET /api/etsy/sections` costs
  no OAuth sign-in, only the workspace's app key pair -- and is empty (not an
  error) for a workspace short of either, falling back to the original text
  field.
- **Pricing plan is selectable, and a resolved price is editable.**
  `GET /api/pricing-plans` already existed for "+ New listing"; it grew a
  `ref` field so the Details tab can PATCH `pricing_plan:` with it directly.
  Editing a resolved price writes a per-size entry into `Listing.prices`,
  which `resolved_price()` already preferred over the plan -- no new
  resolution rule, just a control for one that existed.

Also built in the same pass, real bugs rather than deferred decisions:
`thumbnails.py` was flattening a transparent PNG onto opaque black (`RGB`
instead of `RGBA`) in every list/hover-card thumbnail, and the Variants/
Listing-Images preview panes drew a bare, thumbnail-capped mockup photo
instead of a full-resolution render with the listing's actual artwork on
it -- the calibrator's compositor already existed
(`render_scene`/`imagecache.py`), it just could not resolve a design outside
its own test-design library; `GET /api/templates/{name}/design-preview`
resolves a real `designs/*.png` through `Workspace.design_file` instead.

### Amendment: the status field, and four things the first pass got wrong

A second manual pass found one decision that was too coarse and four plain
bugs. The decision first, since the rest of the UI hangs off it.

**`draft`/`published` became `draft`/`deployed`/`live`/`dirty`** (PRD,
"Dashboard"). `published` was doing two jobs: "this tool has applied it" and
"a buyer can see it". Those are different pieces of news — the pipeline never
activates a listing (non-goal 1), so an applied listing waits at Etsy as a
draft until a person presses publish, and reporting that wait as *published*
said the opposite of what was true. The rule is
`engine/status.py`'s, not the API layer's, for the reason the
"only `engine` computes a diff" invariant gives: Phase 6's `status` command
answers the same question, and the two must not drift.

Two facts feed it, and the interesting part is where each comes from.

- **Applied, and edited since.** `stages_completed` on the lockfile records
  the apply. "Edited since" is the *mtime* of `listing.yaml` against the
  lockfile's — not a re-derived diff. The rule the product states is literally
  "edited since the last apply", and a write is what an edit is; the
  alternative is rebuilding every stage's desired document, half of which
  (`etsy_media`'s image ids) is not knowable without the network, to paint a
  badge. The cost is that an edit reverted before the next apply still reads
  as an edit until one runs.
- **Live on Etsy.** Nothing local can answer this, because nothing this tool
  does causes it. `EtsyListingClient.listing_states` (new —
  `getListingsByListingIds`, unscoped, 100 ids a request) answers for the
  whole table in one round trip, and `ui/api/etsystate.py` memoises the answer
  for 30 seconds — `GET /api/listings/{name}` is also what every autosave
  PATCH returns, so without the memo a keystroke burst in the editor would be
  a round trip apiece. A workspace with no Etsy credentials reports nothing
  live and still opens the page.

The four bugs:

- **The open-on menu pointed at index pages.** "Open on Printify" went to
  `/app/products` and "Open on Etsy" to Shop Manager's listing list — a menu
  that lands you on "all products" has told you nothing you did not know, and
  both ids were already on the row. They are
  `printify.com/app/product-details/{id}` and
  `etsy.com/your/shops/me/listing-editor/edit/{id}` now. The Etsy one is the
  editor rather than the storefront URL because a listing the tool has just
  applied is still an Etsy-side draft, which the public URL 404s for; the
  editor works for every state, so the link is not conditional on one. The
  menu's own visibility moved off `status` and onto "is there an id", since a
  listing can carry a Printify product without an Etsy listing yet.
- **Switching a colour off re-enabled it.** `colors:` was PATCHed alone, and
  `config/listing.py` refuses a document whose `media[]`, `artwork{}` or
  `price_overrides{}` names a colour the listing no longer sells. A refused
  PATCH is answered with a **200** carrying `field_errors` and the listing
  unchanged (which is what lets inline validation skip a status branch) — so
  the tab re-rendered the switch as on, with the reason in a field it does not
  display. `editor/colourSelection.ts` is now the one write path for
  `colors:`, and it drops what depended on a dropped colour in the same patch.
  That is a real edit rather than a workaround: a mockup of a colour the
  listing does not sell is an image Etsy would be sent for a variant that does
  not exist.
- **Both preview panes were postage stamps.** `.preview-stage img` capped
  every preview at 320px, which is a picture to *pick* rather than one to
  judge — and judging ink on cloth is the only reason either tab has a preview
  at all. They cap at 1024px now (the artwork's own resolution), bounded by
  the viewport so the reel and the colour list stay on screen. Clicking the
  Listing Images one opens the reel in the calibrator's `Lightbox`, arrow keys
  and `1:1` included, which is the same reason that component exists there:
  the fault worth catching is usually "this one colour is wrong", and finding
  it means comparing neighbours. A shared `common-media/` asset needed
  `GET /api/common-media/{name}/file` to have a full-size form at all.
- **"+ New listing" was a second form.** Three fields, then the editor —
  which meant two screens disagreeing about what creating a listing involves,
  and all three fields to be found again in the editor to change any of them.
  It is the editor now, opened on a draft the server built
  (`GET /api/listing-draft`, the same stub `POST /api/listings` writes, handed
  back unsaved) with the name inline in the page head. Naming it is the moment
  of creation: POST, then a PATCH carrying whatever was edited before the name
  existed, then the route replaces itself with the real editor. Until then
  there is no autosave, because there is nothing to autosave *to*.

Also in this pass: `etsy-listings ui` binds `0.0.0.0` rather than loopback, so
the workspace is reachable from a phone or another machine. `page_url` already
pointed the native window itself at `127.0.0.1`, so nothing about the desktop
path changes.

### Amendment: one editor, an empty draft, and renaming

The bullet above ("+ New listing was a second form") fixed one screen too few.
`NewListingPage` stopped being a *form* and became a second **route component**
over the shared `ListingEditorShell`, and being a second place broke it in
exactly the ways a second place does: it grew its own `update()`, which
mishandled the design ref and corrupted the design strip to "45 artworks"; its
own `create()`, which closed over a stale draft on blur and lost the click that
blurred the name field; its own loading state, which never resolved in a
workspace with no designs; and a single `.catch` in which a failed follow-up
PATCH reported "already a listing by that name" for a listing that had just
been created successfully.

Worse, it could not open at all in the workspace that needs it most. The draft
was server-built from a design *and* a garment profile (`GET
/api/listing-draft?design=&garment_profile=`), and the stub behind it refused
unless a compatible pricing plan already existed — so a fresh workspace's first
listing was unreachable from the UI that exists to create it.

**There is one route component now.** `/listings/new` and `/listings/:name`
both render `ListingEditorPage`; `useParams` answering `undefined` is what
selects the draft branch. The draft is **empty** — no design, no garment
profile, no colours, no pricing plan, nothing invented — and the editor is
where each of those gets chosen, the same way every other field already was.
Nothing is pre-filled, which supersedes the "colours default client-side to
every colour the chosen garment profile offers" note below; the spirit of it
survives one step later, as *picking* a garment profile enabling every colour
that profile classifies (replacing whatever was selected). That is a response
to an action rather than a starting state, and it is the only defensible
reading once the profile is no longer chosen before the editor opens.

**Incompleteness is the issues banner's job, not a 400's.** Every refusal
`_stub()` used to raise is a block issue instead: no design selected, no
garment profile selected, no pricing plan and no prices. `_stub()` is gone.
`newcmd.logic.build_listing_stub` stays untouched and un-deduplicated — the CLI
`new` picker pre-fills because it asked the questions; the editor has not.

**Naming it is what creates it**, as before, but the transition is one request
rather than a POST and a PATCH that could disagree. `POST /api/listings` takes
`{name, document}` and mirrors `PATCH` exactly: a document that fails
`Listing.model_validate` comes back as a **200** carrying `field_errors` with
nothing written, so the editor never branches on a status code to show inline
validation. The two things a *name* can be wrong about keep their status codes:
not a single path segment is a 400, already taken is a 409.

That 409 tests the **directory**, not `listing.yaml`. A `listings/<name>/`
holding a stale `state.lock.json` but no document would otherwise be adopted by
the new listing, which would inherit another listing's `etsy_listing_id`.

### The unsaved draft

The editor needs to render, and report issues on, a document that is not a
valid `Listing` yet. `Listing` stays strict — the point of it is that nothing
incomplete reaches disk — so the draft is a `Listing` with exactly one rule
waived: "set `pricing_plan` or `prices`". `Listing.draft()` and
`Listing.empty_draft()` pass a private context key; `Listing.load()`, `PATCH`
and `POST /api/listings` all go through plain `model_validate` and cannot.
`tests/unit/test_draft_context_is_private.py` keeps the key private by grep,
the technique `tests/unit/test_no_bare_cv2.py` already established.

Rejected: `model_construct`, which skips coercion as well as validation — so
`_coerce_design` would not run and the object's annotations would lie about
`design`. Rejected: a `DraftListing(Listing)` subclass, because pydantic v2
collects validators by attribute name across the MRO, so an override named
`_validate` *shadows* the parent's and silently loses the other five rules in
it. The context flag keeps every structural rule a half-filled document can
still be judged by — `media[].colour ⊆ colors`, `price_overrides`/`artwork`
keys ⊆ `colors`, the 140-character title, the currency check — which is
precisely what the editor's inline `field_errors` need before there is a file.

One consequence is worth stating plainly, because it is the price of keeping
the model strict: **a named listing is written the moment it has a price
source, and not before.** Every other field tolerates an empty value, so a
listing can have a name, a design, a garment profile and colours and still not
exist on disk. The page head's meta line says so in those words rather than a
bland "Not saved", and names the price source as the one thing standing in the
way when it is.

The banner also has to stay true while the listing is unnamed, which a
mount-time draft cannot do — it goes stale the moment a colour is toggled. So
`POST /api/listing-draft` describes an arbitrary candidate without writing it,
and the editor's debounce points there until there is a name. One hook owns all
three transports (draft, create, patch) because only the place that holds the
pending patch can know which is safe to send.

### Renaming a listing

A listing's identity is its directory name, and the page head's title is
inline-editable — double-click to rename, Enter or blur to commit, Escape to
revert. `POST /api/listings/{name}/rename` with `{new_name}`: POST rather than
PUT because the body is neither the listing nor its new representation and a
second call 404s, matching `POST /api/templates/{name}/kind`'s precedent for a
named mutation. 404 comes free from the `target()` dependency, 400 from
`workspace.listing_dir(new)` letting `_segment` refuse — calling the accessor
is enough, so the note below about exporting `_segment` is wrong and stays only
as the record of a thing that turned out not to be needed.

`Path.rename` on the **directory** moves `listing.yaml` and `state.lock.json`
in one operation, and `.cache/renders/<name>/` moves with it — the render cache
is keyed by listing name
(`Workspace.render_file`), so a rename that ignored it would orphan a tree
nothing ever deletes and force a full re-render. Traced rather than assumed,
that re-render is all it would cost: `input_hash` carries no listing name, so
the hash is unchanged, `read_live` simply reports every output missing, and the
re-rendered bytes are identical, so nothing re-uploads. `Workspace.renders_dir`
exists so the endpoint is not a second place that knows where renders live.

The lockfile's `outputs` keys still carry the old path and go stale. Nothing
reads them — `Lockfile.fold` merges them and `cli/render.py` reads
`Change.outputs`, a different thing — and "only the lockfile merges a lockfile"
puts a rewrite out of the API layer's reach, so they are left alone and become
true again after the next apply. Pruning them would need a `Lockfile` method
for one caller.

Nothing remote is keyed by the name: both remote titles come from `etsy.title`
and both ids from the lockfile, which moves with the directory. A rename
therefore costs no remote write and produces no drift.

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
- **Validation ownership**: the pure listing-validation module reuses
  `Listing`'s pydantic validators (attempt `Listing.model_validate` on the
  candidate document — structural rules for free, no duplication) and owns
  the local copy, description-source, design, and cross-reference checks
  (media vs. colours, template kind vs. colour, `variation_images` coverage,
  garment-profile existence). The stage adapter consumes those same checks;
  no UI-specific copy gate exists. It is deliberately **not** a `Stage` —
  stages diff local vs. remote; this only ever looks at local config, callable
  synchronously on every autosave with no network I/O.
- **Autosave / create split**: pydantic-**invalid** states (bad money, a
  `price_overrides` colour not in `colors:`, >20 media entries, a tag over 20
  chars) block the write and surface as inline field errors — the same shape
  the mockup already uses for Title/Section. Pydantic-**valid** but
  business-incomplete states (empty media, blank concrete deployment copy, an
  enabled colour missing from the swatch template) get written to disk and
  surface in the issues banner. This means `listing.yaml` is always a
  structurally valid `Listing` the moment it exists, even mid-edit.
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
- `etsy.title` over 140 chars; `etsy.tags` over 13 entries or any tag over 20
  chars
- neither `pricing_plan` nor `prices` set

**Business** (pydantic-valid but incomplete → issues banner, block or warn):

- concrete deployment copy (blank title or description lead, or an invalid
  common-copy source) — block
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
  (`draft`/`deployed`/`live`/`dirty`, derived — never persisted, same
  "derived on every read" principle already stated for
  `TemplateSummary.status`; the rule itself is
  `engine/status.py`'s, not this module's — see the status amendment below),
  issue counts by severity (for the row's badge, computed via the same
  validation module).
- `ListingDetail`: the full `Listing`, plus `status`, `issues: list[Issue]`,
  and `etsy_listing_id`/`printify_product_id` from `lock.remote` for the
  "Open on Etsy/Printify" menu — reuse `engine/stages/etsy_target.py`'s
  `ETSY_LISTING_ID_KEY` and `printify_product.py`'s `PRODUCT_ID_KEY` lookup
  rather than re-deriving.
- `PATCH` merges the given fields into the on-disk `Listing`, runs it through
  the validation module, writes only if pydantic-valid, and always returns
  the fresh `ListingDetail` (issues included) — the frontend never
  re-implements validation, it only renders what the server returns.
- `POST` (create) — **superseded by "one editor, an empty draft, and renaming"
  above.** The request is `{name, document}`, the server builds no stub and
  requires no pricing plan to exist, and a document it will not write comes
  back as a 200 with `field_errors`. What follows is the original design,
  kept for the record: the request carried `{name, design, garment_profile,
  colors}` (colours defaulting client-side to every colour the chosen garment
  profile offers), the server picked a compatible pricing plan via
  `newcmd/logic.py`'s `load_candidate_pricing_plans` +
  `build_pricing_plan_choices(plans, garment_profile_slug)` or refused
  creation outright when none existed, and it wrote a minimal valid `Listing`.
  The refusal is what made a fresh workspace's first listing uncreatable.
- The two draft endpoints, added by the same amendment:
  `GET /api/listing-draft` (no parameters) hands back a `ListingDetail` over
  an empty document, `name: ""`, `status: "draft"`, issues included; `POST
  /api/listing-draft` does the same for an arbitrary candidate, so the banner
  stays true while the listing is unnamed. Neither writes anything.
- `POST /api/listings/{name}/rename` takes `{new_name}`: 404 unknown listing,
  400 for a name that is not a single path segment, 409 for a name already in
  use, otherwise the directory and its render cache move together.
- Listing name validation for creation reuses `workspace.py`'s private
  `_segment()` rule (single safe path segment), since a listing's identity is
  its directory name and there's no separate slugification for it (unlike
  colours/garment profiles/pricing plans, which do get auto-slugified). This
  originally read "may need exporting, or a thin public wrapper" — it did not:
  calling the layout accessor (`workspace.listing_file`/`listing_dir`) and
  letting it refuse is both the check and the security boundary (A8).

### Supporting read-only endpoints

- `GET /api/garment-profiles` -> `[{name, sizes, colors, preview_template}]`
  from `workspace.garment_profile_names()` + `load_garment_profile` — feeds
  the Variants tab's garment dropdown (and, via `preview_template`, its
  colour-judgement preview). `preview_template` is null when the garment
  profile does not name one.
- `GET /api/pricing-plans?garment_profile=X` -> compatible plans, via the
  same `newcmd/logic.py` pure functions used by creation. The parameter is
  optional: a listing with no garment profile chosen yet has nothing to be
  compatible *with*, and asking with an empty one is more honest than asking
  with a name that cannot match and rendering every plan as "different
  garment".
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
- `GET /api/common-media` and `GET /api/common-media/{name}/thumbnail` — the
  bare-path half of `media:`, which the first pass left unaddressable: a
  listing could hold a shared asset (the fixture one does) but nothing in the
  UI could add one, and the reel drew it as raw text. The list hands back the
  **listing-relative** ref (`../../common-media/x.png`) as well as the display
  path, because that is the form `media:` stores — PRD 8a's convention, shared
  with `design:` — and leaving each caller to rebuild it is how two spellings
  of one rule drift apart. Backed by new `Workspace.common_media_files()` /
  `common_media_file()`, since only `workspace` knows a directory's layout,
  including how to list one; PNG-only and flat for the same reason
  `design_files()` is.

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
  DashboardPage.tsx        one stat card per lifecycle state + "+ New listing"
  ListingsPage.tsx         table + search + status filter pills, from the
                           mockup's listings section; backed by
                           GET /api/listings. A row carries its design
                           thumbnail, a hover card, and — once it has an id
                           to open — the open-on-Etsy/Printify menu
  ListingEditorPage.tsx    tabs container + issues banner + page head
                           (name/status/path/autosave indicator/open-menu).
                           Mounted at both /listings/new and /listings/:name
  components/
    EditableName.tsx       the page head's title: double-click to rename, or
                           open in edit mode when there is no name yet
  editor/
    DesignSelect.tsx        the design-select strip above the tabs: current
                           design + picker + "Find a design…" modal
    VariantsTab.tsx        garment dropdown, sizes, Dark/Light bulk buttons
                           over a colour list (swatch dot + name + light/dark
                           badge beside the switch) beside a large preview
                           stage showing the focused colour's real render
    ImagesTab.tsx           locator (mockup templates | common-media/
                           images) + a large preview pane (real renders,
                           opening the reel in the calibrator's Lightbox) +
                           reel (drag-reorder), plus the per-template Etsy
                           colour-swatch toggle
    colourSelection.ts      the one write path for `colors:` — and the three
                           colour-keyed fields that have to move with it
    listingDocument.ts      which `ListingDetail` fields are really
                           `listing.yaml` — the document `POST
                           /api/listing-draft` and `POST /api/listings` send
    DetailsTab.tsx          title/tags/description/section/materials, with
                           Etsy's own limits shown as counters; pricing display
api/
  listings.ts              wrapper functions, mirrors api/calibrator.ts
hooks/
  useAutosave.ts            debounced (~800ms after last change, also flushed
                           on blur/tab switch/unmount) save, returns latest
                           ListingDetail including server-computed issues.
                           Three transports — draft, create, patch — plus
                           rename, because only the holder of the pending
                           patch knows which one is safe to send
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
- New-listing flow — **superseded twice**, most recently by "one editor, an
  empty draft, and renaming" above. It was first a small inline step (name +
  design + garment profile) on the promise that "the editor page is *always*
  backed by a real, already-created listing, so it never has to juggle a 'not
  yet saved anywhere' state"; that promise is what cost a fresh workspace the
  ability to make its first listing. The editor does juggle that state now,
  and one hook holds it: `useAutosave` takes a name that may be `null` and
  switches transport on what exists — `POST /api/listing-draft` while
  unnamed, `POST /api/listings` once named, `PATCH /api/listings/{name}` once
  written — plus `rename()`, which drains the pending queue under the old name
  before the directory moves so an in-flight autosave has two fates and no
  third. `components/EditableName.tsx` is the head's title in both pages'
  worth of states.

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
