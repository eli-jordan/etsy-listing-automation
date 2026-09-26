# Multi-Template Mockups: Kinds, Multi-Artwork, and the Calibrator

Companion to [prd.md](prd.md) and [implementation-plan.md](implementation-plan.md).
This document covers the change that let a listing use more than one mockup
template, and a design carry more than one artwork file (light-ink vs
dark-ink). It supersedes an earlier draft of the same name that modelled
templates as a single generic schema with a default placement plus sparse
per-scene overrides — that design was replaced before any code shipped
against it, in favour of the simpler, kind-based one documented here, which
*is* implemented.

## Two things this solves

- **A colour chart** — several garments in one photo, not one garment per
  photo.
- **Light-vs-dark artwork** — a design that needs a dark-ink file for light
  garments and a light-ink file for dark ones, not one file for every colour.

## Vocabulary

**Printify's "variant" already means one colour×size combination** and is
used that way throughout `catalog/` and the lockfile; nothing here reuses the
word for anything else.

- **Template kind** — `colour-matrix`, `multiple`, or `single`. A template is
  exactly one of these, never a mix.
- **Scene** — the photograph(s) inside a template. `colour-matrix` kind has
  one scene per colour (`{colour}.png`); `multiple`/`single` kind has exactly
  one scene, fixed filename `scene.png`.
- **Placement** — one garment within a `multiple`-kind scene: a colour and its
  own `bounding_box`.
- **Artwork key** — which file of a design's (possibly multi-file) artwork
  gets printed. Conventionally `on-light`/`on-dark`, naming the garment tone
  the ink is *for*.

## The three kinds

### `kind: colour-matrix` — one photo per colour, same design position in all

No per-colour override of any kind — every colour's photo places the design
at the identical `bounding_box`. A colour whose photo is actually framed
differently is a `single`-kind template instead; that's a deliberate
constraint, not a limitation to work around; it's what keeps a colour-matrix
template's entire content to two fields.

```yaml
# mockup-templates/flat-lay-01/template.yaml
kind: colour-matrix
bounding_box:
  - { x: 144.0, y: 126.72 }
  - { x: 345.6, y: 115.2 }
  - { x: 355.2, y: 391.68 }
  - { x: 134.4, y: 403.2 }
shade: { enabled: true, opacity: 0.6, blend: soft-light }
```

Scene images: `{colour-slug}.png` per colour (PRD 7a) — no `colours:` list in
the YAML, since the filenames present in the directory *are* the colour set.

### `kind: multiple` — several garments in one photo

```yaml
# mockup-templates/colour-chart-01/template.yaml
kind: multiple
colour_coverage: subset
shade: { enabled: true, opacity: 0.6, blend: soft-light }
placements:
  - { colour: black, bounding_box: [...] }
  - { colour: moss,  bounding_box: [...], artwork: on-dark }
```

`artwork:` on one placement is a rare, explicit override — that photo shows
that colour in a specific ink regardless of what artwork resolution would
otherwise pick. `shade`/`displace` are scene-level only — one photo, one
lighting pass; a placement needing different rendering treatment belongs in
its own template.

`colour_coverage` governs a mismatch between the chart's placement colours
and a listing's `colors:`: `exact` (default) fails `plan` if they don't match
exactly — right when a chart is meant to represent one specific listing.
`subset` skips placements the listing doesn't sell — right for one
shop-wide chart reused across listings that each sell a different subset of
the garment's colour range.

### `kind: single` — one photo, one garment

```yaml
# mockup-templates/lifestyle-01/template.yaml
kind: single
colour: black
bounding_box: [...]
```

`colour:` is optional context for artwork resolution, not an identifier —
there's only one photo.

Discriminated union, implemented in `render/config.py`
(`ColourMatrixTemplate | MultipleTemplate | SingleTemplate`, `Field(discriminator="kind")`,
loaded via `load_template_config()` — there's no wrapping model since the
file *is* one of the three shapes).

## Light-vs-dark artwork

**GarmentProfile** carries `colors`, human-classified by hand-editing the
generated garment profile file (not auto-seeded from Printify hex — this
codebase's `catalog/models.py` carries no hex field, and whether Printify's
real API exposes one at all is unverified). `new` never asks about it:

```yaml
colors:
  black: dark
  ivory: light
```

A freshly-generated garment profile always has `colors: {}`, so the common
single-artwork case costs nothing until a design actually needs the split.

**Listing**'s `design:` is polymorphic (`config/listing.py`): a bare path
normalises to `{"default": <path>}`; a map keys artwork files by tag:

```yaml
design:
  on-light: designs/take-a-hike-dark-ink.png
  on-dark: designs/take-a-hike-light-ink.png
artwork:
  moss: on-dark   # optional per-colour override
```

**Resolution order** (`engine/stages/placement.py::DesignPlacement.artwork_for`),
used by the render stage for its mockups and by `printify_product` for the
print file — one implementation, because the two must agree:

