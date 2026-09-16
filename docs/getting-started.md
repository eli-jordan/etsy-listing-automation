# Getting started

A hands-on walkthrough of what's actually runnable today: install the tool,
try it against a ready-made workspace with zero setup, then build your own —
a workspace, a design, a mockup template, a garment profile and a listing — and run
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
garment profile, a listing, a design, and two mockup templates. You can point the CLI
straight at it and run a real `plan`/`apply` without creating anything of your
own:

```bash
uv run etsy-listings plan take-a-hike --root tests/fixtures/workspace
```

```
take-a-hike

  + render (no previous render)
      render flat-lay-01/black
        in   designs/take-a-hike.png
             mockup-templates/flat-lay-01/template.yaml
             mockup-templates/flat-lay-01/black.png
        out  .cache/renders/take-a-hike/flat-lay-01/black.png
      render flat-lay-01/blue-jean
        ...

  1 to run (4 actions), 0 to change, 0 drift warning(s)
```

That's a genuine three-way diff — it's telling you the `render` stage hasn't
run yet for this listing, and then exactly what running it would do: one action
per scene, the files each reads, the file each writes. Nothing is created until
you apply it:

```bash
uv run etsy-listings apply take-a-hike --root tests/fixtures/workspace
```

```
applying take-a-hike
  applying render
  ██ rendered flat-lay-01/black
  ██ rendered flat-lay-01/blue-jean
  ██ rendered flat-lay-01/ivory
  ██ rendered flat-lay-01/moss
```

Each block is the garment colour that scene actually rendered, sampled from the
mockup photo inside the print area — a quick check that a template is calibrated
onto the shirt and not onto the background. It appears only when the output is a
colour terminal; pipe the run to a file, or set `NO_COLOR`, and you get the plain
lines. If your terminal does render colour but the blocks never appear, set
`FORCE_COLOR=1` — a cygwin pty is a named pipe, and native-Windows Python cannot
tell it apart from a redirect. A `multiple`-kind scene prints one block per
garment in the photo.

Open the PNGs it wrote — `tests/fixtures/workspace/.cache/renders/take-a-hike/flat-lay-01/*.png`
— and you'll see the grid/ruler test design warped onto each garment colour.
Run `plan` again and it reports **no changes**: nothing about the inputs
changed, so nothing reruns. That idempotency is the whole point of the tool.

Now delete one of those PNGs and run `plan` again:

```
  + render (1 rendered file missing from the cache)
      ...
        out  .cache/renders/take-a-hike/flat-lay-01/black.png   (missing)
```

`plan` checks two separate things, and both have to hold for a run to be a
no-op: that nothing about the inputs changed, *and* that every file the last
apply produced is still on disk. The render cache is gitignored and fully
derivable, so deleting it is a supported thing to do — `apply` rebuilds it.

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
never point `--root` at the repo itself for real work. One command creates it:

```bash
uv run etsy-listings setup --root ~/etsy-listings
```

`setup` makes the directory skeleton, asks for your Printify token and
**verifies it against the API before storing it**, reads back which shop it
can reach and writes that id, then collects the currency and Etsy defaults and
writes `shop.yaml`. It is safe to re-run: every question arrives pre-filled
with what the file already says, so pressing enter through it changes nothing.

It stops before Etsy sign-in, which arrives with `auth` in Phase 3. A
workspace without that is complete for everything up to publishing.

The `shop.yaml` it writes looks like this, and hand-editing it is fine:

```yaml
printify:
  shop_name: My new store    # so the id below is checkable at a glance
  shop_id: 28819281          # discovered from your token, not typed
  preferred_print_provider: Monster Digital   # optional; used by `new`'s default
etsy:
  shop_name: TakeAHikeTees   # discovered too; the id is resolved from it
  shop_id: 12345678
  currency: NOK              # read from the Etsy shop
  who_made: i_did
  when_made: made_to_order
  is_supply: false
  renewal: manual
```

