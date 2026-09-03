# Implementation Plan: Multi-Placement Scenes and Artwork Variants

Companion to [prd.md](prd.md) and [implementation-plan.md](implementation-plan.md).
This document covers one change to the Phase 1 renderer and calibrator: a single
mockup photograph may carry **more than one garment**, each needing its own
placement geometry and, potentially, a **different file of the design** — a dark
artwork on light shirts, a light artwork on dark ones.

It amends numbered decisions in both documents. Those amendments are listed at
the end and must land as their own commit, per CLAUDE.md.

---

## What breaks today

Three assumptions, each load-bearing, each wrong for a colour chart:

| Assumption | Where it lives | Why it fails |
|---|---|---|
| One template image = one garment = one quad | `TemplateConfig.warp`, `ColourOverride` | A colour chart is one photograph of eight flat-lay tees. |
| One template image = one colour, named by its filename | `Workspace.template_base_image()`, PRD 7a | `colour-chart.png` is not a colour. |
| One listing = one design file | `Listing.design: str`, `RenderStage.desired()` | Black ink on ivory and white ink on black are two files. |

Everything downstream of those — the render stage's hashing, the media manifest's
`mockup: <colour-slug>` reference, the calibrator's single quad editor — inherits
the same shape.

## Terminology

Fixed up front, because the obvious word is already taken. **Printify's "variant"
means one colour×size combination** and is used that way throughout `catalog/`
and the lockfile; nothing here may reuse it.

- **Scene** — one photograph in a template set. `black.png` is a scene. So is
  `colour-chart.png`. A template set is a directory of scenes plus one
  `template.yaml`.
- **Placement** — one garment within a scene: a warp quad, plus which garment
  colour that garment depicts. A single-garment scene has one placement.
- **Artwork key** — which file of the design set gets printed at a placement.
  Conventionally `on-light` and `on-dark`, naming *the garment the artwork is
  for*, not the ink colour, because "the black one" is ambiguous and "the one
  that goes on dark shirts" is not.

---

## New decisions

Numbered `A11`+ to continue the plan's architecture log, citable from code and
commits.

| # | Fork | Decision |
|---|---|---|
| A11 | Scene model | `template.yaml` carries a **default placement list** applying to every scene, plus a sparse `scenes:` map overriding it per scene. This is today's `warp` + `overrides:` generalised, so the common case — twelve recolours of one photograph — stays one quad for the whole set. |
| A12 | Placement identity | A placement names the **garment colour it depicts**, defaulting to the scene name. That is what makes a colour chart self-describing: the chart's placements *are* its colour list, so validation can compare them against the listing's colours. |
| A13 | Artwork selection | The colour → artwork mapping lives on the **profile** as a `colour_tone` table, auto-seeded by `new` from the catalog's colour hex values. The listing may override per colour; a placement may override for one photo. Listing wins, because it is the only file a human edits per design (PRD 8a). |
| A14 | What enters the hash | Only artwork keys **actually used by the rendered scenes** enter `RenderDesired`. Adding an unused `on-dark.png` to a design set must not re-render anything. |

---

## Data model

### `mockup-templates/{name}/template.yaml`

```yaml
placements:                      # the default: one placement, colour = scene name
  - warp:
      quad: [[144, 127], [346, 115], [355, 392], [134, 403]]
displace: { enabled: false, strength: 0.0 }
shade:    { enabled: true, opacity: 0.6, blend: soft-light }

scenes:                          # sparse; only scenes that differ from the default
  colour-chart:
    colour_coverage: exact
    placements:
      - { colour: black,     warp: { quad: [...] } }
      - { colour: ivory,     warp: { quad: [...] } }
      - { colour: blue-jean, warp: { quad: [...] } }
      - { colour: moss,      warp: { quad: [...] }, artwork: on-dark }
  moss:                          # this photo is framed differently
    placements:
      - warp: { quad: [...] }
```

New models in `render/config.py`:

