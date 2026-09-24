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
- Human review before anything goes public — seller selection reviews AI
  suggestions before deployment, and the Etsy draft remains the final public
  publishing gate.
- **Keep working after publish** — price and copy changes on live listings are a
  routine operation, not an edge case.

## Non-goals (v1)

- Activating listings. The tool creates and maintains drafts; you publish by
  hand. **Amended (#64):** pause and resume of something a human already
  published is plan/apply (`state=inactive` / `state=active`). A `draft` is
  still never activated.
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
  idempotency must be hash-driven locally. Limits: 20 images and 2 videos per
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
inputs have changed — so it will report mockups that need rendering, and `apply`
does that work as part of its run. `render` remains available as an explicit
command for iteration, but you never have to remember to run it.

AI Mode is deliberately outside this staged deploy flow. In a saved listing's
Details tab, it asks a ready local coding-agent CLI for a temporary SEO proposal;
the seller chooses any useful title, tags, or description lead, and those normal
editor edits subsequently appear in `plan` like any other copy change.

Attaching a design in the editor starts that work early rather than waiting for
the seller to reach the Details tab: the brief is drafted from the artwork, and
the SEO proposal it unblocks is requested straight after, so Details is usually
already showing suggestions by the time the seller opens it (#68).

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
  .env                              # gitignored — Printify and Etsy app key
  .auth/etsy-tokens.json            # gitignored — OAuth tokens
  .cache/                           # gitignored
    catalog/{blueprint}-{provider}.json
    providers.json                  # print provider name → id resolution
    fx.json                         # cached exchange rate + fetch timestamp
    renders/{listing-name}/         # rendered mockups
      black.png  blue-jean.png ...
  prompts/                          # editable AI instructions
    seo.md                           # seeded only when absent
    brief.md                         # ditto — the design-brief drafting prompt
  garment-profiles/
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
  common-copy/                        # reusable description bodies
    comfort-colors.md                 # title/targets front matter + body
  listings/
    {listing-name}/
      listing.yaml
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
printify:
  shop_name: My new store      # what the shop is called in Printify
  shop_id: 28819281            # resolved from the name by `setup`
  preferred_print_provider: Monster Digital
                               # by name, not id — preselected in `new` when
                               # it offers the chosen garment
etsy:
  shop_name: TakeAHikeTees     # the shop's name on Etsy
  shop_id: 12345678            # resolved from the name by `setup`
  currency: NOK                # read from the Etsy shop; the only currency
                               # prices may be expressed in
  listing_defaults:            # everything a listing inherits (#52-#59)
    who_made: someone_else     # another company printed it — and Etsy then
                               # requires a production partner (#52)
    when_made: made_to_order
    is_supply: false
    renewal: manual            # manual | auto — default manual
    shipping_profile: NOK standard tee     # by title (#54)
    production_partner: The Print Provider # optional — omit when the shop
                                           # has exactly one (#52)
    return_policy:             # by its terms, not its id (#59); optional
      accepts_returns: true    # when the shop has exactly one policy
      accepts_exchanges: true
      within_days: 30
```

`listing_defaults` is what a listing inherits and may override; everything
outside it identifies the shop. The line is worth drawing because the two fail
differently — a wrong `shop_id` means nothing works, while a wrong default
means every listing is quietly slightly wrong.

Two settings are deliberately **absent**: there is no shop-wide shop section
and no shop-wide swatch template. Which part of the shop a listing sits in, and
which of its mockups become colour swatches, are facts about that listing
(#53, #56).

Every key sits under the service that owns it, and every shop is identified by
**name with its id beside it** (#51). The name is what a human recognises and
can check against a browser tab; the id is what the API needs; `setup` derives
the second from the first, so nobody transcribes an eight-digit number. The
file it writes carries a comment per field and points at `.env` for the
credentials, because it is the one file in a workspace people open by hand.

`printify.shop_id` is **written by `setup`, not looked up by hand** (#42).
Every product call is scoped to a shop — `/v1/shops/{shop}/products.json` — so
the tool cannot create anything without it, and Printify's own titles for shops
are whatever you typed when you made one ("My new store"). `GET /v1/shops.json`
returns exactly the shops the token can reach, so `setup` lists them, selects
the only one when there is only one, and asks otherwise. It is stored rather
than resolved on every run because a second shop appearing later must not
silently redirect where products are created.

**The Etsy shop is discovered from what is already connected**, not typed. A
Printify shop whose sales channel is Etsy carries the Etsy shop's own name, so
`findShops` turns the selection just made into an Etsy shop id with no further
question. Where the Printify shop is not connected — an "API" store, which is
what a workspace starts with — the id comes instead from the shop the stored
consent belongs to, since an Etsy account has exactly one. `setup` shows what
it found and takes an answer either way; what it will not do is ask someone to
find a number in a URL (#51).

**The currency comes from the Etsy shop too.** It is the shop's own
`currency_code`, read at `setup` time and written into the file as the default
for everything after — a value the shop already has, and one whose disagreement
with the file would be invisible until a price landed wrong (#24 is unchanged:
it remains the only currency a price may be written in).

Print providers are referred to **by name everywhere a human writes config**.
Names resolve to Printify's integer IDs via `.cache/providers.json`, populated
from the catalog. `plan` fails with the list of valid names if one can't be
resolved.

> **Currency asymmetry — real on the cost side, absent on the retail side.**
> The Etsy shop lists and deposits in **NOK**, matching the bank account, which
> avoids Etsy's ~2.5% conversion fee on deposits. **Printify bills in USD**, so
> cost is USD while revenue is NOK and the two cannot be subtracted directly.
>
> The retail side looks like the same problem and is not. Printify performs no
> conversion when it publishes a retail price: it sends the bare number, and the
> sales channel renders it in the shop's own currency. Printify documents this
> as the intended procedure rather than a defect — for a GBP shop, *"enter 24.99
> as the retail price in Printify and ignore the 'USD' label"*. So
> `variants[].price` is an integer in **minor units of the connected sales
> channel's currency**, and `29900` against an NOK Etsy shop is `kr 299,00`. The
> `USD` badge in Printify's web app is a fixed label, not a currency assertion
> (#39).
>
> Prices therefore travel as `Money` in NOK from `shop.yaml` to the wire and are
> serialised straight to minor units. **No exchange rate enters `apply`, and
> none enters a hash** (#40). The price is the one thing this asymmetry does not
> touch. Shipping is not so lucky — risk 13.
>
> The cost side still needs a rate. The USD→NOK rate is **fetched live and cached** in `.cache/fx.json` with a
> TTL. Wherever a converted figure is displayed, the output states that a
> conversion occurred, the rate used, and when that rate was fetched. If the
> fetch fails, the cached rate is used and its age is shown prominently.
>
> Residual exposure worth remembering: the card used to pay Printify adds its own
> conversion spread on top of the mid-market rate.

### `garment-profiles/comfort-colors-1717.yaml` — generated, not hand-written

A garment profile describes **the garment**: which blueprint, which printer, print
geometry and fibre materials. It is created by `new` (below) and
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
materials: [cotton]                 # Etsy-facing fibre materials, shared by this garment
preview_template: flat-lay-01   # colour-matrix; editor colour preview only
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
  every garment profile that named one, and the failure surfaces much later.

`title` is still recorded, and `new` refreshes it, because a file saying only
`brand: Comfort Colors / model: "1717"` is harder to read than one that also
says what the garment is. It is **not** part of the match — a title that has
drifted is stale prose, not a broken garment profile.

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

Listing mockups are **not** listed here. Only fields Printify's product
creation actually needs live on the garment profile — `templates:` was tried and
dropped (PRD 29): a template is a purely local, Etsy-facing rendering asset
Printify never sees, so forcing it through a shared per-garment registry
didn't earn its keep the way `blueprint`/`sizes`/`print_area` do, and it got
in the way of two listings on the same garment wanting different mockups. A
listing's `media:` may reference any template that exists in
`mockup-templates/` directly.

The one exception is `preview_template:` — a single `colour-matrix` template
the editor uses to judge colours on the Variants tab. It is not a default for
`media:`, not a render input, and Printify never sees it. A listing that never
mentions that template in `media:` still renders whatever `media:` does name
(PRD 31). Optional, so a garment profile written before the field existed
still loads; without it the Variants preview is empty until one is set. `new`
does not prompt for it — it is hand-edited the same way `colors:` is
classified.

### `pricing-plans/{name}.yaml` — optional, shared starting-price table

A pricing plan is a reusable per-size price table a listing can point at
instead of writing prices out itself — the mechanism behind the
launch-low-then-raise workflow: create a `launch-low` plan and a `premium`
plan once, then move a listing between them by changing one reference rather
than hand-editing every size again.

```yaml
garment_profile: comfort-colors-1717   # which garment this plan was built for
prices:
  S: 299 NOK
  M: 299 NOK
  L: 299 NOK
  XL: 309 NOK
  XXL: 319 NOK
  XXXL: 329 NOK
price_overrides: {}                 # optional — same shape as the listing's own
```

No name/label field — the filename is the identity. `garment_profile` is a plain
bare-name reference, unvalidated at load time (same as `listing.garment_profile`);
it exists so `new`'s picker can tell you which plans were built for the
garment you're configuring. A listing references a plan by **workspace-relative
path**, the same mechanism `design:` uses — not a bare name against a fixed
directory the way `garment_profile:`/`media[].template` are (#34), since a plan's
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
garment_profile: comfort-colors-1717
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
  title: ""
  tags: []
  description:
    lead: ""
    ref: common-copy/comfort-colors.md
  renewal: manual          # overrides shop.yaml
  section: Retro Tees      # by name; listing-only, no shop default (#53)
  shipping_profile: NOK heavy tee     # optional — overrides shop.yaml (#54)
  variation_images: flat-lay-01       # optional — the colour-matrix template
                                      # whose renders become swatches (#56)
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

`etsy.description` has a required `lead` and may carry exactly one sibling body
source: inline `text` or a `ref` beneath `common-copy/`. The final description
is composed once: it joins a non-empty lead and resolved body with exactly one
blank line, and every deployment reader consumes that same concrete string.
The lead may be empty while editing, but deployment is blocked until it is
non-empty. A body is optional, but `text` and `ref` are mutually exclusive.

AI Mode offers temporary choices only; it never writes a generated-copy file.
The listing file contains the seller's ordinary accepted values, whether typed
or selected from a proposal.

Legacy conversion is direct rather than a runtime compatibility layer:
`<generate>` becomes empty ordinary editable SEO values, while a scalar legacy
description becomes `description.text` unchanged with an empty `lead`. The
conversion never guesses where an opening paragraph ends. It enumerates its
targets before writing and is limited to tracked repository fixtures plus the
explicitly identified desktop `try-workspace`, never arbitrary workspaces.

### Colour naming — convention, not a mapping table

A `colour-matrix`-kind mockup filename must equal the **slugified Printify
colour name** (`"Blue Jean"` → `blue-jean.png`), and `listing.yaml` refers to
colours by that same slug. No mapping file to maintain. **`multiple`- and
`single`-kind templates use a fixed filename, `scene.png`, instead** — see
"Mockup templates: kinds, multi-artwork" below — since those kinds have no
per-colour photo to derive a name from.

When no file matches exactly, the lookup falls back to a **trailing-segment
match**: a filename whose hyphen-separated segments *end* with the colour
slug's own segments is accepted too (`vendor-pack-blue-jean.png` resolves
colour `blue-jean`). This exists for photo packs delivered with a shared,
uninformative prefix baked into every filename — renaming fifteen identical
files to strip the same six characters off each one is not a workflow worth
making anyone do by hand. It resolves only when exactly one file in the
directory ends with those segments; two files ending the same way is refused
rather than guessed at, since a wrong guess here ships the wrong photo. The
fallback is a lookup-time convenience only — it does not change what a
directory listing reports as its colour set (see `Workspace.template_colours`);
a filename that never exactly matches a slug still reads as its own name
there.

Slugification rules must be defined precisely and treated as stable. A sparse,
**empty-by-default** `exceptions.yaml` handles colour names that don't slugify
cleanly (ampersands, slashes, parenthesised names) or that collide on one slug.
`new` reports any collisions it finds while building a garment profile.

---

## `setup` — from nothing to a usable workspace

The step before everything else, and until now the one step the tool did not
own (#43). A workspace is a directory the user creates, containing a
`shop.yaml` they wrote by hand from an example in the docs, next to a `.env`
they populated from a page on printify.com. Two files, both easy to get subtly
wrong, both of which fail much later as an unhelpful `401` or a pydantic
validation dump.

`setup` runs in an empty (or absent) directory and produces a workspace that
`new` can immediately be run in:

1. **Creates the directory skeleton** — `designs/`, `listings/`, `garment-profiles/`,
   `pricing-plans/`, `mockup-templates/`, `common-media/`, `test-designs/`,
   `.cache/` — and the `.gitignore` that keeps `.cache/`, `.env` and `.auth/`
   out of any repository the user later puts around it.
2. **Asks which Printify shop**, from `GET /v1/shops.json` with the token
   `auth` stored. One shop is selected without asking; several are a picker;
   none is an error naming what to do on printify.com. Writes
   `printify.shop_id`. A *missing* token is not a question to ask here: it is a
   pointer back to `auth`, by name.
3. **Resolves the Etsy shop** with the app key pair, no OAuth involved:
   `findShops` by shop name, which carries no scope. Writes `etsy.shop_id`,
   discovered rather than typed for the same reason as #42 — an id copied out
   of a browser URL is a transcription error waiting to happen.

   It writes **two ids now, not four** (#53, #59, amending #49). The shop
   section moved to the listing, where it belongs, and the return policy is
   named by its terms — so neither is an id `setup` has to resolve, and a
   workspace no longer carries two numbers whose staleness is invisible until
   a `400`. What `setup` does instead is *report*: a shop with no production
   partner, no section, or only Printify's shipping profile is one where the
   next `plan` will block, and saying so at setup time beats saying it per
   listing later.
4. **Collects the commercial defaults** — the `listing_defaults` block:
   `who_made`, `when_made`, `is_supply`,
   currency, renewal policy, preferred print provider — and writes `shop.yaml`
   **last**, because it is the file that makes a directory a workspace: a run
   cancelled halfway leaves directories nothing downstream mistakes for one.

Re-running it against an existing workspace is safe: it reports what is already
there, offers to fill only what is missing, and never overwrites a value
without asking. **`setup` writes no credentials at all** — that is `auth`'s
whole job (#49) — and what it does write goes to the workspace, never to this
repository.

The `ui` first-run wizard (#26) covers the same ground in a browser and remains
Phase 5's work. `setup` is not a stopgap for it — a terminal-only path to a
working workspace is worth having on its own, and it is the one that exists
before there is a UI to serve.

## `new` — interactive garment picker

```
new [take-a-hike] [--category tshirt]
```

1. Picks the design. Omitting the argument is the normal way in: `new` is a
   wizard, and requiring one answer on the command line meant knowing the exact
   stem of a file just exported. `designs/*.png` is offered newest first — a
   design is made minutes before the listing that ships it — with the date in
   the row and a mark on any design that already has a listing, which `new`
   refuses to overwrite. Naming a design explicitly still works, and is the
   only way to start a listing for artwork that does not exist yet.
2. Fetches Printify's blueprint catalog and filters to the category (defaults to
   `tshirt`). *Note: the catalog endpoint returns `title`/`brand`/`model` without
   a category facet, so filtering is client-side keyword matching over those
   fields — verify during implementation whether a better facet exists.*
3. Interactive fuzzy-search picker for the garment.
4. Fetches print providers offering that blueprint. `preferred_print_provider`
   from `shop.yaml` is preselected when it appears in the list.
5. Reads the chosen combination's variants to populate `sizes` and `print_area`
   automatically from the placeholder dimensions.
6. Offers the calibrated mockup templates and reads the chosen one's kind — a
   `colour-matrix` template gets one `media` entry per colour (capped at
   Etsy's 20-image limit, since a provider can offer far more colours than
   that), `multiple` and `single` get exactly one entry and no colour (PRD
   28). `colors:` still carries every colour: it decides which variants sell,
   not which photos get rendered (PRD 31).
7. **Writes `garment-profiles/{slug}.yaml` if absent; reuses it silently if present.**
8. **Requires a pricing plan.** Offers every discovered `pricing-plans/*.yaml`
   file, annotated for whether its size keys match this garment's `sizes`
   exactly, plus an always-available "create a new pricing plan" choice. That
   choice reads Printify's manufacturing cost and shipping cost for the
   chosen blueprint/provider (see #35/#36) and writes a starting table at a
   10% margin over cost — a generated file, not a final price, and its
   comment says so.
9. Writes `listings/take-a-hike/listing.yaml` referencing that garment profile and the
   chosen pricing plan, with ordinary editable empty SEO fields in place.

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

The lockfile records remote IDs (Printify product id, Etsy listing id, Etsy image
ids), which is what prevents duplicate listings on re-run. Nothing volatile —
timestamps, model output, absolute paths — may enter a hash, or every run shows a
spurious diff.

### Editing published listings

Listings stay maintainable after they go live; this is a routine workflow, not an
edge case. `plan` marks any active listing with a **`LIVE`** banner and shows the
full diff, and `apply` then proceeds without needing a special flag.

**Two writers, and each field belongs to exactly one of them** (#41). Printify
creates the product and publishes it once, carrying only what it needs in order
to exist and to route an order to the printer. From that moment the split is:

- **The variant matrix — colour, size, price, SKU — belongs to Printify.** It
  is what fulfils an order, so Printify has to hold it. Changes go to Printify
  and republish with selective sync `{variants: true}` and **every other flag
  false**.
- **Everything the buyer reads belongs to us** — title, description, tags,
  materials, images, shop section, alt text, renewal — and is written straight
  to Etsy via `updateListing` and the image endpoints, never through Printify.

Neither writer touches the other's fields. That is what makes the two systems
composable rather than a sync war, and it is why the selective-sync booleans
matter so much: they are the enforcement mechanism, not a convenience.

> **Verify early:** republishing with `variants: true` against an *active* Etsy
> listing must be confirmed not to disturb the listing's state or inventory. This
> is the single riskiest assumption in the post-publish workflow. Risk 2 is its
> mirror image — if `{images: false}` is not honoured, every variant republish
> silently overwrites our rendered mockups with Printify's generated ones and the
> ownership split above collapses.

#### There is no draft of a live listing — settled, not open

Etsy has no staging concept. `updateListing`'s `state` parameter is
`enum(active, inactive)`: `draft` appears in the *read* enum
(`active, inactive, sold_out, draft, expired`) but cannot be set on an update.
`draft` is a birth-only state — `createDraftListing` produces one, setting it
`active` publishes it, and there is no route back. A published listing cannot be
copied to a reviewable draft that later replaces it, and edits to a live listing
take effect immediately and visibly.

So the review gate that exists before publish (#4 — the Etsy draft) genuinely
does not exist after it, and **#21 stands as the only in-place option**: `plan`
shows the diff, and the diff *is* the review.

One alternative does exist and is deliberately not chosen: set the listing
`inactive`, edit, set it `active` again. Etsy charges nothing for this as long
as the listing has not expired (deactivation does not pause the four-month
clock; an expired listing costs $0.20 to renew before it can be reactivated),
and the listing keeps its ID, favourites and reviews. What it costs is
visibility — the item is unbuyable and out of search for the duration, on a
marketplace whose ranking rewards consistency. Not worth it to hide a tag edit.
Worth reconsidering only if some future change is both large and slow to apply.

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

**Templates are not declared on the garment profile.** A mockup template lives purely
in `mockup-templates/{name}/`, and a listing's `media:` may reference any of
them directly — there is no per-garment registry to keep in sync, and two
listings sharing a garment are free to use entirely different templates.
(An earlier version of this design listed available templates on the
garment profile; dropped because Printify never sees a template, so it doesn't
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
Which garment colour is which tone is a garment-profile-level fact
(`colors: { black: dark, ivory: light }`), classified once, by hand-editing
the generated garment profile — `new` does not ask, and it is not inferred
from Printify, which does not expose a colour hex value in this tool's
catalog integration.

---

## The UI

A `ui` command serves a local web app. It is the home for anything that is
better seen than typed.

### First-run setup

If no shop is connected, the UI opens straight into a setup wizard rather than an
empty dashboard. It walks through connecting **Etsy** (OAuth PKCE via localhost
callback) and **Printify** (API token), then generating `shop.yaml` — reading the shop id, available shop sections and
return policies back from the Etsy API so those are picked from a list rather
than typed. This is the same work the `auth` CLI command does, presented as a
guided flow.

### Dashboard (read-only)
- Connected shop identity and auth status.
- Every listing grouped by state: **draft**, **deployed**, **live** and
  **dirty**, plus the retire/delete badges in
  [listing-lifecycle.md](listing-lifecycle.md) (#61). Two independent facts
  decide the original four, and neither is a state on its own: has the listing
  been applied (and edited since), and has a human published it on Etsy.

  | | never applied, or edited since | applied, unchanged since |
  |---|---|---|
  | **not on Etsy yet** | draft | deployed |
  | **published on Etsy** | dirty | live |

  ```
  draft --(apply)--> deployed --(publish on Etsy)--> live
  draft --(apply)--> deployed --(edit)--> draft --(apply)--> deployed
  live  --(edit)--> dirty --(apply)--> live
  ```

  **published** was one state and is now two, because the two halves are
  different news. A listing this tool has applied sits at Etsy as a draft
  until a person presses publish (non-goal 1 — the tool never activates a
  *draft*), and that wait is *deployed*: nothing is wrong, and nothing more
  will happen without a human. *Live* is the settled end of the line. Pause
  and resume of a listing already published is #64, not this wait.

  The asymmetry between **draft** and **dirty** is the other half. Both mean
  the workspace holds something Etsy does not; they differ in who is looking
  at the stale copy. An edit to something never published goes back to draft,
  because nobody is. An edit to a live listing is dirty, because a buyer is —
  and that is worth a different colour on a dashboard rather than the same
  one.
- Drift indicators where live remote state diverges from the lockfile.
- History of `plan` and `apply` runs with status, and live progress for anything
  currently running.

### Retiring and deleting

Two operations, not one. **Delete** retracts a listing that has never been
published on Etsy. **Retire** pauses one that has (`state=inactive`); local
files and the Printify product stay. Once a listing has left `draft`, delete
is `Blocked`. `listings_d` stays outside the granted scopes (#50). The field
is `lifecycle:` on `listing.yaml` — omitted, `retired`, `deleted`, or a
one-shot `renew` — not `status`, which the table already uses for the badge.
Gestures live on the listings table, rightmost column; there is no new CLI
verb. Detail, including what Printify `DELETE` does to an Etsy draft and what
`plan` does when Etsy pauses a listing we did not, is
[listing-lifecycle.md](listing-lifecycle.md) (#61–#67).

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

## AI Mode SEO proposals

AI Mode is a manual local editing aid inside the Details tab of a **saved**
listing. It sends the design image, one-line `brief`, garment context, and
relevant editor values to a locally authenticated coding-agent CLI. Vision can
infer style and audience; the brief carries exact design text that stylised
lettering might obscure.

- The Details tab exposes the listing brief for ordinary editing and autosave.
  AI Mode is always visible there, but disabled until the listing is saved, a
  design and non-empty brief are set, `prompts/seo.md` exists, and at least one
  provider is ready.
- Attaching a design to a listing whose brief is still empty drafts one from the
  artwork and writes it into that ordinary brief field, then requests the SEO
  proposal that brief unblocks (#68). The brief is an *input* the seller was
  going to have to type; it is the one listing field AI Mode fills without a
  per-value choice, and it is drafted only into an empty field, never over
  seller text. Title, tags, and description lead keep their explicit
  per-suggestion acceptance, unchanged.
- `prompts/brief.md` is the seller-editable drafting prompt for that brief, and
  a valid draft is one plain-text brief that records the design's subject,
  style, audience, and the exact wording shown in the artwork.
- Providers use their locally configured subscription accounts: Codex first,
  then Claude Code only for recognised unavailable, authentication/quota, or
  rate-limit failures. Neither an API key nor a model picker is part of v1.
- Each CLI runs in the real workspace with its available tools constrained to
  read-only, automatic non-interactive approval, no durable provider session,
  and access to readable workspace files. If the installed CLI cannot provide
  that read-only restriction, it is not ready and must not be launched.
- The request has one 60-second deadline, including one same-provider repair
  for malformed output and the permitted fallback. Leaving the editor,
  disconnecting, or pressing **Cancel** terminates the subprocess tree and
  retains no proposal.
- `prompts/seo.md` and `prompts/brief.md` are seller-editable plain instruction
  text. Setup seeds each default only when absent, never replacing seller
  content. The repository-root
  `seo_prompt.md` is a drafting source, not a runtime workspace prompt.
- A valid proposal has three titles, twenty unique ranked tags (the first
  thirteen are **Best 13**), three description leads, seven phrase rationales,
  warnings, and observed OCR text. Harmless formatting is normalised before
  Etsy limits, uniqueness, affiliation/content checks, and warning-only
  trademark checks are enforced.
- Unresolved choices live only in browser local storage for one day, scoped to
  workspace and listing. They are never written to `listing.yaml`, a lockfile,
  a generated file, or a remote listing. Relevant editor changes stale pending
  choices; accepted values remain ordinary seller edits.

The review gate is therefore the seller's direct choice in the listing editor,
before an accepted value can enter the normal autosave path. AI Mode never
participates in `plan` or `apply`; those commands deploy only the concrete,
seller-owned listing fields.

---

## Etsy field ownership

We own: **title, description, tags, images, shop section, materials, per-image
alt text, renewal policy, the `who_made`/`when_made`/`is_supply` declaration
with its production partner, the shipping profile, the return policy, and the
per-colour variation images.** Everything else stays as Printify left it.

The last four joined this list in Phase 3, and three of them are corrections
rather than additions: the shipping profile because Printify attaches its own
regardless of the sync flag and charges USD numerals as NOK (#58); the
production partner because Etsy refuses the listing without one (#52); and the
return policy because Printify creates one on first publish, so the shop's
policy set is something it writes to.

Renewal defaults to **manual** in `shop.yaml` and is overridable per listing,
written to Etsy's `should_auto_renew`.

**Processing time is the one buyer-facing field we do not own** (#55). It lives
per offering inside the inventory, which belongs to Printify, and every route
to it that avoids writing that document was measured and does not work.

*Known wrinkle:* Etsy requires a title at creation, so Printify's first publish
sets some title and description regardless of the sync flags — the flags govern
subsequent syncs. There is a brief window where the draft carries whatever copy
the Printify product holds before we overwrite it. Harmless for drafts, and
narrower than it looks: the product carries **our** title and description, not
Printify's generic ones, because the create call requires both and #44 makes
them real text (they are also the duplicate guard's match key, #48). The
publish flags still say `{title: false, description: false}` — the product
holding our copy does not make Printify a writer of it.

### Media sync

Explicit ordered media list per listing (mockups plus shared assets such as the
sizing chart), synced as a **full replacement** driven by a per-file hash.

The *mechanism* changed once measurement replaced assumption (#57). This
section used to say that because Etsy has no update-image endpoint, sync must
delete every image and re-upload in rank order — ten uploads to change one
photo. Two endpoints make that unnecessary: `image_ids` on `updateListing` is
an ordered full-replacement set that reorders and detaches without re-sending
bytes, and `uploadListingImage`'s `overwrite: true` replaces in place at an
occupied rank. So sync uploads only what changed, then asserts the order in one
call — which also clears Printify's first-publish mockups, an unknown number of
which arrive at an unknown time.

Two hazards came with it, both measured, both now the media stage's job: sent
as repeated form keys rather than one comma-separated value, `image_ids`
answers `200` and reduces the listing to a single image; and replacing an image
leaves any colour swatch bound to it (#56) pointing at an id no longer on the
listing, which Etsy also reports as a healthy `200`.

---

## CLI

| Command | Purpose |
|---|---|
| `setup` | Initialise an empty workspace: directory skeleton, `shop.yaml`, and the Printify and Etsy ids resolved from the live APIs (#49) |
| `new [<design>] [--category tshirt]` | Interactive garment/provider picker; writes garment profile (if absent) + listing |
| `ui` | Serve setup, dashboard, template authoring and plan/apply runner |
| `plan <listing\|--all>` | Three-way diff against live remote state; decides which stages need to run |
| `apply <listing\|--all>` | Execute every stage the plan identified, including rendering |
| `render <listing\|--all>` | Force a re-render (normally handled by apply) |
| `status [<listing>]` | Stage and remote state overview |
| `auth` | Every deployment credential, each verified before storage: Printify token, Etsy app key pair, and Etsy OAuth PKCE flow (#49) |
| `catalog refresh [<garment-profile>]` | Force-refresh the cached Printify catalog |
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

- Design file: **pixel dimensions within 10% of the garment profile's print area** in
  both axes — that is, at least 90% of its width and 90% of its height — and RGB
  with an alpha channel. **Rejected with an actionable error naming the required
  size — never auto-upscaled or converted.** Silent upscaling produces a blurry
  print discovered via customer complaint, and nothing downstream will catch it:
  Printify accepted a 120×140 PNG onto a 4200×4800 print area without so much as
  a warning ([api-findings.md](api-findings.md)).

  The measure is the print area rather than a DPI figure because the print area
  *is* the DPI figure — Printify's placeholder dimensions are already the pixels
  it wants at its own print resolution. The 10% tolerance is there because a
  design a few percent short upscales invisibly, while the failure this gate
  exists to catch is a design that is half the size or a tenth of it. A gate at
  exactly 100% would reject a 4000×4800 file for a 4200×4800 area — 4.8% short
  on one axis, indistinguishable in print — and a rule that fires on files
  nobody would call wrong gets turned off.
- The listing's garment profile still names the blueprint and print provider its
  Printify product was created with. A garment or printer change is a **hard
  error** — see below.
- Every requested colour slug resolves to a real variant in the catalog. A
  colour that resolves for *some* sizes but not all is not an error — the
  missing cells are reported and skipped (#46).
- **`etsy.title` and the final composed `etsy.description` are concrete and
  non-empty** before a Printify product may be created (#44). The description
  lead is required for deployment; a configured common-copy reference must
  resolve and be valid for descriptions.
- Every requested colour has a matching mockup file.
- Every media entry resolves: `mockup:` references name a colour the listing
  offers, paths exist. ≤20 images total.
- Every price carries an explicit currency, and it matches `shop.yaml`. Bare
  numbers are rejected.
- Blueprint and print provider names resolve to catalog IDs; failure lists the
  valid names.
- Copy is within Etsy limits, after the description is composed once from its
  lead and configured body source.
- **Every Etsy name resolves**: the shop section, the shipping profile and the
  production partner each name something the shop actually has, with failure
  listing the real candidates. A stale name is not a soft failure — a section
  id Etsy does not recognise fails the entire `updateListing` (#53).
- **`who_made: someone_else` has a production partner resolved** (#52). Etsy
  refuses the write without one, so this gate turns a `400` that blames the
  marketplace into a sentence naming the missing thing.
- **The return policy reference matches exactly one policy**, or the shop has
  exactly one and none is named (#59).
- **A `variation_images` reference names a `colour-matrix` template that the
  listing's own `media` uses** (#56). `multiple` and `single` templates have
  one output and no colour, so they have nothing to bind.

### Changing the garment is not an operation

Once a listing has a Printify product, its blueprint and print provider are
fixed. `plan` fails, naming both values, and says what to do instead: **start a
new listing**, or make the change by hand in Printify and Etsy.

This is a deliberate refusal, not a missing feature. Printify will not do it —
`PUT` with a different `blueprint_id` answers `200` and changes nothing, the
quietest failure in that API — so the only automated route would be delete the
product and create another. That discards the Etsy listing behind it along with
its reviews, favourites and search history, to save retyping a short YAML file.
A listing is cheap; the listing's history is not.

## Auth and secrets

Two commands, divided by what they own rather than by which service they talk
to: **`auth` captures every credential; `setup` builds the workspace and
resolves the ids** (#49). `auth` runs first, because every id `setup` writes is
discovered through a call that needs a credential.

Etsy alone needs two of them on every scoped call: an app key pair
(`x-api-key: <keystring>:<shared_secret>`) identifying the application, and an
OAuth bearer identifying the shop owner. So `auth` collects, in order, the
Printify token, the Etsy app key pair, the Etsy OAuth tokens — a localhost
callback server and the PKCE flow in the browser (access 1h, refresh 90d,
rotating on every use). **Each is verified against its own API before it is stored**: `GET /v1/shops.json` for Printify,
`openapi-ping` for the Etsy pair, the token exchange itself for the bearer. A
credential a wizard accepted and the service rejects produces a workspace that
looks configured and is not, which is worse than a question re-asked.

Each question says where the value comes from and what it must carry — the
Printify token needs `catalog.read` plus the shop scopes Phase 2 writes with;
the Etsy keystring and shared secret are both on the app's page, the secret
behind a visibility toggle. That guidance is the reason a credential wizard
beats a page of documentation, so it lives in the questions rather than beside
them.

Tokens land in gitignored `.auth/`, keys in `.env`, both in the workspace and
neither in this repository. Because `auth` runs before `shop.yaml` exists, it
writes the `.gitignore` covering them *before* it writes the first secret —
the one ordering here that protects something other than the user's patience.
It shares that writer with `setup` rather than keeping a second copy of the
list.

Re-running `auth` is also how a credential is rotated and how a lapsed Etsy
consent is renewed. Like `setup`, it fills gaps: an existing value is reported,
not silently replaced.

---

## Implementation phases

| Phase | Deliverable |
|---|---|
| 0 | Config schemas (pydantic), garment-profile/listing resolution, catalog fetch + cache, slugification, validation, lockfile model, `plan` skeleton |
| 1 | Render pipeline + calibration UI + `new` picker — fully local, valuable standalone |
| 2 | `setup` (43); Printify: variant resolution, product create/update, the validation gates (37, 38, 44) |
| 3 | Etsy: OAuth, publish + polling + `unlock`, the listing patch, media replace, renewal, variation images — [phase-3-etsy.md](phase-3-etsy.md) |
| 4 | Structured descriptions, common copy, and AI Mode proposals: local Codex/Claude runners, saved-listing API, and Details-tab acceptance UI |
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
12. **Printify's retail price against this shop's NOK prices — resolved: there
    is nothing to convert.** The conflict was real; the premise shared by both
    proposed resolutions was not. Printify publishes a retail price as a bare
    number and the sales channel renders it in its own currency — its
    documentation instructs sellers on non-USD channels to type the local figure
    and ignore the `USD` label, and its supported billing currencies (AUD, CAD,
    EUR, GBP, USD — **not** NOK) move the *cost* side only. NOK minor units go
    to `variants[].price` unchanged, no FX rate reaches `apply`, and nothing
    volatile reaches a hash (#39, #40).

    Two things remain, neither of them a decision. **To observe:** publish one
    product at `29900` into the NOK shop and confirm Etsy stores `299,00`. All
    of the above is Printify's documentation, and this project's standard is
    measurement — the same standard that caught the API reference being wrong
    about `visible`. **To guard:** Printify refuses to publish when the numeric
    retail price falls below the numeric USD production cost. NOK clears that by
    roughly 10×, so it will not fire in normal use, which is precisely why
    `plan` asserts it rather than waiting to be surprised by a mis-scaled price
    (#40) — in the **publish** stage, where the cost figure exists, per #40's
    amendment.

13. **Shipping rates pass through as bare numbers too, and that one does bite.**
    The same mechanism as the price, with the opposite consequence: Printify
    sends its USD shipping rates to Etsy as numerals, so a `$4.49` rate is
    published as `kr 4,49` — roughly a 90% shortfall on every shipment.
    Printify names the problem itself and offers exactly two ways out: set the
    Etsy shop currency to USD (2.5% on every deposit, refused here), or maintain
    Etsy shipping profiles that Printify never overwrites.

    The lever exists and is unused. `publish.json` takes `shipping_template`,
    documented as *"Used by Etsy and Amazon sales channels only. If set to
    false, product shipping template will not be updated"* — but nothing in this
    tool sets it, and no decision anywhere says what shipping should be.

    **The requirement is that both modes work: free shipping (cost absorbed into
    the NOK price) and paid shipping (a real NOK rate the buyer sees), starting
    with paid.** That rules out the easy answer of always publishing free
    shipping, and means the tool owns a shipping profile on the Etsy side rather
    than borrowing Printify's.

    **Settled, and worse than described, before it was closed** (#58). Measured
    against the connected shop: `shipping_template: false` does not prevent
    Printify creating and attaching its own profile on first publish, so the
    documented lever is a hint. The profile it made ships from `US` against a
    shop that ships from `NO`, and its rates read `kr 10,39` where `$10.39` was
    meant — the ~90% shortfall, now measured rather than predicted.

    The resolution is not a shipping stage and not a rate table in config. The
    tool **names an Etsy shipping profile and asserts it on every listing it
    manages**; because `read_live` reads the listing's actual
    `shipping_profile_id`, a profile Printify re-attaches is ordinary drift,
    which `plan` reports and `apply` repairs. Free and paid shipping both work
    by naming a different profile — a choice, not a code path. Rates are
    maintained in Shop Manager, where they can be created at all: the tool has
    `shops_r` and not `shops_w` (#50), which is deliberate.

    Two questions the probe could not close — whether the flag at least
    prevents *re-attachment*, and whether an assigned profile survives a
    republish — stop being blockers under that design, since drift is repaired
    either way. Both need a second shipping profile to exist before they can be
    distinguished at all.

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
| 4 | AI lifecycle | AI Mode is a saved-listing Details-tab editing aid. It obtains one temporary local proposal from Codex or Claude Code, and the seller directly accepts individual title, tag, or description-lead choices into ordinary autosave fields. It writes no generated file, lockfile, or remote state; `plan`/`apply` only see accepted concrete values. **Amended (#68):** attaching a design also drafts the listing `brief` and writes it straight into that field, then starts the SEO request automatically. The brief is a generation *input*, not one of the three SEO outputs the seller reviews, and drafting only ever fills an empty one — so the review gate on copy that reaches Etsy is unchanged, while the seller stops paying a two-minute wait for work that could already have run. |
| 5 | Render passes | Warp + displace + shade; shade on by default, displace off and tuned per template. |
| 6 | Placement config | Per-template `template.yaml`, per-listing override. |
| 6b | Calibrator | Browser UI with live preview through the real renderer. Lives only inside the `ui` app; no standalone command. Ships with a bundled test design. |
| 6c | Geometry | Four-corner quad (homography). |
| 6d | Per-colour geometry | Superseded by #28 — `colour-matrix` kind has no per-colour override at all; a colour needing different geometry is a separate `single`-kind template. |
| 6e | Occlusion masks | Deferred to v2. |
| 7a | Colour mapping | Convention: `colour-matrix`-kind mockup filename = slugified Printify colour name, or — if exactly one file matches — a filename ending in that slug's hyphen segments (for a shared vendor-pack prefix). Sparse exceptions file. `multiple`/`single` kind use a fixed `scene.png` instead (#28). |
| 7b | Variant IDs | Catalog cached with a TTL, fetched automatically; `catalog refresh` as override. |
| 8a | Config layering | Garment profile = garment definition (generated by `new`); listing = everything commercial and creative, including prices — now optionally sourced from a shared pricing plan (#33) as the base layer rather than written per listing every time. |
| 8b | Overrides | Anything overridable, every departure flagged in `plan`. |
| 9 | CLI | `plan`/`apply` primary; local-only stages standalone; no separate remote push verbs. |
| 10 | Pricing | Explicit table per listing, optional per-colour overrides, optional shared pricing-plan file (#33) as the base layer under both. Never set via Etsy API. |
| 10b | Margin | Gross only, labelled as excluding fees; live FX rate with rate and age always shown. |
| 11 | Etsy fields | Core + merchandising, plus renewal policy (default manual). |
| 12 | Media | Explicit per-listing list; full replace on change. |
| 13 | AI inputs | Vision + short brief; seller-editable `prompts/seo.md` and `prompts/brief.md`; hard proposal validation before the browser sees it. |
| 14 | Auth | Single guided `auth` covering the deployment credentials: Printify token, Etsy app key pair, and Etsy OAuth flow, each verified before storage. AI Mode instead uses already-authenticated local coding-agent CLIs and stores no provider credential. **Amended:** it writes credentials and nothing else — no `shop.yaml`, no ids (#49). One command to answer "what do I need to give this tool, and where does it go" beats a credential list split across two wizards by which service happens to need a browser. **Amended:** it also takes the part as an argument -- `auth printify`, `auth etsy` -- with bare `auth` running both. One credential expiring is the ordinary case, and having to walk past a working one to renew the other is what teaches people to avoid the command. |
| 15 | Failures | Resumable staged apply; `unlock` for stuck products. |
| 16 | Batch | Sequential, rate-limited, continue-on-error. |
| 17 | Design validation | Strict, never auto-fix. |
| 18 | Testing | Golden files + recorded fixtures + manual E2E. |
| 19 | `new` | Interactive garment/provider picker from the Printify catalog; generates garment profile + listing. |
| 20 | UI scope | Read-only dashboard + template authoring + plan/apply runner. |
| 21 | Live listings | `plan` marks LIVE and shows the diff; `apply` proceeds without a special flag. |
| 22 | Mockup storage | Rendered mockups persist in gitignored `.cache/renders/` — not regenerated every run, not committed. |
| 23 | Provider references | Print providers referred to by name in all config; blueprints by a `{brand, model, title}` object, matched on brand + model. Both resolve to Printify IDs via a cached lookup. Revised after the e2e layer found that Printify has no blueprint titled "Comfort Colors 1717": titles there are generic ("Unisex Garment-Dyed T-shirt"), shared across brands, and rewritten over time, so a title is not an identifier. `title` stays on the object as readable context and is not matched. |
| 24 | Price units | Every price carries an explicit currency (`349 NOK`); bare numbers and mismatched currencies are rejected. |
| 25 | Media references | Superseded by #29 — always-explicit `{template, colour?}` references, no bare-colour shorthand. |
| 26 | First run | The `ui` opens a setup wizard when no shop is connected — Etsy and Printify auth and guided `shop.yaml` generation. AI Mode readiness is independent and checks locally authenticated provider CLIs only when used. |
| 27 | Stage orchestration | `plan` determines whether rendering needs to run from input hashes; `apply` runs it. `render` remains available as an explicit command. AI Mode proposals are browser-only and never a stage. |
| 28 | Template kinds | A template is exactly one of `colour-matrix` / `multiple` / `single`, never a mix — [docs/multi-placement-rendering.md](multi-placement-rendering.md). |
| 29 | Multiple templates per listing | No garment-profile-level registry of *listing* templates — a listing's `media:` may reference any template that exists in `mockup-templates/`, always naming it explicitly as `{template, colour?}`; no default, no shorthand. Superseded once from an earlier `profile.templates: list[str]` registry, dropped because a template is a purely local, Etsy-facing asset Printify never sees. **Amended:** the garment profile may name one `preview_template`, a `colour-matrix` template the editor uses to judge colours. That is not a `media:` default and does not decide what renders. |
| 30 | Multi-artwork | `listing.design:` polymorphic (bare path or a map keyed by artwork tag); `garment_profile.colors` classified by hand-editing the generated garment profile file (`new` does not ask), not inferred from Printify. |
| 31 | What renders | Driven purely by `media` references, not by `listing.colors` membership — a listing's colours drive which Printify variants sell, not which photos render. |
| 32 | Frontend testing | Vitest + React Testing Library, v8 coverage provider, 80%-branch floor mirroring the Python gate, wired into `scripts/check.sh`. |
| 33 | Pricing plan | A separate, reusable `pricing-plans/{name}.yaml` file holding a per-size price table plus optional per-colour overrides (same shape as the listing's own) and a `garment_profile:` back-reference. `Listing.resolved_price` precedence: `price_overrides` > `prices` > the plan's own (override-then-flat) resolution. Named "pricing plan", not "pricing profile", to avoid colliding with the existing `GarmentProfile` concept. |
| 34 | Pricing plan reference | A listing references a pricing plan by workspace-relative path (`pricing_plan: ../../pricing-plans/x.yaml`), the same mechanism as `design:` — not a bare name against a fixed root, unlike `garment_profile:`/`media[].template` (#29). `pricing-plans/` is a conventional discovery root for `new`'s picker, not an enforced resolution root — nested layouts, and plans stored elsewhere, both work. Migrating `media[].template` to the same path-based scheme is explicitly out of scope: it would also touch the calibrator UI/API and render-cache key naming, a separate, larger piece of work. |
| 35 | Undocumented cost data | `new`'s "create a pricing plan" flow reads Printify's undocumented per-variant manufacturing-cost endpoint (`product-catalog-service`, no auth, no docs — verified working in this project against a live response) to seed a starting price, joined against the public `variants.json` catalog on variant id for colour/size names. Isolated in its own module outside the documented `catalog/` surface, fail-soft by construction: any failure degrades to a blank price for the affected size(s), never aborts `new`. `decoration_method` is hardcoded to `dtg` (risk item 11). Shipping cost, by contrast, comes from Printify's documented `shipping.json` endpoint and lives in the normal `catalog/` client. |
| 36 | Wizard-time FX | The starting-price computation ((manufacturing + shipping) × 1.10 margin) converts USD cost to the shop currency via a minimal, uncached, one-off live rate fetch — deliberately not the deferred full-margin-model FX cache (#10b); that remains unbuilt. Where colours offering the same size disagree on cost, the max is used and the disagreement is noted in the generated file's comment. |
| 37 | Changing the garment | Refused, not automated. Once a listing has a Printify product its blueprint and print provider are fixed; `plan` fails and says to start a new listing or make the change by hand. Printify silently ignores both fields on an update (`200`, no change — [api-findings.md](api-findings.md)), so the only automated route is delete-and-recreate, which throws away the Etsy listing's history to save retyping a short file. |
| 38 | Design resolution gate | A design must be **within 10% of the garment profile's print area** — at least 90% of it on each axis. Replaces the earlier "~300 DPI for the print area", which said the same thing less checkably: Printify's placeholder dimensions already *are* its print resolution. Verified necessary — Printify accepts a 120×140 file onto a 4200×4800 area silently, so nothing else in the chain will catch it. The tolerance is not slack for its own sake: a few percent short upscales invisibly, and a gate that rejects a 4000×4800 file for a 4200×4800 area is a gate that gets switched off. |
| 39 | Printify price units | Integer **minor units of the connected sales channel's currency** — not USD cents. Printify converts nothing on publish: it sends the number and the channel renders it in the shop currency, which is what its own instruction to non-USD sellers ("enter 24.99 … and ignore the 'USD' label") describes. The `USD` badge in the web app is a fixed label. This corrects an earlier reading of the same measurement: the integers were measured correctly, the currency attached to them was inferred from a UI string, and that inference is what produced risk 12. |
| 40 | Retail price currency | NOK reaches Printify verbatim, as NOK minor units; `Money` stays NOK from `shop.yaml` to the wire, and no conversion happens at `apply`. Rejected — converting NOK→USD at apply time, which puts a live rate inside a hash-based idempotency system and churns every listing on a day nobody edited anything; pricing in USD and letting Printify's conversion set the Etsy figure, which surrenders the number the customer reads; and changing Printify's billing currency, which does not offer NOK and converts costs only. Accepted costs: Printify's own profit and listing-health figures compare an NOK number against a USD cost and are meaningless, leaving this tool's margin display (#10b) the only honest one; and `plan` must assert the numeric price is at or above the numeric USD production cost, because Printify refuses to publish below it. **Amended:** that assertion belongs to the **publish** stage, not the product stage. `variants[].cost` exists only on a product that already exists, so before the first create there is no documented source for it — the only other one is walled off from the engine by A17 — and Printify enforces the rule at publish anyway. Phase 3 gets it free from its own `read_live`; asserting it earlier would mean either skipping the run that matters or breaching A17. |
| 41 | Update routing | Printify creates the product and publishes once with only the fields it needs to exist and route orders. Thereafter each field has exactly one writer: the **variant matrix** (colour, size, price, SKU) is Printify's, changed there and republished with selective sync `{variants: true}` and every other flag false; **everything the buyer reads** (title, description, tags, materials, images, shop section, alt text, renewal) is ours, written straight to Etsy. Refines #1 by making the boundary exhaustive rather than exemplary. Rests entirely on the sync booleans behaving as documented — risk 2 — since they are what stops a variant republish from overwriting our copy and mockups. |
| 42 | Printify shop id | Stored in `shop.yaml` as `printify.shop_id`, written by `setup` (#43) from `GET /v1/shops.json`, which returns exactly the shops the token can reach. Discovered rather than typed, because the id appears in no obvious place in Printify's UI; stored rather than resolved per run, because an account that gains a second shop must not silently start creating products somewhere else. Unlike a print provider (#23) there is no name to match on — a shop's title is whatever the owner typed. **Amended (#51):** the title is stored beside the id all the same, as `printify.shop_name`. It is not a resolution key -- the id remains what `setup` selects and stores -- but it is what makes the stored id checkable by a human, which the number alone never was. |
| 43 | `setup` command | A terminal command that takes an empty directory to a workspace `new` can run in: directory skeleton and `.gitignore`, a guided Printify token capture **verified against the live API before it is stored**, the shop selection above, and the Etsy/commercial defaults written to `shop.yaml`. Stops short of Etsy OAuth, which is `auth`'s job (#14) and Phase 3's code, and says so. Idempotent — re-running fills only what is missing. Does not replace the `ui` first-run wizard (#26): a terminal path to a working workspace has to exist before there is a UI to serve it. **Amended (#49):** `setup` no longer captures any credential — the Printify token capture named above moved to `auth`, which runs first. What `setup` gained in exchange is the whole id-resolution job: `printify.shop_id` as before, plus `etsy.shop_id`, `etsy.shop_section_id` and `etsy.return_policy_id`. It no longer stops short of Etsy; it stops short of *credentials*. |
| 44 | Printify product copy | The product carries the listing's **own** concrete title and final composed description; empty copy is refused at `plan` time. Printify's create call requires both, so something must be sent; sending the real copy makes the product legible in Printify's web app and gives #48 its match key. It does **not** make Printify a writer of them: the publish flags stay `{title: false, description: false}` (#41), and the fields reach Etsy only through `updateListing`. AI Mode may help draft fields, but the seller must accept them into ordinary listing content first. Accepted cost: a copy edit shows a diff on the Printify stage. |
| 45 | Print placement | Fixed — centred, `scale: 1.0`, `angle: 0`, into `garment_profile.placeholder`. No per-listing or per-template configuration in v1. `scale: 1.0` means fit-inside-the-print-area, and #38 already requires the design to be within 10% of that area on each axis, so the constant is the consequence of a gate rather than a default nobody chose. Revisit if a garment ever needs off-centre or rotated placement; a config surface added speculatively would need a calibrator to be usable. |
| 46 | Missing variant cells | A colour × size combination the catalog does not offer is **reported and skipped**, not fatal. The requested matrix is `listing.colors` × `garment_profile.sizes`, and Printify discontinues individual cells (`Berry / 4XL`); refusing the listing would force the user to drop a size for every colour or drop the colour entirely, to record a fact that is Printify's rather than theirs. A colour with *no* variants at all remains a hard error — that one is a typo. |
| 47 | SKUs | Printify's. `variants[].sku` is writable and reads back verbatim, measured, so this is a choice rather than a limit — but the only thing our own SKU bought was #48's match key, and #48 has one without it. Declining leaves one less field to keep synchronised on a matrix where every entry must already carry a price. Refines #41, which listed SKU as part of Printify's variant matrix without saying whether we set it. |
| 48 | Duplicate-create guard | The lockfile's `printify_product_id` is the primary guard; before a create — and **only** before a create — the stage also walks `GET /shops/{id}/products.json` and refuses if a product already matches on title and description. `POST products.json` has no idempotency key and no conflict, so the window the lockfile cannot close is create-succeeds-then-crash. The product list is a paginator that honours `limit`/`page` and **no filter whatsoever** (`title`, `search`, `sku` are accepted and ignored), so the match is client-side over a full walk — affordable because it runs on the rare create path, never on a no-op `plan`. Corrects the implementation plan, which asserted a pre-flight lookup without a key to look up by. |
| 49 | Credentials versus configuration | `auth` captures every credential and writes only `.env` and `.auth/`; `setup` creates the workspace and writes every id into `shop.yaml`. The line is what the value *is*, not which vendor it belongs to: a credential is something a human obtains from a website and pastes, an id is something this tool discovers by asking an API. Ordering follows from that — `auth` first, because every discovery call `setup` makes needs a credential to make it with. Two consequences worth stating. `auth` runs before `shop.yaml` exists, so like `setup` it takes its root from `--root`, `ETSY_LISTINGS_ROOT` or cwd rather than discovering it (A8 governs commands that *use* a workspace, not the two that create one); and it writes the `.gitignore` before the first secret, sharing `setup`'s writer. This also records a second Etsy secret the document had been silent about: the app key pair is keystring **and** shared secret, colon-joined into `x-api-key` on every v3 request. Rejected: splitting the credentials by whether they need a browser, which put the Etsy key pair in `setup` and left a user hunting two commands for the answer to one question; and letting `auth` write ids, which would make the workspace's identity wait on a browser round trip it never needed — `findShops`, `getShopSections` and `getShopReturnPolicies` carry no scope, so the ids need the key pair only. |
| 50 | Etsy OAuth parameters | Scopes `listings_r listings_w shops_r`; callback `http://localhost:8517/oauth/callback`, registered verbatim with the app; refresh on demand, with a warning as the 90-day refresh token nears expiry. The scopes are the smallest set covering Phases 3-6 — image upload *and* delete are both `listings_w`, and `listings_d` deletes listings, which this tool never does — and are worth choosing once, because changing them later forces a second trip through the browser. The port is fixed rather than OS-assigned because Etsy matches `redirect_uri` against a registered string exactly, case and trailing slash included; an ephemeral port cannot be registered in advance, so a busy 8517 is a clear error rather than a silent fallback Etsy would refuse. One caveat carried knowingly: Etsy's authentication guide says the redirect must be `https://`, while Etsy's own quick-start tutorial uses `http://localhost:3003/oauth/redirect` throughout. Loopback over http is the documented-by-example exception, and the first real `auth` run is what confirms it. |
| 51 | `shop.yaml` grouped by service, keyed by name | Every setting sits under the service that owns it: `printify.shop_name`, `printify.shop_id`, `printify.preferred_print_provider`; `etsy.shop_name`, `etsy.shop_id`, `etsy.currency` and the listing defaults. Two top-level keys moved to get there. `currency` is the Etsy shop's own currency, now **read from the shop** rather than typed, so it belongs with the shop it describes; #24 is untouched, and it remains the only currency a price may be written in. `preferred_print_provider` names a Printify entity and was top-level only because it arrived first. Each shop is then identified by **name with the id beside it**: the name is what a human recognises, the id is what the API needs, and `setup` derives the second from the first. Discovery follows what is already connected — a Printify shop whose sales channel is Etsy carries the Etsy shop's name, and where there is no connection the id comes from the shop the stored consent owns. Rejected: the id alone, which is what the file held. An eight-digit number tells a reader nothing, so a wrong one looks exactly like a right one — the PRD's own example `12345678` sat in a real workspace for a phase and a half without being noticed. |
| 52 | Who made it, and who printed it | `who_made: someone_else` — the shirt genuinely was made by another company — with a **production partner attached to the listing**, which Etsy requires and refuses the write without. Measured: the same PATCH answers `400 "you cannot sell this item on Etsy"` with no partner on the listing and `200` with one, *even when a partner exists in the shop*. An earlier reading of that 400 — that a made-to-order finished item may not be declared `someone_else` at all — came from three controls that each dodged the partner requirement rather than satisfying it, and is disproved. The partner is **not** derived from `garment_profile.print_provider`: Etsy carries `The Print Provider` where the garment profile says `Monster Digital`, the location matching while the name is deliberately generic, because Printify's guidance produces one anonymous partner standing in for whichever printer fulfils an order. Resolution is therefore: named explicitly (listing > garment profile > `listing_defaults`), else the shop's sole partner, else an error listing candidates by name **and location** — generic names make the location the distinguishing half. A listing whose partner does not resolve is blocked at `plan` time, because under `someone_else` an unresolved partner is not a policy nicety but a guaranteed `400`. |
| 53 | Shop section, per listing only | A listing names its section by **name** (`etsy.section`), resolved per run through `getShopSections`, which carries no scope. **No shop-wide default**: which part of a shop a listing belongs in is a fact about that listing, and a default would be right for the first one and wrong from the second onwards. `etsy.shop_section_id` therefore leaves `shop.yaml` entirely, and `setup` stops resolving it — amending #43/#49, which had `setup` writing four ids. Measured: a stale section id fails the *whole* `updateListing`, so resolution is load-bearing rather than cosmetic. |
| 54 | Shipping profile by name | `listing_defaults.shipping_profile` names an Etsy shipping profile by its `title`, overridable per listing. Resolved per run through `getShopShippingProfiles` (`shops_r`), filtering `is_deleted`; an unresolvable name fails loudly rather than falling back to whatever Printify attached. The tool never *creates* a profile — that needs `shops_w`, outside the granted scopes (#50) — so both shipping modes the PRD requires become a choice of which named profile, not a code path. |
| 55 | Processing time is read, never written | The tool **never calls `updateListingInventory`**, recorded as an invariant: it is a full-replace PUT over the variant matrix #41 gives to Printify, and its failure mode is an unsellable listing rather than a wrong word. That closes the only route to Etsy's processing profiles, which are attached per *offering* inside the inventory. The two levers that would have avoided it were measured and do not work: this shop is on processing profiles, so the shipping profile does not carry processing time; and `processing_min`/`processing_max` on `updateListing` answer `200` and change nothing — the second silent-`200` in this project after Printify's `blueprint_id`, and the more dangerous because both fields *are* documented as writable on `createDraftListing`. `readiness_state_id` on `updateListing` is untested rather than working: the shop has one definition and it was already the value in place. The practical cost is near zero — Printify applies the shop's single profile to every offering at publish — so `plan` surfaces processing time and reports drift, the same treatment as the shop's draft setting (risk 5). |
| 56 | Per-colour variation images | Opt-in per listing, `etsy.variation_images: <template>`, naming the `colour-matrix` template whose renders become Etsy's colour swatches; absent means off. The join is: find the colour property **by its values** — measured, it is `property_id 513` named `Comfort Colors® Colors`, the *blueprint's* option name, so matching on `"Color"` finds nothing and hardcoding 513 picks the wrong property on the next garment — then slugify Etsy's value strings onto `listing.colors` (`"Black"` → `black`, the same convention as #7a, since Printify's colour names reach Etsy verbatim), then resolve each colour to the image id its media entry was uploaded under. Rejected: `true` with first-match-wins, which makes media *order* silently decide swatch content. A replaced image leaves its link **dangling and reported as a healthy `200`**, so re-asserting whenever an image id changed is a measured requirement, not a precaution. Deferred: swatches from `single`-kind or shared assets, which need a `depicts:` annotation rather than overloading `media[].colour` — that key addresses a render, and a swatch needs a claim about content. |
| 57 | Media sync mechanism | **Supersedes #12's mechanism, not its meaning.** Upload only what the per-file hash says changed, then `PATCH updateListing` with `image_ids` as **one comma-separated value**, which orders our images and detaches everything else — including Printify's first-publish mockups, of which an unknown number arrive at an unknown time. `overwrite: true` replaces in place at an occupied rank, so a re-rendered mockup that has not moved costs one call and no reorder. Sync is still full-replacement in meaning, still hash-driven, still an explicit ordered manifest. The premise #12 rested on — that reordering requires re-uploading — was measured false. The encoding is the sharp edge and gets its own test: sent as repeated form keys, `image_ids` answers `200` and reduces the listing to one image. |
| 58 | Shipping ownership | The tool owns the Etsy-side shipping profile by **asserting it on every listing it manages**, and `shipping_template: false` is treated as a hint rather than a guarantee — measured, Printify creates and attaches its own US-origin profile on first publish regardless, publishing USD rates as NOK numerals (`$10.39` → `kr 10,39`, a ~90% shortfall). This closes risk 13 by design rather than by a flag: `read_live` reads the listing's actual `shipping_profile_id`, so a profile Printify re-attaches is **drift**, `plan` reports it, and `apply` re-asserts. No always-rewrite special case, and no dependence on a boolean Printify honours only sometimes. |
| 59 | Referring to a return policy | By its **terms**, not its id: `return_policy: {accepts_returns, accepts_exchanges, within_days}`, resolved by exact match against `getShopReturnPolicies`. Etsy gives a return policy no title, but the three terms are its identity — `return_deadline` is constrained to `[7, 14, 21, 30, 45, 60, 90]`, and Etsy ships `consolidateShopReturnPolicies` precisely because duplicate term-sets are merged rather than kept. **Omitting it is the zero-config path**: a shop with exactly one policy needs no reference. Two or more with none named is an error listing them by their terms, because guessing which refund policy was meant is not a thing a tool should do. Same ladder as #52's partner, for the same reason: when Etsy offers exactly one, do not make anyone name it. |
| 60 | Renaming a listing | A listing's identity is its directory name, and the editor's page head renames it in place (double-click the title). The rename moves `listings/{name}/` whole — document and lockfile — and `.cache/renders/{name}/` with it, so the next `plan` reports no change; leaving the cache behind would cost a full re-render (the hash carries no listing name, so nothing would re-upload) and orphan a tree nothing deletes. Browser-local unresolved AI proposals are scoped to the listing and are not moved as workspace files. The lockfile's `outputs` keys are left stale deliberately: nothing reads them, they become true again at the next apply, and rewriting them from the API layer would breach "only the lockfile merges a lockfile". Nothing remote is keyed by the name — both remote titles come from `etsy.title` and both ids from the lockfile — so a rename costs no remote write. A name already in use is refused, never merged into. |
| 61 | Delete vs retire | Two operations. **Delete** retracts never-live listings (local-only, Printify-only, Etsy `draft`). **Retire** pauses a published listing (`state=inactive`); files and the Printify product stay. Once a listing has left `draft`, delete is `Blocked` — the history PRD 37 refused to throw away for a garment change. `listings_d` stays outside `SCOPES` (#50): this tool still never calls Etsy's `deleteListing`. Draft retraction is Printify's cascade (#63), not Etsy's delete. Detail: [listing-lifecycle.md](listing-lifecycle.md). |
| 62 | `lifecycle` field | Optional key on `listing.yaml`: omitted (working, including after Un-retire), `retired`, `deleted`, or one-shot `renew`. Named `lifecycle`, not `status`, because the table already has a Status column for the badge. `plan` never writes the yaml. Wrong verb (`deleted` on published, `retired` on never-live) is `Blocked`, never rewritten as the right one. |
| 63 | Never-live delete | No remotes: confirm dialog, rm `listings/{name}/` and `.cache/renders/{name}/` now — `plan` never sees it. Remotes: confirm, write `lifecycle: deleted`, pending-delete badge, `apply` is retract-only. Printify `DELETE` of the **still-connected** product (never `unpublish.json` first); `GET` the Etsy id; `404` then wipe files; still there then fail and keep the files. Unpublish-then-DELETE orphans the draft (measured 2026-09-10); connected DELETE takes it (measured in e2e teardown). Live cascade unmeasured, and delete is `Blocked` there anyway. |
| 64 | Etsy `state` writes | Never sent on a `draft` — first publish stays Shop Manager, non-goal 1. `lifecycle: retired` → apply sends `inactive`. Apply sends `active` only for Un-retire (last applied was `retired`, now omitted) or `renew`. Edits while retired stay retired; a typo does not put the listing back on sale. Copy and media still sync on a retired listing; a deleted one is retract-only. |
| 65 | Remote pause | Plan **reads** Etsy `state`. It does not write yaml and does not send `active` because the field was omitted. Names `inactive` / `expired` / `removed` and says apply will not reactivate. Two explicit gestures: Retire (adopt) and Renew (`lifecycle: renew`). `sold_out` is inventory, stays `live`. Auto-adopting `retired` into the file would make Etsy the author of `listing.yaml`. |
| 66 | Gestures | Listings table, rightmost column. Never-live → Delete; live → Retire; pending-retire / retired applied → Un-retire; pending-delete → Cancel; Etsy paused us → Retire \| Renew. Delete confirms (dialog, no typing). No editor-page copy, no CLI twins. Yaml hand-edit still works. |
| 67 | Missing `listing.yaml` | Directory with a lockfile and no yaml still appears, `Blocked`: restore the file. Never infer retire or delete — a missing file is not consent. Whole `listings/{name}/` tree gone is invisible and out of scope; no shop-wide crawl for ids no local file names. |
| 68 | Drafting on design attach | Attaching a design to a listing whose `brief` is empty drafts one from the artwork through the same provider chain AI Mode uses, writes it into that ordinary field, and then requests the SEO proposal the filled brief unblocks. The draft goes out **on the pick**, waiting for nothing: it is a request about a design, not a listing, so it takes the design alone and needs no saved file, no name, no garment profile and no autosave — which is what lets it serve the flow it exists for, where the design is attached before the listing is named. Only that one transition arms it: opening an editor, typing, or changing any other field never starts a request, and a brief the seller has written is never redrafted or overwritten. The chain is the open editor's, not a server job — leaving the listing abandons it, exactly as pressing **Cancel** does (#4's cancellation rule). Drafting the brief is an input the seller would otherwise type; the three SEO outputs still reach `listing.yaml` only through an explicit per-suggestion choice. The page head reports each step beside the autosave line, since the seller is normally on another tab while it runs. |
| 70 | Naming writes it; nothing else withholds it | A named listing is written, full stop. Incompleteness is never a reason to withhold the file: no garment profile, no colours, no price source, no title, no lead, no images — all of them block *deployment* and none of them blocks the save. Before this, the price-source rule sat in `Listing` itself, so a seller could name a listing, attach a design and pick colours and still have nothing on disk, with the head explaining that the file would appear once they picked a plan. That is the tool withholding a file the seller plainly asked for, and it is the one incompleteness out of eight that behaved differently from the rest. The rule keeps its refusal — `plan` and `apply` still stop, as a `Blocked` from the stage that needs a price — and the banner keeps its sentence; only the write stops depending on it. What still refuses a write is a document that is *malformed* rather than incomplete: a title over Etsy's limit, a price in the wrong currency, a `media` entry naming a colour the listing does not sell. Those come back as `field_errors` on the field that caused them, as they already did. |
| 69 | A design names an unnamed draft | Picking a design for a listing that has no name yet names it after the design's filename, without the extension — the same derivation `new <design>` already makes on the CLI, and the name a seller would have typed. Only a *nameless* draft takes one: a listing already called something is called that on purpose, and changing its artwork is not a reason to move its directory. The name shows in the page head from the pick, not from when the file appears, because a create is still refused until the document validates and a name held invisibly until then reads as the tool renaming things by itself. A name already in use is refused exactly as a typed one is (#60). With this, and #70, the ordinary create flow is one gesture: open the editor and pick a design. |