The Etsy fields are absent until `auth` has stored credentials `setup` can look
them up with — the tool asks for each by name at the point it actually needs
one, and none of them is ever typed as a number. Every price you write anywhere in this workspace
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
be **within 10% of your garment's print area** — a 4500×5400 print area wants a
design at least 4050×4860, and one at least 4500×5400 is better. Rendering never
upscales; anything smaller fails loudly, naming the required size. Printify's
print area varies by garment size, and `new` records the largest of them in the
garment profile, so meeting the number in `print_area` covers every size you sell.

Printify itself checks none of this — it will take a 120×140 file and print it —
so this gate is the only thing between a low-resolution export and a blurry
shirt.

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

A template is a folder you create yourself — `mockup-templates/<name>/` with
the photo(s) in it: one file for `multiple`/`single`, one per colour for
`colour-matrix`. The calibrator calibrates; it does not copy your files about.

Open `http://localhost:8000`. The server binds every interface, so the same
page is reachable from a phone or another machine on the network at
`http://<this-machine>:8000` — pass `--host 127.0.0.1` to keep it to loopback.
From there:

1. Pick the template from the rail and answer what kind it is. Uncalibrated
   ones sort to the top and say what they are missing.
2. Put the bounding box where the design should sit: drag inside a box to move
   it whole, its corner handles to reshape it, or nudge it with the arrow keys
   (hold shift for a bigger step). Use the shade/displace sliders to match the
   fabric's lighting and texture.
3. On a `multiple` chart, click the caption under a box to say which garment
   colour it depicts. Untick the outline toggle to see the render clean.
4. Toggle to the grid/ruler test design if you want warp errors to be more
   obvious than your real artwork makes them.
5. **Save** — this writes `mockup-templates/<name>/template.yaml`.

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

## 6. Add a garment profile and a listing

A **garment profile** (`garment-profiles/<name>.yaml`) is the garment definition — blueprint,
print provider, print area, sizes — reused by every listing built on it. A
**listing** (`listings/<name>/listing.yaml`) is everything commercial and
creative for one product: prices, colours, which template(s) render as its
photos, Etsy copy.

### The easy way: `new`

```bash
uv run etsy-listings new --root ~/etsy-listings
```

It asks which design first — `designs/*.png`, newest first, since the artwork
you just exported is nearly always the one you want. Name it instead
(`new take-a-hike --root ~/etsy-listings`) to skip that question, which is also
how you start a listing for artwork you have not drawn yet.

