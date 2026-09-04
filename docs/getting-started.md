# Getting started

A hands-on walkthrough of what's actually runnable today: install the tool,
try it against a ready-made workspace with zero setup, then build your own —
a workspace, a design, a mockup template, a profile and a listing — and run
`plan`/`apply` against it.

**Status check first.** Only Phases 0 and 1 are implemented: workspace
discovery, config, the render pipeline, the `plan`/`apply`/`new`/`ui`
commands, and the browser calibrator. `apply` only ever runs the `render`
stage — nothing here talks to Printify or Etsy yet. That's expected, not a
bug in the tool or in this guide. See [README.md](../README.md) and
[docs/prd.md](prd.md) for the full roadmap.

## 1. Install

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+ (uv manages the
interpreter for you), run from **zsh under cygwin** — see
[CLAUDE.md](../CLAUDE.md) for why other Windows shells misbehave here.

```bash
uv sync
```

This creates `.venv/` and installs the `etsy-listings` CLI in editable mode.
Confirm it's on your PATH:

```bash
uv run etsy-listings --help
```

You'll see four commands: `plan`, `apply`, `new`, `ui`. That's the entire
implemented surface — anything else (`auth`, `catalog refresh`, `unlock`,
`status`) is designed but not built; see "What's not here yet" at the bottom.

Node is only needed if you want to run the calibrator's frontend in dev mode
(§5) — skip it for now.

## 2. Try it in two minutes, no setup

This repository's test suite ships a small, real, synthetic workspace at
[`tests/fixtures/workspace/`](../tests/fixtures/workspace/) — a `shop.yaml`, a
profile, a listing, a design, and two mockup templates. You can point the CLI
straight at it and run a real `plan`/`apply` without creating anything of your
own:

```bash
uv run etsy-listings plan take-a-hike --root tests/fixtures/workspace
```

```
take-a-hike

  + render (no previous render)

  1 to run, 0 to change, 0 drift warning(s)
```

That's a genuine three-way diff — it's telling you the `render` stage hasn't
run yet for this listing. Apply it:

```bash
uv run etsy-listings apply take-a-hike --root tests/fixtures/workspace
```

```
applying take-a-hike
  applying render
  rendered flat-lay-01/black
  rendered flat-lay-01/blue-jean
  rendered flat-lay-01/ivory
  rendered flat-lay-01/moss
```

Open the PNGs it wrote — `tests/fixtures/workspace/.cache/renders/take-a-hike/flat-lay-01/*.png`
— and you'll see the grid/ruler test design warped onto each garment colour.
Run `plan` again and it reports **no changes**: nothing about the inputs
changed, so nothing reruns. That idempotency is the whole point of the tool.

Don't commit anything under `.cache/` if you experiment here — it's
gitignored and fully derivable, so `git status` should stay clean. If you want
to poke at this without touching the repo's own fixtures at all, copy the
directory elsewhere first:

```bash
cp -r tests/fixtures/workspace /tmp/try-workspace
uv run etsy-listings apply take-a-hike --root /tmp/try-workspace
```

## 3. Set up your own workspace

The workspace is a directory **you** own, entirely separate from this repo —
never point `--root` at the repo itself for real work. Create it anywhere:

```bash
mkdir -p ~/etsy-listings/{designs,mockup-templates,listings,common-media}
cd ~/etsy-listings
```

Write `shop.yaml` at the root. Only `currency` and the `etsy.*` fields shown
below are required today — `shop_section_id`/`return_policy_id` are Phase 3
fields, leave them out until then:

```yaml
etsy:
  shop_id: 12345678
  who_made: i_did
  when_made: made_to_order
  is_supply: false
  renewal: manual
currency: NOK
preferred_print_provider: Monster Digital   # optional; used by `new`'s default
```

`shop_id` is a placeholder for now — nothing in Phase 0/1 calls Printify or
Etsy, so any number works. Every price you write anywhere in this workspace
must be in the currency you set here (`349 NOK`, never a bare `349` — see
`Money` in [config/money.py](../src/etsy_listings/config/money.py)).

Point the tool at this workspace one of two ways:

```bash
uv run etsy-listings plan <listing> --root ~/etsy-listings
# or, once per shell:
export ETSY_LISTINGS_ROOT=~/etsy-listings
uv run etsy-listings plan <listing>
```

Without either, the CLI walks up from your current directory looking for
`shop.yaml` — so running from inside the workspace works too, with no flag.

## 4. Add a design

Drop an RGBA PNG into `designs/`, e.g. `designs/take-a-hike.png`. It needs to
be large enough for ~300 DPI over your garment's print area — a 4500×5400
print area wants a 4500×5400-or-larger design. Rendering never upscales; too
small fails loudly, naming the required size.

