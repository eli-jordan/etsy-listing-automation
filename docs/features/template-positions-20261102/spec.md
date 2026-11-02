# Per-listing template positions

Status: agreed, not implemented. Started 2026-11-02 from a design interview.
This specification owns the requirements under the
[documentation authority rules](../../README.md#documentation-authority).
The [interactions document](interactions.md) records UI behaviour and maps it to the
Marver prototype in `src/ui/design/scenes/template-positions/` and
`template-positions-settings/`. The [plan](plan.md) owns delivery.

## Outcome

A mockup template's bounding box is calibrated once, for every listing that uses
it. Some designs look better on a particular scene slightly smaller, higher or
tilted. A listing may now record its own position for a template: an absolute
bounding box in the template photo's pixels, constrained to stay close to the
template's box. Rendering, the editor preview and the lockfile use the
listing's box wherever one is recorded.

The position changes the mockup only. Printify placement stays fixed
(centred, scale 1, filling the print area), so the limits exist to keep the
photo an honest picture of the shirt the buyer receives.

## Scope and decisions

| Area | Agreed behaviour |
| --- | --- |
| Granularity | One position per listing per template. A `colour-matrix` template shares it across every colour. A `multiple` template takes one per placement ID. |
| Representation | Absolute four-corner `bounding_box` in photo pixels, the same schema as `template.yaml`. Not a relative scale/offset. |
| Allowed shape | The template box under a uniform scale, an offset and a rotation, applied in the box's own (pre-homography) frame. No skew, non-uniform stretch or perspective change. |
| Limits | Scale, offset and rotation, read from settings. Defaults: scale 0.80–1.10, offset ±10% of box width and height, rotation ±15° about the box centre. |
| Out of range | `plan` refuses. No clamping, no grandfathering: narrowing the limits makes existing out-of-range listings fail until edited. |
| Printify | Unchanged. Positions are mockup-only. |
| Listing templates and batches | Never carry positions. New listings start from the template boxes. |
| Renderers | Photo warp and Marigold. Marigold depends on the padded-fit spike below; if it fails, Marigold templates refuse positions. |
| Editing | Direct manipulation on the Images tab preview pane. |

## Listing file

A new top-level key, `template_positions:`, mirrors `template.yaml`:

```yaml
template_positions:
  front-flatlay:
    bounding_box:
      - {x: 412, y: 380}
      - {x: 1210, y: 380}
      - {x: 1210, y: 1340}
      - {x: 412, y: 1340}
  family-chart:
    placements:
      left-shirt:
        bounding_box: [...]
```

A `single` or `colour-matrix` entry holds `bounding_box`; a `multiple` entry
holds `placements`, keyed by placement ID. A template with no entry renders
with its own box. Resetting a position in the editor removes the entry; it does
not write a copy of the template box. Corners are ordered top-left, top-right,
bottom-right, bottom-left, as in `template.yaml`.

The key lives in `listing.yaml`, so rename, delete and move already cover it
through `listing_documents`.

## Validation

`plan` decomposes each stored box against the current template box: map both
into the template box's own unit frame through the template homography, fit a
similarity (uniform scale, translation, rotation), and check the residual and
the parts. It refuses, naming the listing and the key, when:

1. the box is not a similarity of the template box (corner residual above about
   1 photo pixel);
2. the scale, offset or rotation lies outside the current settings limits;
3. the key names a template that is not in the listing's `media:`;
4. the key names a placement ID the template does not have, or uses
   `placements:` on a template that is not `multiple` (or `bounding_box:` on one
   that is);
5. the template is Marigold and the spike has not shipped Marigold support.

Example messages:

- `frog-tee: template_positions.front-flatlay scales the design to 1.18; the limit is 0.80–1.10`
- `frog-tee: template_positions.family-chart.placements.left-shirt names a placement that no longer exists`

Validation stays pure: the limits are passed in, as other settings-driven
checks are.

### Recalibration

Listing boxes are absolute, so recalibrating a template box does not move them.
The next `plan` re-checks them against the new box and refuses any that now
fall outside the limits. Saving a template in the calibrator lists the listings
holding positions for it, so the user sees which ones a change may break. The
calibrator never edits listings.

## Settings

A new settings section holds the limits. In Admin, Settings splits into two
subsections the way Shop already does: **AI** (the existing settings) and
**Template rendering** (these limits). The file shape is:

```yaml
template_positions:
  scale: {min: 0.80, max: 1.10}
  offset: 0.10        # fraction of box width/height, each axis
  rotation: 15        # degrees either way
```

The editor and `plan` enforce the same values. Changing them re-prepares
Marigold templates (below), so this section does not save on blur like the
rest of Admin: edits stay a draft, a note describes the effect, and
**Review and save…** opens a confirmation naming the templates refitted and
any listings that fall outside. Discard reverts the draft.

## Rendering

### Photo warp

The listing box replaces the template box in the layer's `RenderConfig`. The
render config is already hashed into the lockfile, so only scenes whose
effective box changed re-render.

### Marigold (option A)

Prepared maps store the artwork UV for each photo pixel (0 and 1 are the
artwork edges), with zero visibility outside the quad. Option A fits each
template's maps once over a **padded quad**: the template box grown to cover the
largest box the current limits allow. A listing position becomes an affine
transform on UV at composite time, and visibility is recomputed from the
transformed UV. No per-listing preparation runs.

- `PlacementInput.quad` records the padded quad, so adopting this re-prepares
  every Marigold template once.
- Padding follows the settings in both directions. Saving new limits refits
  every Marigold template's maps in the background from its existing
  preparation (the CPU rebuild a placement change already triggers; no model
  inference). This is expected to be fast; the spike measures it. The
  settings screen confirms before saving and names the templates affected.
- The editor shows no progress for the refit. If `plan` runs before a
  template's refit finishes, it waits for it rather than rendering against
  maps fitted for the old limits.
- The 1024px interactive composite and `_check_prepared_geometry` apply the
  same UV transform.

### Spike gate

Before any Marigold work, a spike fits real templates over padded quads at the
default limits, times the refit from existing preparation, and compares composites at the limit extremes against a direct
fit of the adjusted box. Padding that runs off the flat front of a garment is
the expected failure. If quality does not hold, Marigold templates refuse
positions (validation rule 5) and the padding and re-prepare work is not built.
There is no per-listing refit fallback.

## Editor

The Images tab preview foot gains an **Adjust position** switch (the app's
own switch control) for the selected template entry:

- Switch on: handles appear on the stage. Drag inside the box to move, pull a
  corner to resize, drag the round handle above the box to tilt; arrow keys
  nudge, Shift for larger steps.
- The template's own box shows as a dashed ghost outline.
- There is no readout of scale, offset or tilt. The handles simply stop at
  the limits.
- **Reset to template** (a text link) removes the listing's entry.
- No Done or Cancel: the position saves like every other editor field. Switch
  off to leave.
- For `colour-matrix` entries, the note line says the position applies to
  every colour.
- For `multiple` entries, the other placements render dimmed with their IDs;
  clicking one selects it. Reset names the selected placement.
- A stored position outside the limits shows a red box, a note and a
  **Fit within limits** action beside Reset.
- During a drag the stage draws a flat overlay at the draft position; the
  real composite from the existing scene-preview route replaces it once the
  position saves on release (see [interactions](interactions.md#adjusting)).

Mockups: a clickable prototype in `src/ui/design/scenes/template-positions/`
and `template-positions-settings/` (round 3). Earlier rounds are archived as
`template-positions-v1` and `-v2`.

## Impact

| Area | Change |
| --- | --- |
| `core/render/config.py` | Similarity decomposition and limit check; `scene_layers`/`scene_boxes` accept per-listing boxes. |
| `core/config/listing.py`, `listing_validation.py` | New field and refusals 1–5. |
| `core/config/settings.py` | Limits section. |
| `engine/stages/render.py` | Resolve the effective box per layer. |
| `core/preparation/`, `render/material.py` | Padded fit, UV affine, staleness on settings change, background re-prepare (Marigold, after the spike). |
| `application/prepared_previews.py`, server API | Previews render the saved position; regenerate the OpenAPI client for the new listing field. |
| `src/ui` Images tab | Position mode, reusing `QuadEditor`/`quadGeometry`. |
| Calibrator save | List listings holding positions for the template. |
| Settings screen | Limits form with the re-prepare warning. |

## Out of scope

- Changing Printify placement per listing.
- Per-colour positions.
- Free-form quads, skew or perspective edits.
- Copying positions into listing templates or batch-created listings.
- Rewriting listing positions when a template is recalibrated.