```python
class Placement(BaseModel):          # frozen
    colour: str | None = None        # defaults to the scene name
    artwork: str | None = None       # rare per-photo override
    warp: WarpConfig
    displace: DisplaceConfig | None = None   # None => inherit the template default
    shade: ShadeConfig | None = None

class SceneConfig(BaseModel):        # frozen
    placements: list[Placement]
    colour_coverage: Literal["exact", "subset"] = "exact"

class TemplateConfig(BaseModel):     # frozen
    placements: list[Placement]
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()
    scenes: dict[str, SceneConfig] = {}

    def resolve(self, scene: str) -> ResolvedScene: ...
```

`ResolvedScene` is a frozen sequence of `(colour, artwork_key, RenderConfig)` in
placement order. `RenderConfig` is unchanged and stays the per-placement unit
whose `canonical_json()` is the hash — that is what keeps A7 intact.

`ColourOverride` disappears; `scenes:` replaces it.

### `profiles/{name}.yaml` — colour tones

```yaml
blueprint: Comfort Colors 1717
print_provider: Monster Digital
...
colour_tone:                     # written by `new`, hand-editable
  black: dark
  moss: dark
  ivory: light
  blue-jean: light
```

`new` seeds this from the catalog. Printify's blueprint variants carry hex
colour values; relative luminance (`0.2126R + 0.7152G + 0.0722B` over linearised
sRGB) at or above **0.5** classifies as `light`, below it as `dark`. Heathers
declaring two hex values are averaged. The threshold is a calibration constant
with a named test, not a magic number buried in a branch, and the table is
hand-editable precisely because mustard and heather grey sit near the line.

This costs no extra API traffic: `new` already fetches the variant set to
populate `sizes` and `print_area`.

### `listings/{name}/listing.yaml` — the design set

`design:` becomes polymorphic. The single-artwork case is untouched:

```yaml
design: ../../designs/take-a-hike.png
```

and the two-artwork case is a map keyed by artwork key:

```yaml
design:
  on-light: ../../designs/take-a-hike-dark-ink.png
  on-dark:  ../../designs/take-a-hike-light-ink.png
artwork:                         # optional per-colour override
  moss: on-dark
```

A bare path normalises to `{"default": path}`, and every colour resolves to
`default`.

### Artwork resolution, in order

For a placement in a scene, the artwork key is the first of:

1. `listing.artwork[colour]` — the human's explicit per-design decision.
2. `placement.artwork` — the template author's per-photo decision.
3. `on-{profile.colour_tone[colour]}`, if that key exists in the design map.
4. The sole key, if the design map has exactly one entry.

Otherwise it is a validation error naming the colour, the tone it resolved to,
and the keys the design map actually offers. **No silent fallback to an
arbitrary artwork** — a wrong-ink render is invisible on the very shirt it is
wrong for, which is the failure mode the PRD's "strict, never auto-fix" stance
(decision 17) exists to prevent.

---

## Renderer

`render/passes.py` is unchanged. Every pass is already per-layer and pure; a
scene with eight garments is eight layers over one base.

`render/pipeline.py` changes signature:

```python
@dataclass(frozen=True)
class Layer:
    design: RGBA
    cfg: RenderConfig

def render(
    template_base: RGB,
    layers: Sequence[Layer],
    *,
    height: FloatMap | None = None,
    luminance: FloatMap | None = None,
) -> Image.Image:
```

Each layer runs warp → displace → shade independently, then `export` folds them
over the base **in list order**. `export` grows a sequence form —
`export(base: RGB, print_layers: Sequence[RGBA]) -> Image.Image` — folding with
the same straight-alpha, float32, round-not-truncate arithmetic it uses today,
in one place, so the compositing-order determinism note keeps covering it.

**The single-layer path must stay byte-identical.** For `len(layers) == 1` the
fold reduces to today's expression, and a test asserts the existing
`tests/golden/e2e/goldens/*.png` are unchanged. Get this wrong and every
already-applied listing re-renders to different bytes, the output hash moves, and
every image re-uploads to Etsy — the two-hash-axes invariant working correctly
against a change that should have been a no-op.

Derived height and luminance maps are **per scene, not per placement** — they
come from the whole base photograph, so a chart with eight garments still
computes and caches exactly two maps. Placement-level `displace` / `shade`
overrides only change how each layer *samples* them.