1. `listing.artwork[colour]` — wins even over a template's own override,
   deliberately: it's the thing a human is most likely to revisit per design.
2. The template/placement's own `artwork:` override.
3. `on-{profile.colors[colour]}`, if that key exists in the design map.
4. The design map's sole key, if it has exactly one entry — the common case
   needs none of the above.

Anything else raises `ArtworkResolutionError`, naming the colour, its tone
(if any), and the design map's actual keys.

## Multiple templates per listing, and how media references them

**There is no per-garment registry of templates.** An earlier version of this
design put `templates: list[str]` on the garment profile, on the reasoning that
mockup templates were a garment-level fact the same way `blueprint`/
`print_provider`/`sizes` are. That reasoning didn't hold up: those fields are
literal inputs to Printify's product-creation call — a template is not,
Printify never sees it, it's purely local and Etsy-facing. The registry also
got in the way of a real case: two listings sharing a garment wanting
different mockups, or a listing wanting a template no other listing on that
garment will ever reuse. `GarmentProfile` carries no listing-template
registry; a template lives purely in `mockup-templates/{name}/`, and any
listing may reference any of them. The one template name it does carry is
`preview_template` — a single `colour-matrix` used by the editor to judge
colours, never written into `media:` and never what decides which scenes
render (PRD 29, A13).

**Listing media always references a template explicitly** — there is no bare
`mockup: <colour>` shorthand:

```python
class TemplateMediaEntry(BaseModel):
    template: str
    colour: str | None = None   # required for colour-matrix kind, must be absent otherwise

MediaEntry = TemplateMediaEntry | str   # str = a shared asset path
```

```yaml
media:
  - { template: flat-lay-01, colour: black }
  - { template: flat-lay-01, colour: moss }
  - { template: colour-chart-01 }
  - common-media/comfort-colors-sizing-chart.png
```

`colour:` disambiguates which of several colour-matrix outputs; it's rejected
for `multiple`/`single` kind (exactly one output each — nothing to
disambiguate, so naming one would just be a second place to get it wrong).

**Rendering is driven purely by `media`** — a real behaviour change from
before this work: the render stage used to loop `listing.colors` and render
every one regardless of whether `media` showed it. Once addressing is always
explicit, that implicit rule had nothing left to justify it: `.cache/renders/`
output nothing in `media` references is pure waste, since nothing downstream
would ever upload it. `listing.colors` keeps driving which Printify variants
get sold (Phase 2); it no longer also drives which photos get rendered.

**Output paths are namespaced by template** —
`.cache/renders/{listing}/{template}/{colour}.png` for `colour-matrix` kind,
`.cache/renders/{listing}/{template}/scene.png` for `multiple`/`single`. This
is *not* what the original draft plan said (it assumed the old flat
`.cache/renders/{listing}/{colour}.png`) — that shape breaks the moment a
listing references two different `colour-matrix` templates that each happen
to have a "black" scene, which is exactly what became possible once
`mockup_template: str` stopped being a single field. Namespacing by template
closes that collision outright and mirrors each template's own scene-naming
convention, just one level down.

**A typo'd or not-yet-created template name fails loudly, naming it** —
`TemplateNotFoundError` checks that `mockup-templates/{template}/template.yaml`
actually exists on disk (at `plan` time, in the render stage's `desired()`)
before ever trying to read it. This replaced an earlier `TemplateNotDeclaredError`
that checked membership in the now-removed garment-profile registry instead; the
validation moved from "is this declared" to "does this exist," which is the
right question once there's no declaration step to skip.

## Uploading per-colour artwork to Printify (Phase 2 groundwork)

Not built yet — `printify_product` doesn't exist — but the artwork
resolution above already produces exactly what that stage will need:

- Group `listing.colors` by resolved artwork key.
- Each group uploads its artwork file once, gets one Printify image id.
- One `print_areas[]` entry per group: that group's `variant_ids` (colour ×
  every size) plus the uploaded image id.
- Single-artwork listings are the degenerate one-group case.

**Unverified against the real API**: whether a multi-entry `print_areas` with
disjoint `variant_ids` behaves as documented. Goes in `docs/api-findings.md`
at Phase 2 exit.

## Renderer

`render/passes.py` and `render/pipeline.py`'s `render()` (single layer) are
**untouched** — `colour-matrix` and `single` kinds call it exactly as before.
`multiple` kind uses a **new**, separate `render_scene()` (with `Layer` and
`export_many()`), not a generalisation of the existing single-layer path — so
there was zero regression risk to the pre-existing goldens or hash stability
from this change, verified by a dedicated test
(`test_export_many_with_one_layer_matches_export`) asserting the two paths
produce byte-identical output for one layer.

Derived height/luminance maps are per **scene** (the one base photo), shared
by every placement in a `multiple`-kind template — `displace`/`shade` are
scene-level, so this needed no change to `DerivedMapCache`.