A design that needs different ink for light vs. dark garments carries more
than one file — that's configured per-listing (§7), not here.

## 5. Add a mockup template

A template is a folder under `mockup-templates/<name>/` containing one or
more garment photos plus a `template.yaml` describing where the design sits
on them. There are exactly three kinds — a template is always one, never a
mix:

| Kind | Use it for | Scene file(s) |
|---|---|---|
| `colour-matrix` | One photo per colour, design in the identical spot on all of them (a flat-lay shot re-taken per colour) | `{colour-slug}.png`, one per colour |
| `multiple` | Several garments together in one photo (a colour chart) | one `scene.png` |
| `single` | One photo, one garment | one `scene.png` |

The easiest way to get the geometry right is the **calibrator** — a browser
UI that renders through the real pipeline live as you drag. Build the
frontend once, then run both halves:

```bash
cd src/etsy_listings/ui/frontend && npm install && npm run build && cd -
uv run etsy-listings ui --root ~/etsy-listings --port 8000
```

Open `http://localhost:8000`. From there:

1. Pick (or create) a template, choose its kind, and upload the photo(s) —
   one file for `multiple`/`single`, one per colour for `colour-matrix`.
2. Drag the corner handles of the bounding box (or boxes, for `multiple`) onto
   where the design should sit; use the shade/displace sliders to match the
   fabric's lighting and texture.
3. Toggle to the grid/ruler test design if you want warp errors to be more
   obvious than your real artwork makes them.
4. **Save** — this writes `mockup-templates/<name>/template.yaml`.

If you'd rather iterate with hot-reload while working on the frontend itself,
run the dev server instead of the built one in a second terminal (it proxies
`/api` to the backend):

```bash
cd src/etsy_listings/ui/frontend && npm run dev   # http://localhost:5173
```

You can also hand-write `template.yaml` — no calibrator required, just less
convenient for getting pixel coordinates right. A `colour-matrix` example:

```yaml
kind: colour-matrix
bounding_box:
  - { x: 144.0, y: 126.72 }
  - { x: 345.6, y: 115.2 }
  - { x: 355.2, y: 391.68 }
  - { x: 134.4, y: 403.2 }
shade: { enabled: true, opacity: 0.6, blend: soft-light }
```

Full schema and worked examples for all three kinds, plus how light/dark
artwork resolves per colour, are in
[docs/multi-placement-rendering.md](multi-placement-rendering.md).

## 6. Add a profile and a listing

A **profile** (`profiles/<name>.yaml`) is the garment definition — blueprint,
print provider, print area, sizes — reused by every listing built on it. A
**listing** (`listings/<name>/listing.yaml`) is everything commercial and
creative for one product: prices, colours, which template(s) render as its
photos, Etsy copy.

### The easy way: `new`

```bash
uv run etsy-listings new take-a-hike --root ~/etsy-listings
```

This talks to Printify's public catalog live (no auth token needed for
read-only catalog calls) and interactively:

1. Lists garments (`--category` filters by blueprint category, default
   `tshirt`) — pick one.