**Cost.** N placements means N full-canvas warps. At chart sizes (a 4000px photo
with twelve garments) that is measurable but bounded, and it happens once per
render, not once per run. If it becomes a problem, the fix is warping into each
quad's integer bounding box and compositing at an offset — deferred, and gated on
a golden test proving bbox-warp output is bit-identical to full-canvas warp,
since it changes the homography's destination coordinates.

---

## Render stage

`engine/stages/render.py` moves from colours to scenes.

```python
@dataclass(frozen=True)
class RenderDesired:
    listing: str
    designs: tuple[tuple[str, str, str], ...]   # (artwork key, workspace-relative ref, hash)
    template_name: str
    template_hash: str
    scenes: tuple[str, ...]
    configs: dict[str, str]                     # scene -> canonical json of the ResolvedScene
```

`configs[scene]` serialises the ordered placements as
`[{colour, artwork, render_config}]`, so a reordered chart, a re-pointed artwork,
or a nudged quad all produce a real diff. Reordering placements without moving
them re-renders to identical bytes, and `outputs` then correctly declines to
re-upload. Per A14, `designs` carries only the keys the rendered scenes use.

**Which scenes render:**

- One scene per colour in `listing.colors`, as today — its single placement takes
  the scene's own colour.
- Plus any multi-placement scene named in `media`. Charts are expensive and
  optional; rendering one nobody references is waste.

Output paths keep their form: `.cache/renders/{listing}/{scene}.png`. For
single-garment scenes the scene name *is* the colour slug, so existing paths,
existing `mockup: black` references and existing lockfiles all keep working.

`apply()` loads each artwork **once** per run, reuses the array across every
placement referencing it, and makes one `render()` call per scene.

### Media validation moves

`Listing._validate` currently rejects `mockup: <x>` where `x` is not in `colors`.
The valid set now depends on the template, which `config/listing.py` cannot see
and should not learn about. **The check moves to the render stage's `desired()`**,
which already loads the profile and template:

- `mockup: <scene>` must name a scene the template defines.
- A scene that is a bare colour must be a colour the listing offers.

The cost is that the error surfaces at `plan` time rather than at config load.
That is the right side of the trade — `plan` is the gate the PRD designates, and
every other cross-file check (colour slugs against the catalog, prices against
sizes) already lives there. `tests/unit/test_listing.py`'s media case moves to
`tests/behaviour/test_render_stage.py` with it.

### Colour coverage

A chart showing twelve colours on a listing selling four is a misleading
photograph, and Etsy treats misleading photography as a listing problem. So
`colour_coverage` is per scene:

- **`exact`** (default) — the scene's placement colours must equal the listing's
  colours, or `plan` fails, naming both sides of the difference.
- **`subset`** — placements whose colour the listing does not offer are skipped,
  leaving that garment unprinted in the render, and `plan` reports each skip.

Default `exact` is deliberately the strict one: a silently-wrong product photo is
expensive and invisible, a failed plan is neither. It does mean a shop-wide
twelve-colour chart cannot serve a four-colour listing without opting into
`subset` — worth revisiting after the first real chart, and flagged as an open
question below rather than settled by guesswork.

---

## Calibrator

### API (`ui/api/schemas.py`, `ui/api/templates.py`)

```
GET  /api/templates                    scenes, with placement counts
GET  /api/templates/{name}/config      default placements + per-scene overrides
PUT  /api/templates/{name}/config      writes the new shape
POST /api/templates/{name}/preview     { scene, placements[], displace, shade, design }
```

`PreviewRequest` carries the whole placement list for one scene and renders all of
them through the real pipeline — the PRD's "the preview is the actual output, not
an approximation" is exactly what makes a multi-garment chart worth previewing at
all.

Each placement's `artwork` key resolves, in the calibrator only, to a **bundled
test design in the matching ink**: `scripts/generate_test_assets.py` gains a
second deterministic target so `on-light` and `on-dark` render visibly
differently and a mis-assigned artwork is obvious on screen. The grid/ruler target
gets the same treatment.

