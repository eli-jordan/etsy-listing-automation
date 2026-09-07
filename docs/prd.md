# PRD: Etsy Print-on-Demand Listing Automation (t-shirts)

## Context

Listing a print-on-demand t-shirt on Etsy is the same work every time, only the
artwork changes: render mockups in each shirt colour, recreate the product in
Printify (garment, print provider, colour×size matrix, per-size pricing), then
write SEO copy and upload media to Etsy. It is repetitive, error-prone at the
variant level, and slow enough to be the bottleneck on how many designs get
listed.

This tool makes that a command. Given a design file and a small amount of
config, it produces a **draft** Etsy listing backed by a correctly configured
Printify product — and keeps maintaining that listing after it goes live. It is
deterministic wherever it can be, and uses AI only where deterministic code
genuinely cannot help: SEO tags, description copy, and image alt text.
Re-running against unchanged inputs must make no remote changes.

**Scope for v1 is t-shirts only.** TeePublic and Instagram posting, present in
the original sketch, are out of scope; the architecture should not preclude them.

## Goals

- One command takes a design from file to reviewable Etsy draft.
- Idempotent: re-running changes nothing unless an input changed.
- Previewable: nothing touches a shop without showing the real diff first.
- Custom mockups, not Printify's stock ones — the main differentiator.
- Human review before anything goes public — the Etsy draft is the gate.
- **Keep working after publish** — price and copy changes on live listings are a
  routine operation, not an edge case.

## Non-goals (v1)