2. Lists print providers for that garment — pick one (defaults to
   `preferred_print_provider` from `shop.yaml` if it's offered).
3. Resolves the provider's colours to slugs, flagging any collision against
   `exceptions.yaml` (see below).
4. Asks which mockup template to reference (must already exist under
   `mockup-templates/`).
5. Optionally walks each colour asking light/dark, to seed the profile's
   `colour_tone` — skip this if every design you'll use on this garment needs
   only one ink file.
6. Asks a starting per-size price.

It writes `profiles/<blueprint-slug>.yaml` (reusing it if a profile for that
blueprint+provider already exists) and
`listings/take-a-hike/listing.yaml` referencing `designs/take-a-hike.png`.
Open the listing file afterwards and fill in `brief` (used by AI copy
generation in a later phase) and adjust prices/media to taste.

### By hand

Equivalent, written directly:

```yaml
# profiles/comfort-colors-1717.yaml
blueprint: Comfort Colors 1717
print_provider: Monster Digital
placeholder: front
print_area: { width: 4500, height: 5400 }
sizes: [S, M, L, XL, XXL, XXXL]
```

```yaml
# listings/take-a-hike/listing.yaml
profile: comfort-colors-1717
design: ../../designs/take-a-hike.png
colors: [black, blue-jean, ivory, moss]
brief: >
  Retro 70s sunset mountain scene. Design text reads exactly "TAKE A HIKE".
prices:
  S: 349 NOK
  M: 349 NOK
  L: 349 NOK
  XL: 359 NOK
  XXL: 369 NOK
  XXXL: 379 NOK
etsy:
  title: <generate>
  description: <generate>
  tags: <generate>
  materials: [cotton]
media:
  - { template: flat-lay-01, colour: black }
  - { template: flat-lay-01, colour: blue-jean }
  - { template: flat-lay-01, colour: ivory }
  - { template: flat-lay-01, colour: moss }
```

A few things worth knowing about `listing.yaml`:

- **`media` is what actually gets rendered.** Listing a colour in `colors`
  makes it sellable; it doesn't make it photographed. Only colours named in
  `media` produce a render. `media` entries either name `{template, colour}`
  (colour required for `colour-matrix`-kind templates, forbidden otherwise)
  or are a bare path to a shared asset under `common-media/` (a sizing
  chart, say). Etsy allows at most 10.
- **`design` can be a map**, not just a bare path, when you need separate
  light-ink/dark-ink artwork — `{on-light: ..., on-dark: ...}` — with an
  optional per-colour `artwork:` override on the listing. Full resolution
  order is in [docs/multi-placement-rendering.md](multi-placement-rendering.md).
- **`<generate>`** on `etsy.title`/`description`/`tags` marks them for the
  (not-yet-built) AI copy stage. Write real values now if you want to skip
  that later, or leave the placeholder.
- **Every price needs an explicit currency** matching `shop.yaml`'s
  `currency` — `349 NOK`, never a bare `349`.

### `exceptions.yaml` (optional)

If two of a garment's colour names would slugify to the same string (e.g.
two different greys), `new` fails and names the collision. Add an override at
the workspace root:

```yaml
# exceptions.yaml
"Heather Grey": heather-grey
"Ash Grey": ash-grey
```

Empty/absent is the common case — leave it out until you hit a collision.

## 7. Run `plan` and `apply`

```bash
uv run etsy-listings plan take-a-hike        # or --all for every listing
uv run etsy-listings apply take-a-hike       # runs whatever plan identified
```

`plan` does a three-way diff — desired config vs. last-applied vs. (in later
phases) live remote state — and prints what would happen without changing
anything:

```
take-a-hike

  + render (no previous render)

  1 to run, 0 to change, 0 drift warning(s)
```

`apply` runs it for real and writes `listings/<name>/state.lock.json`, which
records what was applied and a hash of the inputs that produced it. Re-run
`plan`/`apply` with nothing changed and you'll get "No changes." — that's the
idempotency guarantee this tool is built around, not a fluke of this
particular listing. Change a bounding box in the calibrator, or add a colour,
and `plan` will show exactly which render outputs are now stale.

`--all` runs every listing found under `listings/` and keeps going past a
single bad one (reporting failures at the end) rather than stopping the batch
— useful once you have more than one listing to manage.

## What's not here yet

Everything below is real, agreed design in [docs/prd.md](prd.md) and
[docs/implementation-plan.md](implementation-plan.md) — worth reading if
you're planning around where this is going — but none of it runs yet:

| Command | Will do |
|---|---|
| `auth` | Etsy OAuth (PKCE) and Anthropic credential setup |
| `catalog refresh` | Force-refresh the cached Printify catalog |
| `unlock <listing>` | Clear a Printify product stuck mid-publish |
| `status [<listing>]` | Run history from the SQLite recorder |
| `render` / `generate` | Force a single stage in isolation (today, `render` only runs as part of `apply`) |

`ui` itself will grow a dashboard, setup wizard and run runner in Phase 5 —
today it serves only the calibrator.

## Where things live, quick reference

```
your-workspace/
  shop.yaml              currency, Etsy shop defaults
  exceptions.yaml         colour-name -> slug overrides (optional)
  .env                    secrets — PRINTIFY_API_TOKEN etc., gitignore this
  designs/                your artwork PNGs
  mockup-templates/<name>/
    template.yaml         kind + bounding box(es) + shade/displace
    {colour}.png | scene.png
  profiles/<name>.yaml    garment definition, reused across listings
  listings/<name>/
    listing.yaml          prices, colours, media, Etsy copy
    state.lock.json        written by `apply` — what ran, input hashes
  .cache/                gitignored, fully derivable — safe to delete
    renders/<listing>/<template>/{colour|scene}.png
```

Never write secrets into this repository — they belong in the workspace's
`.env` and `.auth/`, both gitignored. See [docs/setup.md](setup.md) for what
has to exist in Printify/Etsy before Phase 2 can run against a real shop, and
[docs/architecture.md](architecture.md) for how the modules fit together.