`_colours()` becomes `_scenes()`; `Workspace.template_base_image(template,
colour)` becomes `template_scene_image(template, scene)`. Same `_segment()` guard,
same security boundary — a rename, not a new path surface.

Regenerate the TypeScript client after the schema change; CI already fails on a
stale one.

### UI (`ui/frontend/src/`)

- **Placements panel** — list, add, duplicate, delete, select. Each row carries a
  colour slug field, an artwork dropdown, and an optional per-placement
  displace/shade override toggle.
- **QuadEditor** — draws every placement's quad, the selected one with live
  handles and the rest dimmed and click-to-select. Arrow keys nudge the selection.
- **Duplicate-and-offset** — one click copies the selected quad, offset by its own
  width. Calibrating twelve near-identical flat-lays by dragging four handles
  each, twelve times, is the difference between this feature being used and being
  avoided; this is the ergonomic core of the change, not a nicety.
- **Scene selector** labels multi-placement scenes with their placement count.

Auto-detecting garments in a chart photograph (segmentation, one quad proposed per
detected shirt) is the obvious next step and stays deferred alongside the
occlusion masking it shares machinery with — v2, as PRD 6e.

---

## Downstream: this is not only a mockup change

**Two artworks mean two print files.** If the shop sells a white-ink version on
black and a black-ink version on ivory, Printify must receive both, mapped to the
right colour×size variants. Printify's `print_areas[]` is a list of entries each
carrying `variant_ids` plus placeholders, so the API supports this natively: one
`print_areas` entry per group of variants sharing an artwork key.

The colour → artwork map defined here is precisely that grouping. It is the
argument for landing this work **now, as Phase 1b, before Phase 2 starts** rather
than after: doing it later means rewriting the `printify_product` stage's
`desired()` immediately after writing it.

Add to `docs/api-findings.md` at Phase 2 exit: whether a multi-entry `print_areas`
with disjoint `variant_ids` behaves as documented, and how it interacts with the
`{variants: true}` republish path.

---

## Back-compat

Existing `template.yaml` files — the three in `tests/fixtures/` and whatever is
calibrated in real workspaces — carry a top-level `warp:` and an `overrides:` map.
A `model_validator(mode="before")` on `TemplateConfig` normalises both:

```
warp: {...}                    ->  placements: [{ warp: {...} }]
overrides: {moss: {warp: X}}   ->  scenes: {moss: {placements: [{warp: X}]}}
```

Kept for one release, with a test pinning the translation. The alternative —
making everyone re-calibrate by hand — throws away real work to save a twenty-line
validator.

The template hash is computed over `template.yaml`'s **raw text**, so a legacy file
left untouched hashes as before and does not re-render. The first calibrator save
rewrites it in the new shape, the hash moves, the scene re-renders to identical
bytes, and `outputs` declines the re-upload. That is the two-hash-axes invariant
behaving exactly as designed, and it is worth asserting in a test.

*Optional, separable:* hash the **parsed canonical config** rather than the raw
text, so cosmetic YAML edits stop triggering re-renders. Correct, but a separate
change with its own risk surface — not bundled here.

---

## Work breakdown

Ordered so each step is independently reviewable and the suite stays green
throughout. Sizes are relative, not hours.

| # | Step | Touches | Tests | Size |
|---|---|---|---|---|
| 1 | `Placement` / `SceneConfig` / `TemplateConfig.resolve()`, legacy normalisation | `render/config.py` | `tests/unit/test_render_config.py`: defaults, scene overrides, inheritance, legacy shapes | M |
| 2 | Multi-layer `render()` and `export()` fold | `render/pipeline.py`, `render/passes.py` | existing goldens **unchanged**; new multi-placement fixture scene + golden | M |
| 3 | `colour_tone` on the profile; `new` seeds it from catalog hex | `config/profile.py`, `newcmd/logic.py` | luminance classification, incl. the 0.5 boundary and two-hex heathers | M |
| 4 | Polymorphic `design:`, `artwork:` overrides, resolution order | `config/listing.py` | `tests/unit/test_listing.py`: shorthand normalisation, precedence, unresolvable-key error | S |
| 5 | Render stage over scenes: artwork resolution, hashing, outputs, media check, coverage policy | `engine/stages/render.py`, `workspace/workspace.py` | `tests/behaviour/test_render_stage.py`: chart renders, hash stable across runs, `exact` failure, `subset` skip, artwork switch changes the hash, unused artwork does not | L |
| 6 | Calibrator API: schemas, preview with placements, config round trip; regenerate the TS client | `ui/api/*` | `tests/behaviour/test_calibrator_api.py` | M |
| 7 | Calibrator UI: placements panel, multi-quad editor, duplicate-and-offset, dual test designs | `ui/frontend/src/*`, `scripts/generate_test_assets.py` | `tests/browser/test_calibrator_browser.py`: add a placement, drag it, save, assert `template.yaml` | L |
| 8 | Document amendments (below) | `docs/*`, `CLAUDE.md` | — | S |