- Activating listings. The tool creates and maintains drafts; you publish by hand.
- Order or fulfilment management (Printify's native Etsy integration owns this).
- Full Etsy fee modelling — see the deferred note at the end.
- Occlusion masking in mockups (v2).
- Other garments, other marketplaces, social posting.

---

## Key API constraints

These drive most of the design, so they are stated up front.

- **Printify** `POST /v1/shops/{id}/products.json` takes `blueprint_id` (garment
  model), `print_provider_id`, `variants[]` (each variant id = one colour×size
  combination, with `price` in integer cents and `is_enabled`), and
  `print_areas[]` placing the design via normalised `x`, `y`, `scale`, `angle`
  on a named placeholder (`front` / `back`).
  Rate limits: 600 req/min global, 100/min catalog, **200 publishes/30 min**.
- **Printify → Etsy** `POST .../publish.json` takes a *selective sync* body of
  booleans: `{title, description, images, variants, tags, keyFeatures,
  shipping_template}`. For a natively-connected Etsy shop, **Printify itself
  creates the Etsy listing**. The product then gains `external: {id, handle}` —
  that `id` is the Etsy listing ID and is the only bridge between the systems.
- **Etsy v3** `updateListing` for title (≤140 chars), description, tags (≤13,
  ≤20 chars each), and `should_auto_renew`. **There is no update-image
  endpoint** — only delete plus `uploadListingImage` at a `rank`, so image
  idempotency must be hash-driven locally. Limits: 10 images and 1 video per
  listing, ~10 req/sec, 10k requests/day.
- **Etsy API access requires app registration and approval.** Not instant, and a
  hard dependency for the entire Etsy half of this tool.

---

## Architecture

```
design.png + listing.yaml
        │
        ├─► render      warp → displace → shade → export   (local, deterministic)
        │
        ├─► generate    vision + brief → title/desc/tags/alt  (AI, review-gated)
        │
        ├─► printify    create/update product, resolve variant IDs, set prices
        │
        ├─► publish     publish.json {variants:true, copy/images:false}
        │               poll product until external.id appears
        │
        └─► etsy        patch title/desc/tags/section/materials/renewal
                        replace all images in rank order
```

### Default workflow

The intended path is four steps, and `plan` works out the rest:

1. Drop a design into `designs/`.
2. `new <design>` to create the listing file; fill in colours, prices and brief.
3. `plan`, then `apply`.
4. Review the draft in Etsy and publish it there.

**`plan` decides which stages need to run** by checking whether each stage's
inputs have changed — so it will report that mockups need rendering or copy needs
generating, and `apply` does both as part of its run. `render` and `generate`
remain available as explicit commands for when you want to iterate on just one,
but you never have to remember to run them.

The division of ownership is deliberate: **Printify owns the commercial and
fulfilment layer** (variant matrix, inventory, prices as pushed to Etsy,
shipping profile, production partner declaration, order routing). **We own what
sells the listing** (mockups, copy, tags, media order, renewal policy). The
selective-sync booleans are what stop a later Printify republish clobbering our
copy and images.

---

## Directory layout

```
etsy-listings/
  shop.yaml                     # shop-wide
  .env                              # gitignored — Printify + Anthropic keys
  .auth/etsy-tokens.json            # gitignored — OAuth tokens
  .cache/                           # gitignored
    catalog/{blueprint}-{provider}.json
    providers.json                  # print provider name → id resolution
    fx.json                         # cached exchange rate + fetch timestamp
    renders/{listing-name}/         # rendered mockups
      black.png  blue-jean.png ...
  prompts/                          # editable AI prompt templates
    title.md  description.md  tags.md  alt-text.md
  profiles/
    comfort-colors-1717.yaml        # generated by `new`
  pricing-plans/
    launch-low.yaml                  # optional, shared starting-price tables
  designs/
    {design-name}.png
  mockup-templates/
    {template-name}/
      template.yaml                 # written by the calibrator
      blue-jean.png  black.png  ...
      _derived/                     # displacement + shading maps, generated
  common-media/
    comfort-colors-sizing-chart.png
    care-instructions.png
  listings/
    {listing-name}/
      listing.yaml
      generated.yaml                # AI output
      state.lock.json
```

**Rendered mockups live in the gitignored `.cache/renders/` directory**, keyed by
listing. They persist between runs so they are not constantly regenerated, but
they never enter version control — rendered PNGs across a growing catalogue would
bloat the repository for files that are fully derivable.

The lockfile carries two separate hashes: an **input** hash (design bytes +
template assets + resolved render config) decides whether to *re-render*, and an
**output** hash per file decides whether to *re-upload*. A cleared cache
re-renders; if a Pillow or OpenCV upgrade changes output bytes, the output hash
changes and the images re-upload, which is correct behaviour.

---

## Config

### `shop.yaml`
```yaml
etsy:
  shop_id: 12345678
  who_made: i_did
  when_made: made_to_order
  is_supply: false
  shop_section_id: 4455667
  return_policy_id: 1122334
  renewal: manual              # manual | auto — default manual
currency: NOK                  # the only currency prices may be expressed in
preferred_print_provider: Monster Digital
                               # by name, not id — preselected in `new` when
                               # it offers the chosen garment
```

Print providers are referred to **by name everywhere a human writes config**.
Names resolve to Printify's integer IDs via `.cache/providers.json`, populated
from the catalog. `plan` fails with the list of valid names if one can't be
resolved.

> **Currency asymmetry.** The Etsy shop lists and deposits in **NOK**, matching
> the bank account, which avoids Etsy's ~2.5% conversion fee on deposits.
> **Printify bills in USD**, so cost is USD while revenue is NOK and the two
> cannot be subtracted directly.
>
> The USD→NOK rate is **fetched live and cached** in `.cache/fx.json` with a
> TTL. Wherever a converted figure is displayed, the output states that a
> conversion occurred, the rate used, and when that rate was fetched. If the
> fetch fails, the cached rate is used and its age is shown prominently.
>
> Residual exposure worth remembering: the card used to pay Printify adds its own
> conversion spread on top of the mid-market rate.

### `profiles/comfort-colors-1717.yaml` — generated, not hand-written

A profile describes **the garment**: which blueprint, which printer, what print
geometry. Nothing commercial lives here. It is created by `new` (below) and
reused by every subsequent listing for that shirt.

```yaml
blueprint:                          # authoritative; id resolved from cache
  brand: Comfort Colors             # brand + model identify the blank
  model: "1717"
  title: Unisex Garment-Dyed T-shirt   # descriptive; not matched on
print_provider: Monster Digital     # authoritative; id resolved from cache
placeholder: front
print_area: { width: 4500, height: 5400 }   # px, from the catalog placeholders
sizes: [S, M, L, XL, XXL, XXXL]
```

**A blueprint is identified by brand and model, not by title.** This was a
bare `blueprint: Comfort Colors 1717` until the e2e layer asked Printify and
found no blueprint by that title — the catalog calls 706 *"Unisex Garment-Dyed
T-shirt"*, with the brand *"Comfort Colors®"* and the model *"1717"*. Two
things were wrong with a title:

- **Printify's titles are generic and shared.** "Unisex Garment-Dyed T-shirt"
  does not say which shirt; half a dozen brands sell one. Brand and model are
  what anyone buying blanks actually quotes, which is why `new`'s picker
  already columns them.
- **Titles are marketing copy and get rewritten.** A retitle silently breaks
  every profile that named one, and the failure surfaces much later.

`title` is still recorded, and `new` refreshes it, because a file saying only
`brand: Comfort Colors / model: "1717"` is harder to read than one that also
says what the garment is. It is **not** part of the match — a title that has
drifted is stale prose, not a broken profile.

Matching normalises: case, surrounding whitespace, and the ® / ™ signs
Printify puts in brand names. So a hand-written `brand: Comfort Colors`
resolves against the catalog's `Comfort Colors®` without anyone having to
type the symbol. If brand and model somehow match more than one blueprint,
that is an error naming the candidates rather than an arbitrary pick.

One print area, and the catalog offers several: Printify's placeholders hang
off each *variant* and differ by garment size (Comfort Colors 1717 / Monster
Digital sells `front` at 3461×3955, 3839×4387 and 4200×4800). `new` records
the **largest** and says so. The print area is a resolution target — art sized
for the 3XL panel still covers the S panel, and the reverse prints soft on the
sizes with the most shirt to cover.

Mockup templates are **not** listed here. Only fields Printify's product
creation actually needs live on the profile — `templates:` was tried and
dropped (PRD 29): a template is a purely local, Etsy-facing rendering asset
Printify never sees, so forcing it through a shared per-garment registry
didn't earn its keep the way `blueprint`/`sizes`/`print_area` do, and it got
in the way of two listings on the same garment wanting different mockups. A
listing's `media:` may reference any template that exists in
`mockup-templates/` directly.

### `pricing-plans/{name}.yaml` — optional, shared starting-price table

A pricing plan is a reusable per-size price table a listing can point at
instead of writing prices out itself — the mechanism behind the
launch-low-then-raise workflow: create a `launch-low` plan and a `premium`
plan once, then move a listing between them by changing one reference rather
than hand-editing every size again.

```yaml
profile: comfort-colors-1717        # which garment this plan was built for
prices:
  S: 299 NOK
  M: 299 NOK
  L: 299 NOK
  XL: 309 NOK
  XXL: 319 NOK
  XXXL: 329 NOK
price_overrides: {}                 # optional — same shape as the listing's own
```

No name/label field — the filename is the identity. `profile` is a plain
bare-name reference, unvalidated at load time (same as `listing.profile`);
it exists so `new`'s picker can tell you which plans were built for the
garment you're configuring. A listing references a plan by **workspace-relative
path**, the same mechanism `design:` uses — not a bare name against a fixed
directory the way `profile:`/`media[].template` are (#34), since a plan's
directory has no enforced meaning and nested layouts are allowed.

### `listings/{name}/listing.yaml`

Everything commercial and creative lives here. **Prices** now have two
layers: an optional `pricing_plan:` reference supplies the base table, and
the listing's own `prices:`/`price_overrides:` sit on top of it — either can
be a full listing's worth of pricing on its own (today's flat-table
behaviour, unchanged), or `prices:` can cover just the sizes that need to
differ from the plan. Resolution order is `price_overrides` >
`prices` > the referenced plan's own (override-then-flat) resolution — a
listing must set at least one of `pricing_plan` or `prices`.

```yaml
profile: comfort-colors-1717
design: ../../designs/take-a-hike.png
colors: [black, blue-jean, ivory, moss]
brief: >
  Retro 70s sunset mountain scene. Design text reads exactly
  "TAKE A HIKE". Audience: hikers, national-park visitors, outdoorsy gifts.
pricing_plan: ../../pricing-plans/launch-low.yaml
prices: {}                 # optional per-size overrides on top of the plan
price_overrides:           # optional — specialty colours can cost more
  ice-blue: { XXL: 379 NOK }
etsy:
  title: <generate>
  description: <generate>
  tags: <generate>
  materials: [cotton]
  renewal: manual          # overrides shop.yaml
media:
  - { template: flat-lay-01, colour: black }
  - { template: flat-lay-01, colour: blue-jean }
  - { template: flat-lay-01, colour: ivory }
  - ../../common-media/comfort-colors-sizing-chart.png
  - ../../common-media/care-instructions.png
```

**Every price carries its currency explicitly** — in a pricing plan just as
much as on the listing. Validation rejects any price whose currency differs
from `shop.yaml`, and any bare number — so a figure can never be silently
misread as the wrong currency, which matters when the revenue side is NOK and
Printify's cost side is USD.

**Media entries are either `mockup: <colour-slug>` or a path** to a shared asset.
The `mockup:` form is a logical reference the renderer resolves into
`.cache/renders/`, so the listing file never points at a cache path, and
validation can confirm the colour is one the listing actually offers.

`<generate>` is the sentinel from the original sketch, kept. `generate` writes
concrete text to `generated.yaml`; at plan time, resolved copy comes from
`generated.yaml` wherever `listing.yaml` says `<generate>`, and is taken
literally otherwise. A re-run never silently rewrites reviewed copy —
`--regenerate` is required.

### Colour naming — convention, not a mapping table

A `colour-matrix`-kind mockup filename must equal the **slugified Printify
colour name** (`"Blue Jean"` → `blue-jean.png`), and `listing.yaml` refers to
colours by that same slug. No mapping file to maintain. **`multiple`- and
`single`-kind templates use a fixed filename, `scene.png`, instead** — see
"Mockup templates: kinds, multi-artwork" below — since those kinds have no
per-colour photo to derive a name from.

Slugification rules must be defined precisely and treated as stable. A sparse,
**empty-by-default** `exceptions.yaml` handles colour names that don't slugify
cleanly (ampersands, slashes, parenthesised names) or that collide on one slug.
`new` reports any collisions it finds while building a profile.

---

## `new` — interactive garment picker

```
new take-a-hike [--category tshirt]
```

1. Fetches Printify's blueprint catalog and filters to the category (defaults to
   `tshirt`). *Note: the catalog endpoint returns `title`/`brand`/`model` without
   a category facet, so filtering is client-side keyword matching over those
   fields — verify during implementation whether a better facet exists.*