This reads Printify's catalog live, so it needs a token first — the catalog
endpoints are read-only but **not** public, and without one Printify answers
`401 Unauthorized`. Generate a personal access token with the `catalog.read`
scope at [printify.com/app/account/api](https://printify.com/app/account/api)
(docs/setup.md §1.3) and put it in the **workspace's** `.env`:

```
PRINTIFY_API_TOKEN=...
```

`.env` belongs to the workspace, not this repository, and should be gitignored.
Exporting `PRINTIFY_API_TOKEN` in your shell works too, and overrides the file.
The catalog is cached under `.cache/catalog/` with a one-day TTL, so a repeat
run of `new` may not call Printify at all.

With that in place, `new` interactively:

1. Offers garments (`--category` filters by blueprint category, default
   `tshirt`) across three columns — brand, model, title:

   ```
     1  ⭐ Gildan          5000   Unisex Heavy Cotton Tee
     2     Comfort Colors  1717   Unisex Garment-Dyed Heavy Weight Tee
     3     Gildan          2400   Unisex Long Sleeve Tee
     4     Gildan          18500  Unisex Pullover Hoodie
   ```

   Brand and model are how a blank is actually identified — “Gildan 18500” is
   what you look up — while Printify's titles bury it, since half a dozen
   brands sell a “Unisex Pullover Hoodie”. ⭐ means this workspace already has
   a garment profile for that garment, and those rows sort to the top — a shop reuses
   a handful of blueprints, so the one you used yesterday should not need
   finding.
2. Lists print providers for that garment — pick one
   (`preferred_print_provider` from `shop.yaml` sorts first if it's offered).
3. Resolves the provider's colours to slugs, flagging any collision against
   `exceptions.yaml` (see below).
4. Lists the calibrated mockup templates under `mockup-templates/` — pick one.
   A directory without a `template.yaml` isn't offered: it has no kind and no
   geometry yet, so choosing it would only fail later.
5. Asks a starting per-size price.

A garment needing different ink for light vs dark shirts isn't asked about —
edit the generated garment profile's `colors:` by hand (`{black: dark, ivory:
light}`) once you know you need it; see
[docs/multi-placement-rendering.md](multi-placement-rendering.md).

It writes `garment-profiles/<blueprint-slug>.yaml` (reusing it if a garment profile for that
blueprint+provider already exists) and
`listings/take-a-hike/listing.yaml` referencing `designs/take-a-hike.png`.
Open the listing file afterwards and fill in `brief` (used by AI copy
generation in a later phase) and adjust prices/media to taste.

**What lands in `media:` depends on the template you picked**, and `new` says
which case it took:

| Template kind | `media:` |
|---|---|
| `colour-matrix` | One entry per colour — capped at Etsy's **20-image limit** |
| `multiple`, `single` | Exactly one entry, no `colour` (one output each) |

The cap matters in practice: Comfort Colors 1717 at Monster Digital offers 33
colours, and Etsy accepts 20 images. `colors:` still lists all 33 — it decides
which Printify *variants sell*, which is a different axis from which photos
get rendered. The first 20 is an arbitrary starting point; edit `media:` to
choose which colours are worth a photo.

**Install `fzf` if you want to filter.** `new` uses it for the garment and
provider pickers whenever this machine has one, and it is the only front-end
that filters — full-screen, incremental, fuzzy, with space-separated words
AND-ed so `gil hood` finds the Gildan hoodie. Without it you get a plain
selector over the same rows in the same order: questionary's arrow-key list,
or under cygwin a numbered list (`n`/`p` page, a number picks). The reason for
that spread is in the next note.

> **Under cygwin, prompts fall back to a numbered list.** prompt_toolkit —
> which questionary is built on — only ever builds a Win32 console output on
> Windows, and a cygwin pty is a named pipe with no console screen buffer
> behind it, so it raises `NoConsoleScreenBufferError` before reading a key.
> `new` detects this and asks its questions with plain `input()` instead. The
> columns and the ⭐ marker still work; only filtering is lost, and cygwin's
> `fzf` package brings it back. A *Windows* `fzf.exe` under mintty generally
> needs `winpty` and is not worth the trouble.

> **Finding that `fzf` needs cygwin's help.** The tool is native-Windows
> Python, and cygwin's `fzf` package installs `/usr/bin/fzf` as a *shebang
> script* with no `.exe` — a file Windows can neither find on `PATH` nor
> execute. `shutil.which("fzf")` therefore says no while `ls | fzf` works
> perfectly in the same shell. So when the native lookup fails, `new` asks
> cygwin's own `sh` whether it has an `fzf` and runs it through that shell.
> One consequence worth knowing: cygwin's package is fzf **0.12.1**, the Ruby
> implementation, which rejects `--height`, so the picker always takes the
> whole screen rather than opening inline.

### By hand

Equivalent, written directly:

```yaml
# garment-profiles/comfort-colors-1717.yaml
blueprint:
  brand: Comfort Colors
  model: "1717"
  title: Unisex Garment-Dyed T-shirt
print_provider: Monster Digital
placeholder: front
print_area: { width: 4500, height: 5400 }
sizes: [S, M, L, XL, XXL, XXXL]
preview_template: flat-lay-01   # colour-matrix; editor colour preview only
```

`blueprint` is matched on **brand and model** — the pair you'd quote to order
blanks. `title` is there so the file reads as something rather than a part
number, and is ignored when resolving: Printify's titles are generic ("Unisex
Garment-Dyed T-shirt" is sold by several brands) and get rewritten, so one is
not an identifier (PRD 23). Case, surrounding spaces and the ® Printify puts
in brand names are all normalised away, so `Comfort Colors` matches its
`Comfort Colors®`.

```yaml
# listings/take-a-hike/listing.yaml
garment_profile: comfort-colors-1717
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
  garment-profiles/<name>.yaml    garment definition, reused across listings
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