## Calibrator

Kind is chosen at upload time (a segmented control), which decides the upload
widget (`colour-matrix`: several files, named by colour; `multiple`/`single`:
exactly one file, saved as `scene.png`) and picks the editor:

- **`ColourMatrixEditor`** — filmstrip, one live `QuadEditor`, shade/displace
  sliders, plus a **Gallery** panel (below).
- **`MultipleEditor`** — a `PlacementsPanel` (add/duplicate-and-offset/delete/
  select) driving a `QuadEditor` generalised to accept multiple boxes: the
  selected one gets live drag handles and arrow-key nudge, the rest render
  dimmed and click-to-select. Duplicate-and-offset (copy the selected box,
  shifted by its own width) is the ergonomic core of calibrating a
  many-garment chart without dragging four handles per garment.
- **`SingleEditor`** — one box, sliders, nothing else.

**Gallery** (`colour-matrix` kind only — `multiple`/`single` kind's one
output already *is* the full preview): live thumbnails, one per colour,
reusing the existing `/preview` endpoint with one parallel call per colour on
an 800ms debounce, separate from the main view's 200ms live-drag preview. No
new backend endpoint — this was strictly simpler than adding a batch preview
route.

Preview request bodies are a union
(`ColourMatrixPreviewRequest | MultiplePreviewRequest | SinglePreviewRequest`,
disambiguated by required fields alone — `colour` vs `placements` vs
neither); the endpoint additionally checks the parsed body's shape against
the target template's actual kind and rejects a mismatch with 400, rather
than silently rendering the wrong thing.

## Frontend test infrastructure

Added from nothing — the frontend had no test runner before this work.
**Vitest** (native to the existing Vite toolchain) + **React Testing
Library**, **v8 coverage provider**, **80%-branch floor**, deliberately
mirroring the Python side's gate exactly (`pyproject.toml`). Coverage
enforcement lives in `npm run test:coverage`, not the plain `npm run test`,
matching the Python side's "not in default addopts" reasoning — a
single-file run shouldn't fail a whole-suite gate. `scripts/check.sh` runs
both gates, skipping the frontend one cleanly (not a failure) if `npm` isn't
on `PATH`.

## Back-compat

None. This was a young, unreleased codebase at the time of the change — the
schema changed directly, and every fixture was updated in the same change
rather than carrying a transitional shape. The garment profile's mockup-template
field went through two shapes in quick succession: `mockup_template: str` →
`templates: list[str]` (a per-garment registry) → removed entirely once it
became clear the registry didn't earn its keep (see "Multiple templates per
listing" above). `warp.quad` → `bounding_box`, and the bare `mockup:` media
shorthand was removed, in the same spirit.

## Decision log

| Fork | Decision |
|---|---|
| Template kinds | Exactly one of `colour-matrix` / `multiple` / `single` per template, discriminated by `kind:`. No mixing, no generic placements-with-overrides model. |
| Per-colour override | Removed entirely for `colour-matrix` kind. A colour needing different geometry is a separate `single`-kind template instead. |
| Artwork tone source | Human-classified once per garment profile by hand-editing the generated file (`new` does not ask), not auto-seeded — Printify hex isn't modelled in this codebase and isn't confirmed to exist in the real API. |
| Media addressing | Always explicit `{template, colour?}` — no bare-colour shorthand, no "default template" concept. |
| Template ownership | No per-garment registry of listing templates — any listing may reference any template that exists in `mockup-templates/`. A template is purely local and Etsy-facing, unlike the fields (`blueprint`, `print_provider`, `sizes`) that are genuine Printify product-creation inputs and do belong on the garment profile. `preview_template` is the one name the garment profile does carry: a `colour-matrix` the editor uses to judge colours, not a `media:` default. `TemplateNotFoundError` checks the template actually exists on disk instead of checking registry membership. |
| What renders | Driven purely by `media` references, not by `listing.colors` membership (a real behaviour change from before this work). |
| Render output paths | Namespaced by template (`.cache/renders/{listing}/{template}/...`), not by colour alone — closes a collision a single-colour-matrix-template assumption used to hide. |
| `multiple`-kind rendering | New `render_scene()`/`export_many()`, not a generalisation of the existing single-layer `render()`/`export()` — zero regression risk to existing goldens, verified by an explicit byte-identity test. |
| Gallery preview | Reuses the existing per-colour `/preview` endpoint via parallel calls on a longer debounce; no new batch endpoint. |
| Frontend testing | Vitest + RTL + v8 coverage, 80% branch floor mirroring Python, wired into `scripts/check.sh`. |

## Open questions, carried forward

- **Printify `print_areas` multi-entry behaviour** — unverified; Phase 2's job.

Resolved since the first version of this section: whether a `single`-kind
template needed garment-profile-level ownership or could be listing-specific — moot
once the garment-profile-level registry was dropped for every kind, not just
`single`.