2. Interactive fuzzy-search picker for the garment.
3. Fetches print providers offering that blueprint. `preferred_print_provider`
   from `shop.yaml` is preselected when it appears in the list.
4. Reads the chosen combination's variants to populate `sizes` and `print_area`
   automatically from the placeholder dimensions.
5. Offers the calibrated mockup templates and reads the chosen one's kind — a
   `colour-matrix` template gets one `media` entry per colour (capped at
   Etsy's 10-image limit, since a provider can offer far more colours than
   that), `multiple` and `single` get exactly one entry and no colour (PRD
   28). `colors:` still carries every colour: it decides which variants sell,
   not which photos get rendered (PRD 31).
6. **Writes `profiles/{slug}.yaml` if absent; reuses it silently if present.**
7. **Requires a pricing plan.** Offers every discovered `pricing-plans/*.yaml`
   file, annotated for whether its size keys match this garment's `sizes`
   exactly, plus an always-available "create a new pricing plan" choice. That
   choice reads Printify's manufacturing cost and shipping cost for the
   chosen blueprint/provider (see #35/#36) and writes a starting table at a
   10% margin over cost — a generated file, not a final price, and its
   comment says so.
8. Writes `listings/take-a-hike/listing.yaml` referencing that profile and the
   chosen pricing plan, with `<generate>` sentinels in place.

This removes the only genuinely opaque step in the whole system — nothing is
created by hand in the Printify UI, and you never look up an integer ID yourself.

---

## Idempotency: three-way comparison

`plan` compares **three** states:

| State | Source | Meaning |
|---|---|---|
| **desired** | config files + rendered mockups | what you want |
| **last applied** | `state.lock.json` | what this tool last wrote |
| **live** | Printify + Etsy APIs | what is actually there now |

- `desired ≠ last applied` → a **change** you made locally.
- `live ≠ last applied` → **drift**, someone edited in the Printify or Etsy UI.
  Reported prominently, since applying over drift discards that edit.

`plan` **always fetches live state**, caching each remote object for the duration
of a single run. A large batch plan is therefore slow and consumes a meaningful
share of Etsy's 10k/day allowance — an accepted trade for accurate drift
detection by default.

### Plan output shows real changes, not hashes

Hashes decide *whether* something changed; the diff shows *what*. Plan renders
actual before/after text, per-size price deltas, and named image changes:

```
listings/take-a-hike  [LIVE — etsy listing 1234567890]

  + render    4 mockups (design changed)
  + generate  title, description, tags (brief changed)

  ~ etsy.title
      - Take A Hike Retro Mountain Shirt
      + Retro Take A Hike Shirt, 70s Mountain Sunset Tee, Hiking Gift
  ~ etsy.tags
      + retro hiking tee, national park shirt
      - mountain shirt
  ~ prices                                     (NOK)
      XL      359 → 379
      XXL     369 → 389
  ~ media
      + { template: flat-lay-01, colour: moss }      (rank 4)
      - { template: flat-lay-01, colour: ivory }
  ! drift  etsy.description was edited outside this tool
           applying will overwrite it

  2 to run, 4 to change, 1 drift warning
```

Where copy has not yet been generated, `plan` shows the stage as pending rather
than the text — the words don't exist until `apply` produces them.

The lockfile records remote IDs (Printify product id, Etsy listing id, Etsy image
ids), which is what prevents duplicate listings on re-run. Nothing volatile —
timestamps, model output, absolute paths — may enter a hash, or every run shows a
spurious diff.

### Editing published listings

Listings stay maintainable after they go live; this is a routine workflow, not an
edge case. `plan` marks any active listing with a **`LIVE`** banner and shows the
full diff, and `apply` then proceeds without needing a special flag.

- **Price changes** flow through Printify: update variant prices, then republish
  with `{variants: true}` so Etsy picks them up.
- **Copy, tags, materials, renewal and image changes** go straight to Etsy via
  `updateListing`, bypassing Printify entirely.

> **Verify early:** republishing with `variants: true` against an *active* Etsy
> listing must be confirmed not to disturb the listing's state or inventory. This
> is the single riskiest assumption in the post-publish workflow.

---

## Mockup rendering

An ordered pipeline of independently-optional passes:

```
warp (homography to quad) → displace → shade → [mask, v2] → export
```

- **Warp** — `cv2.getPerspectiveTransform` + `warpPerspective` onto the
  template's four-corner quad. A quad rather than `x/y/w/h` because it
  degenerates to a rectangle for straight-on shots but handles angled and draped
  photos, and cannot be retrofitted cheaply once templates are calibrated
  against a rectangle schema.
- **Displace** — `cv2.remap` against a height field derived from the blank
  mockup's **own luminance** (desaturate → gaussian blur → normalise levels).
  This is the standard Photoshop apparel workflow and is why plain flat PNG
  mockups are sufficient — no purchased displacement maps needed. **Implemented
  but off by default**, toggled and tuned per template in the calibrator's live
  preview, because over-strong displacement looks melted.
- **Shade** — the mockup's luminance blended over the design so the print picks
  up the garment's lighting and fold shadows. **On by default.** Needs a
  per-colour blend parameter: multiply crushes prints on dark garments, so
  soft-light or a mid-grey pivot is used for those.
- **Mask** — v2. Where a collar, sleeve seam or arm crosses the print area the
  design should be clipped. v1 targets templates where nothing overlaps the
  chest. Planned approach: auto-derive from garment segmentation, brush-correct
  in the calibrator.

Rendering is a pure function of `design × template × render config` — fully
deterministic and hashable.

### Rejected: AI-placed mockups

Using an image model to place the design onto the shirt was considered and
rejected. Image models re-synthesise rather than paste, so design text and fine
linework would not exactly match the printed garment — a refund-and-review
problem for typographic tees, not a cosmetic one. It also conflicts with Etsy
expecting photos to represent the actual item, and breaks determinism. **AI
belongs in template authoring (calibration), not in the render path.**

### Mockup templates: kinds, multiple templates, multi-artwork

A template is exactly one of three **kinds**, never a mix — full detail in
[docs/multi-placement-rendering.md](multi-placement-rendering.md):

- **`colour-matrix`** — one photo per colour, the design at the same position
  in every one. This is the default case above.
- **`multiple`** — several garments in one photo (a colour chart). Each
  garment is a *placement*: its own colour and position.
- **`single`** — one photo, one garment (a lifestyle shot, a folded product
  photo).

**Templates are not declared on the profile.** A mockup template lives purely
in `mockup-templates/{name}/`, and a listing's `media:` may reference any of
them directly — there is no per-garment registry to keep in sync, and two
listings sharing a garment are free to use entirely different templates.
(An earlier version of this design listed available templates on the
profile; dropped because Printify never sees a template, so it doesn't
belong alongside the fields — blueprint, print provider, sizes — that
actually are garment-level facts Printify's product creation needs.) Each
`media:` entry always names which template (and, for `colour-matrix` kind,
which colour) it is: `{ template: flat-lay-01, colour: black }`. There is no
bare-colour shorthand — addressing is always explicit, which is what lets a
listing pull together outputs from several templates into one ordered media
list, including interleaving a shared asset between two mockups.

**A design may need more than one artwork file** — dark ink for light
garments, light ink for dark ones. `listing.yaml`'s `design:` becomes a map
keyed by artwork tag (`on-light`/`on-dark`) when more than one file is
needed; a bare path stays valid shorthand for the common single-artwork case.
Which garment colour is which tone is a profile-level fact
(`colour_tone: { black: dark, ivory: light }`), classified once, by hand,
when `new` sets up the garment — not inferred from Printify, which does not
expose a colour hex value in this tool's catalog integration.

---

## The UI

A `ui` command serves a local web app. It is the home for anything that is
better seen than typed.

### First-run setup

If no shop is connected, the UI opens straight into a setup wizard rather than an
empty dashboard. It walks through connecting **Etsy** (OAuth PKCE via localhost
callback) and **Printify** (API token), obtaining Anthropic credentials, and then
generating `shop.yaml` — reading the shop id, available shop sections and
return policies back from the Etsy API so those are picked from a list rather
than typed. This is the same work the `auth` CLI command does, presented as a
guided flow.

### Dashboard (read-only)
- Connected shop identity and auth status.
- Every listing grouped by state: **draft**, **published**, and **dirty** —
  where the backing files have changed since the last apply.
- Drift indicators where live remote state diverges from the lockfile.
- History of `plan` and `apply` runs with status, and live progress for anything
  currently running.

### Template authoring
- **A template is a folder the user puts in the workspace; the calibrator does
  not create one.** An upload form was the original answer here, and it would
  have earned its place if the browser were the only way in. It is not: a
  template set is photographs, and whatever produced them already wrote them to
  disk. A form that asks for a name and then copies files from one directory
  into another is a second, worse file manager, and it puts a naming decision
  (PRD 7a, PRD 28) in front of the photos instead of beside them. The
  calibrator starts where the folder exists and the kind is unanswered.
- Define the design bounding box on the four-corner quad, with draggable handles.
- Filmstrip of all colour variants in the set.
- Sliders for displacement strength and shading blend mode/opacity.
- The Python backend re-runs the **real renderer** on each change and streams
  back the composite, so the preview is the actual output, not an approximation.
  It is served at two *sizes*, which is not the same as two renderers: the
  editing canvas gets a downscale, because a full-resolution render per frame
  of a drag is slower than the drag and nobody sees the frames it costs, and a
  separate Preview view renders at the photo's own size on demand. Both run the
  same pipeline over the same photo; only the pixel count differs.
- **Ships with a bundled test design** so a new template can be calibrated
  immediately, with nothing to prepare. A toggle switches to a grid/ruler
  target, which makes warp and displacement errors more obvious than artwork
  does. You can also upload your own test design at any point.
- Writes `template.yaml` and caches derived maps into `_derived/`.

Colour variants are **usually** the same photograph recoloured, so
`template.yaml` carries one default quad for the whole set — but this is not
guaranteed, so per-file overrides are supported for a subset of the colour
images. The filmstrip is how you spot which ones need their own geometry.

### Running plan and apply
Plan and apply can be triggered per listing or in batch, with output streamed
into the page. These paths reuse exactly the same code as the CLI and enforce the
same guard rails — the LIVE banner, drift warnings and validation gates all
apply identically, so there is only ever one set of rules regardless of route.

Calibration exists **only** inside this UI — there is no standalone `calibrate`
command.

---

## AI copy generation

`generate` sends the model **the design image plus the one-line `brief`** from
`listing.yaml`, along with profile context. Vision infers style and audience; the
brief carries the exact design text so stylised lettering can't be misread into a
title.

- Prompts live in `prompts/` as editable templates — SEO strategy evolves and
  should not require a code change.
- Output written to `generated.yaml`, which acts as the cache: once copy exists it
  is never silently rewritten, so re-runs stay idempotent. Edit it by hand freely;
  `--regenerate` is required to overwrite it.
- **Hard post-generation validation**, failing loudly: ≤13 tags, ≤20 chars per
  tag, title ≤140 chars, plus a banned-word and trademark screen. Etsy suspends
  shops for keyword stuffing and trademark hits, so this gate is a real control.
- Alt text is generated alongside the copy — an Etsy search signal, nearly free
  to produce at the same time.

> **Where the human review gate sits — changed from the earlier decision.**
> Originally copy was generated by a separate command and reviewed on disk before
> any push. Under the four-step workflow, `apply` generates *and* pushes in one
> run, so the review point moves to **the Etsy draft**: you read the finished
> listing in Etsy and publish it there. Nothing reaches the public without your
> eyes on it either way, and the automated validation still runs before upload.
> If you would rather keep a gate before anything touches Etsy, `apply` can halt
> after writing `generated.yaml` on first generation and require a second run.

---

## Etsy field ownership

We own: **title, description, tags, images, shop section, materials, per-image
alt text, and renewal policy.** Everything else stays as Printify left it.

Renewal defaults to **manual** in `shop.yaml` and is overridable per listing,
written to Etsy's `should_auto_renew`.

*Known wrinkle:* Etsy requires a title at creation, so Printify's first publish
sets some title and description regardless of the sync flags — the flags govern
subsequent syncs. There is a brief window where the draft carries Printify's
generic copy before we overwrite it. Harmless for drafts.

### Media sync

Explicit ordered media list per listing (mockups plus shared assets such as the
sizing chart). Because Etsy has no update-image endpoint, sync is **full
replace**: if the media manifest hash differs, delete all images and re-upload in
rank order. Always correct; churns image IDs and spends ~10 uploads to change one
photo, acceptable at this volume.

---

## CLI

| Command | Purpose |
|---|---|
| `new <design> [--category tshirt]` | Interactive garment/provider picker; writes profile (if absent) + listing |
| `ui` | Serve setup, dashboard, template authoring and plan/apply runner |
| `plan <listing\|--all>` | Three-way diff against live remote state; decides which stages need to run |
| `apply <listing\|--all>` | Execute every stage the plan identified, render and generate included |
| `render <listing\|--all>` | Force a re-render (normally handled by apply) |
| `generate <listing\|--all>` | Force copy generation (`--regenerate` to overwrite reviewed text) |
| `status [<listing>]` | Stage and remote state overview |
| `auth` | Guided setup: Etsy OAuth PKCE flow, then Anthropic credentials |
| `catalog refresh [<profile>]` | Force-refresh the cached Printify catalog |
| `unlock <listing>` | Clear a Printify product stuck in publishing state |

The Printify catalog is fetched **automatically with a TTL** — `catalog refresh`
is a manual override, not a step you have to remember. It exists because Printify
identifies each colour×size combination by an integer variant ID unique to a
(blueprint, provider) pair, and the catalog payload is large and rarely changes.

`unlock` exists because Printify locks a product while a publish is in flight; if
a publish fails or stalls, that lock can persist and block further edits.
`publishing_failed.json` clears it. **This behaviour is inferred from the API
surface and needs verifying** — see risks.

### Batch behaviour

Sequential, behind a shared rate limiter respecting Printify's 200-publishes/30min
and Etsy's ~10/sec caps. **Continue-on-error**: a failure is recorded and the
batch carries on, with a summary at the end. Resumable apply makes re-running just
the failures safe, and one bad design cannot halt fifty good ones.

---

## Failure handling

`publish.json` is asynchronous: the product locks in Printify, Printify pushes to
Etsy, and `external.id` appears on success.

- Poll for `external.id` with exponential backoff to a timeout.
- The lockfile records which stages completed, so re-running `apply` resumes from
  the failed stage rather than duplicating work.
- `unlock` clears a stuck product.
- The case this exists to guard: Printify product and Etsy listing created, but
  our Etsy patch failed — leaving a draft carrying Printify's generic copy.

## Validation (at `plan` time, before any remote write)

- Design file: pixel dimensions must meet ~300 DPI for the profile's print area;
  must be RGB with an alpha channel. **Rejected with an actionable error naming
  the required size — never auto-upscaled or converted.** Silent upscaling
  produces a blurry print discovered via customer complaint.
- Every requested colour slug resolves to a real variant in the catalog.
- Every requested colour has a matching mockup file.
- Every media entry resolves: `mockup:` references name a colour the listing
  offers, paths exist. ≤10 images total.
- Every price carries an explicit currency, and it matches `shop.yaml`. Bare
  numbers are rejected.
- Blueprint and print provider names resolve to catalog IDs; failure lists the
  valid names.
- Copy within Etsy limits; no unresolved `<generate>` sentinels.

## Auth and secrets

`auth` is a single guided command: it runs a localhost callback server and
completes Etsy's OAuth 2.0 PKCE flow in the browser (access 1h, refresh 90d,
auto-refreshed), then walks through obtaining and storing an Anthropic API key.
Tokens land in gitignored `.auth/`, keys in `.env`.

---

## Implementation phases

| Phase | Deliverable |
|---|---|
| 0 | Config schemas (pydantic), profile/listing resolution, catalog fetch + cache, slugification, validation, lockfile model, `plan` skeleton |
| 1 | Render pipeline + calibration UI + `new` picker — fully local, valuable standalone |
| 2 | Printify: variant resolution, product create/update, publish, polling |
| 3 | Etsy: OAuth, copy patch, media replace, renewal |
| 4 | AI generation + validation gate |
| 5 | `ui` first-run setup, dashboard and plan/apply runner |
| 6 | Batch, rate limiting, `status`, drift reporting, polish |

The calibration UI lands in phase 1 rather than with the rest of the web app,
because templates must be calibrated before rendering is useful at all. Phase 5
adds the dashboard and runner around it.

Phase 1 is deliberately early: it is the riskiest work and produces something
useful before any API credentials exist.

## Verification

- **Render regressions** — checked-in golden reference PNGs compared with a pixel
  tolerance.
- **API logic** — recorded HTTP fixtures for Printify and Etsy so the pipeline
  runs offline in tests.
- **End-to-end** — one documented manual run against a real throwaway draft.
  Neither Printify nor Etsy offers a sandbox, so this cannot be automated; Etsy
  drafts do not incur the $0.20 listing fee until activated, so it is cheap.
- **Idempotency check** — `apply` twice in a row; the second must be a no-op.
- **Live-edit check** — publish a draft manually, change a price, confirm `plan`
  shows the LIVE banner and the price delta, and that `apply` updates Etsy
  without disturbing the listing.

## Risks and things to verify early

1. **Etsy API approval** is a hard prerequisite with unknown lead time. Start it
   before writing phase 3.
2. **Do the selective-sync booleans behave as documented?** The entire
   architecture assumes `{title/description/images/tags: false}` stops Printify
   overwriting our work on republish. Verify against a test product first.
3. **Does republishing `{variants: true}` against an active listing disturb it?**
   The post-publish price-change workflow depends on this being safe.
4. **Does `updateListing` interact badly with Printify-managed variations?**
   Etsy writes against a listing carrying external inventory may affect
   variations.
5. **Printify shop settings control whether its publish creates a draft or an
   active listing.** Must be confirmed as draft during setup, or listings go live
   before review.
6. **Is `unlock` real?** The publishing-lock behaviour and
   `publishing_failed.json` as its remedy are inferred from the API surface, not
   observed. Confirm before relying on it.
7. **Blueprint category filtering** in `new` is client-side keyword matching over
   title/brand/model, because the catalog endpoint appears to expose no category
   facet. Check for a better mechanism.
8. **Slug collisions** between two Printify colour names — the exceptions file
   exists for this, and `new` should detect and report collisions.
9. **Render determinism across library versions** — because renders live in a
   cache rather than version control, a Pillow or OpenCV upgrade combined with a
   cleared cache will re-upload every image. Hashing inputs and outputs
   separately makes this correct rather than silent, but pin both libraries.
10. **Plan is now network-bound.** A 200-listing plan takes minutes and consumes a
    real share of Etsy's daily allowance. Watch this as the catalogue grows.
11. **The undocumented Printify per-variant-cost endpoint** (product-catalog-
    service, no auth, no official docs) may change shape or vanish without
    notice; `new`'s pricing-plan wizard must degrade to a blank price on any
    failure, never abort. Its `decoration_method` query parameter is
    currently hardcoded to `dtg` rather than read from the provider's
    offered methods — correct for the providers used so far, but a
    different provider will simply fail soft to a blank price rather than
    use the right method. Verify there's no better, documented source for
    either the cost data or the decoration method.

## Deferred: full margin model

v1 shows **gross margin only** — NOK price minus Printify variant cost and
shipping converted at the live FX rate, with the rate and its fetch time shown —
explicitly labelled as excluding Etsy fees. Recorded here so a future phase does
not have to rediscover the stack:

`new`'s pricing-plan wizard (#35/#36) is **not** this model — it computes a
one-off USD cost + 10% markup starting price at creation time from an
uncached live FX fetch, with no ongoing rate, no Etsy-fee accounting, and no
recomputation after the file is written. This section's cached, fee-aware
margin display remains unbuilt.

**Etsy** — listing fee ($0.20 per listing per 4 months and on each renewal);
transaction fee (6.5% of item price *plus* shipping charged); payment processing
(country-dependent — the **Norwegian** rate needs confirming from Etsy's current
fee schedule rather than assumed); Offsite Ads (15%, or 12% above $10k/yr, but
only on attributed orders — so true margin is a band, not a number); currency
conversion (~2.5% when listing currency ≠ deposit currency — **not applicable
here**, both are NOK); regulatory operating fee (levied in some countries;
whether Norway is among them needs checking, not assuming).
**FX** — USD→NOK on the Printify cost side, plus the card's conversion spread.

---

## Appendix: decision log

| # | Fork | Decision |
|---|---|---|
| 1 | Etsy listing creation | Printify creates via native integration, we patch via Etsy API. Only path where orders route to the printer. |
| 2 | Runtime | Python — strongest compositing toolkit, pydantic, Typer. |
| 3 | Idempotency | Lockfile + `plan`/`apply`, three-way comparison against live state. |
| 4 | AI lifecycle | `apply` generates and pushes in one run; `generated.yaml` caches the text so it is never silently rewritten. Review gate is the Etsy draft, not a file. |
| 5 | Render passes | Warp + displace + shade; shade on by default, displace off and tuned per template. |
| 6 | Placement config | Per-template `template.yaml`, per-listing override. |
| 6b | Calibrator | Browser UI with live preview through the real renderer. Lives only inside the `ui` app; no standalone command. Ships with a bundled test design. |
| 6c | Geometry | Four-corner quad (homography). |
| 6d | Per-colour geometry | Superseded by #28 — `colour-matrix` kind has no per-colour override at all; a colour needing different geometry is a separate `single`-kind template. |
| 6e | Occlusion masks | Deferred to v2. |
| 7a | Colour mapping | Convention: `colour-matrix`-kind mockup filename = slugified Printify colour name. Sparse exceptions file. `multiple`/`single` kind use a fixed `scene.png` instead (#28). |
| 7b | Variant IDs | Catalog cached with a TTL, fetched automatically; `catalog refresh` as override. |
| 8a | Config layering | Profile = garment definition (generated by `new`); listing = everything commercial and creative, including prices — now optionally sourced from a shared pricing plan (#33) as the base layer rather than written per listing every time. |
| 8b | Overrides | Anything overridable, every departure flagged in `plan`. |
| 9 | CLI | `plan`/`apply` primary; local-only stages standalone; no separate remote push verbs. |
| 10 | Pricing | Explicit table per listing, optional per-colour overrides, optional shared pricing-plan file (#33) as the base layer under both. Never set via Etsy API. |
| 10b | Margin | Gross only, labelled as excluding fees; live FX rate with rate and age always shown. |
| 11 | Etsy fields | Core + merchandising, plus renewal policy (default manual). |
| 12 | Media | Explicit per-listing list; full replace on change. |
| 13 | AI inputs | Vision + short brief; editable prompts; hard limit validation. |
| 14 | Auth | Single guided `auth` covering Etsy OAuth and Anthropic credentials. |
| 15 | Failures | Resumable staged apply; `unlock` for stuck products. |
| 16 | Batch | Sequential, rate-limited, continue-on-error. |
| 17 | Design validation | Strict, never auto-fix. |
| 18 | Testing | Golden files + recorded fixtures + manual E2E. |
| 19 | `new` | Interactive garment/provider picker from the Printify catalog; generates profile + listing. |
| 20 | UI scope | Read-only dashboard + template authoring + plan/apply runner. |
| 21 | Live listings | `plan` marks LIVE and shows the diff; `apply` proceeds without a special flag. |
| 22 | Mockup storage | Rendered mockups persist in gitignored `.cache/renders/` — not regenerated every run, not committed. |
| 23 | Provider references | Print providers referred to by name in all config; blueprints by a `{brand, model, title}` object, matched on brand + model. Both resolve to Printify IDs via a cached lookup. Revised after the e2e layer found that Printify has no blueprint titled "Comfort Colors 1717": titles there are generic ("Unisex Garment-Dyed T-shirt"), shared across brands, and rewritten over time, so a title is not an identifier. `title` stays on the object as readable context and is not matched. |
| 24 | Price units | Every price carries an explicit currency (`349 NOK`); bare numbers and mismatched currencies are rejected. |
| 25 | Media references | Superseded by #29 — always-explicit `{template, colour?}` references, no bare-colour shorthand. |
| 26 | First run | The `ui` opens a setup wizard when no shop is connected — Etsy and Printify auth, Anthropic credentials, and guided `shop.yaml` generation. |
| 27 | Stage orchestration | `plan` determines whether render and generate need to run from input hashes; `apply` runs them. Both remain available as explicit commands. |
| 28 | Template kinds | A template is exactly one of `colour-matrix` / `multiple` / `single`, never a mix — [docs/multi-placement-rendering.md](multi-placement-rendering.md). |
| 29 | Multiple templates per listing | No profile-level registry — a listing's `media:` may reference any template that exists in `mockup-templates/`, always naming it explicitly as `{template, colour?}`; no default, no shorthand. Superseded once from an earlier `profile.templates: list[str]` registry, dropped because a template is a purely local, Etsy-facing asset Printify never sees. |
| 30 | Multi-artwork | `listing.design:` polymorphic (bare path or a map keyed by artwork tag); `profile.colour_tone` classified by hand via `new`, not inferred from Printify. |
| 31 | What renders | Driven purely by `media` references, not by `listing.colors` membership — a listing's colours drive which Printify variants sell, not which photos render. |
| 32 | Frontend testing | Vitest + React Testing Library, v8 coverage provider, 80%-branch floor mirroring the Python gate, wired into `scripts/check.sh`. |
| 33 | Pricing plan | A separate, reusable `pricing-plans/{name}.yaml` file holding a per-size price table plus optional per-colour overrides (same shape as the listing's own) and a `profile:` back-reference. `Listing.resolved_price` precedence: `price_overrides` > `prices` > the plan's own (override-then-flat) resolution. Named "pricing plan", not "pricing profile", to avoid colliding with the existing garment `Profile` concept. |
| 34 | Pricing plan reference | A listing references a pricing plan by workspace-relative path (`pricing_plan: ../../pricing-plans/x.yaml`), the same mechanism as `design:` — not a bare name against a fixed root, unlike `profile:`/`media[].template` (#29). `pricing-plans/` is a conventional discovery root for `new`'s picker, not an enforced resolution root — nested layouts, and plans stored elsewhere, both work. Migrating `media[].template` to the same path-based scheme is explicitly out of scope: it would also touch the calibrator UI/API and render-cache key naming, a separate, larger piece of work. |
| 35 | Undocumented cost data | `new`'s "create a pricing plan" flow reads Printify's undocumented per-variant manufacturing-cost endpoint (`product-catalog-service`, no auth, no docs — verified working in this project against a live response) to seed a starting price, joined against the public `variants.json` catalog on variant id for colour/size names. Isolated in its own module outside the documented `catalog/` surface, fail-soft by construction: any failure degrades to a blank price for the affected size(s), never aborts `new`. `decoration_method` is hardcoded to `dtg` (risk item 11). Shipping cost, by contrast, comes from Printify's documented `shipping.json` endpoint and lives in the normal `catalog/` client. |
| 36 | Wizard-time FX | The starting-price computation ((manufacturing + shipping) × 1.10 margin) converts USD cost to the shop currency via a minimal, uncached, one-off live rate fetch — deliberately not the deferred full-margin-model FX cache (#10b); that remains unbuilt. Where colours offering the same size disagree on cost, the max is used and the disagreement is noted in the generated file's comment. |