Optional follow-ups, explicitly out of scope here: the contrast tripwire (compare
an artwork's mean opaque luminance against the garment hex and warn on a
near-miss), bounding-box warp, and caching inactive layers during a calibrator
drag.

---

## Document amendments

Per CLAUDE.md these change numbered decisions, so they land as their own commit,
before the code depending on them.

**`docs/prd.md`**

- **7a is weakened** — "mockup filename = slugified Printify colour name" becomes
  "a *scene* filename is a slugified colour name **unless** `template.yaml`
  declares placements for it". This is the most consequential edit here: the
  convention that replaced a mapping table now has an exception, and it must be
  written down rather than discovered in `_scenes()`.
- **6d** (per-colour geometry) extends to per-scene placement lists.
- New **6f** — a scene may carry multiple placements, each naming the colour it
  depicts.
- New **6g** — a listing may carry multiple artworks keyed by garment tone; colour
  → tone lives on the profile, auto-seeded from catalog hex values.
- **25** (media references) — `mockup:` names a scene, which is a colour for
  single-garment scenes.
- The directory layout, the `listing.yaml` example and the validation list all
  gain their new forms.

**`docs/implementation-plan.md`** — A7 amended for the multi-layer pipeline;
A11–A14 appended; the render stage's row in the stage table updated.

**`docs/architecture.md`** and **CLAUDE.md** — the "mockup filename = colour"
invariant restated in its weakened form, plus the terminology note (scene /
placement / artwork key vs Printify variant) where the invariants live.

---

## Risks

1. **The single-layer byte-identity requirement** (step 2). If the fold changes
   rounding for `N == 1`, every existing listing silently re-uploads. Guarded by
   the unchanged goldens, and worth an explicit assertion rather than trusting the
   golden diff to be read.
2. **"Variant" collision.** Printify's colour×size variant and an artwork variant
   are different things in adjacent code. Mitigated by never using the word for
   artwork — reviewers should push back on any reintroduction.
3. **Calibrating twelve quads is tedious enough not to get done.** Mitigated by
   duplicate-and-offset and arrow-key nudge; if it still bites, segmentation-based
   auto-detection moves up from v2.
4. **`colour_coverage: exact` may be the wrong default** for a shop with one
   standard chart. Cheap to flip; see the open question below.
5. **Preview latency scales with placement count.** The existing ≤1200px preview
   budget absorbs a lot; if a twelve-garment chart drags badly, cache the inactive
   layers' composite for the duration of a drag.
6. **Printify multi-entry `print_areas` is unverified** against the real API. It is
   documented, not observed — Phase 2's job, recorded above.

## Open questions

1. **Coverage default.** `exact` (a chart must match the listing's colours) or
   `subset` (skip what is not offered, leaving that garment blank)? This plan
   assumes `exact`, which means a chart per colour set. If the intent is one
   standard shop-wide chart, `subset` is the right default and the plan should say
   so before step 5 is written.
2. **Legacy `template.yaml` normalisation** — keep the shim, or re-calibrate the
   handful of existing templates and delete twenty lines? The plan assumes the
   shim.
3. **Are multi-placement scenes only ever colour charts?** If size-comparison or
   folded/hanging composites are wanted too, placements may eventually need to
   carry a print-area or garment reference as well. Nothing here forecloses it,
   but it is worth knowing before the schema is published.
