# Per-listing template positions

Status: agreed; Marigold positions (option B) implemented in PR 7. Started
2026-11-02 from a design interview.
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
| Renderers | Photo warp and Marigold. Marigold positions are rendered with a direct fit per position (option B, chosen after the spike). |
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
into the template box's own rectified frame through the template homography
(its unit square scaled to the box's mean side lengths, so a tilt is a rigid
rotation; ADR-0058 amendment), fit a similarity (uniform scale, translation, rotation), and check the residual and
the parts. It refuses, naming the listing and the key, when:

1. the box is not a similarity of the template box (corner residual above about
   1 photo pixel);
2. the scale, offset or rotation lies outside the current settings limits;
3. the key names a template that is not in the listing's `media:`;
4. the key names a placement ID the template does not have, or uses
   `placements:` on a template that is not `multiple` (or `bounding_box:` on one
   that is);
5. *(lifted by PR 7)* the template is Marigold and Marigold positions have not
   shipped yet.

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

The editor and `plan` enforce the same values. Widening them can require new
Marigold inference (below), so this section does not save on blur like the
rest of Admin: edits stay a draft, a note describes the effect, and
**Review and save…** opens a confirmation naming the templates that need inference and
any listings that fall outside. Discard reverts the draft.

## Rendering

### Photo warp

The listing box replaces the template box in the layer's `RenderConfig`. The
render config is already hashed into the lockfile, so only scenes whose
effective box changed re-render.

### Marigold (option B: a fit per position)

The spike (below) rejected option A, fitting each template's maps once over a
padded quad. Marigold positions instead get their **own maps**: a direct fit
of the posed quad, the same fit a calibrator geometry change already runs,
from preparation evidence that covers every allowed pose.

- **Evidence coverage.** A Marigold template's preparation evidence must cover
  the *padded quad*: the template box grown to the largest box the current
  limits allow. A template whose evidence does not cover it needs model
  inference once (spike: 85–131 s per template on the seller's GPU). The
  template's own published maps are unchanged.
- **Per-position fit.** A listing position on a Marigold template is rendered
  with maps fitted directly to its posed quad from that evidence (CPU only;
  spike: 0.9–5.8 s per fit). Fits are durable, content-addressed artifacts
  keyed by template, placement, evidence identity, posed quad and inference
  settings, so listings with identical positions share one, and any fit can be
  rebuilt from evidence. Fits no listing references are pruned with the cache.
- **When fits run.** Saving a position queues its fit in the background. The
  preview route and `plan`/apply wait for a missing or running fit rather than
  render with the template's own maps; the editor shows its normal loading
  treatment, never a progress card. The scene's render identity includes the
  fit's numerical digest, so the lockfile changes only for affected scenes.
- **Limits changes.** Narrowing the limits needs no new work. Widening them
  beyond a template's evidence coverage queues inference for that template in
  the background; existing fits stay valid because they are keyed by geometry.
  The settings confirmation names the templates that need it and says it runs
  the model once per template.
- **Recalibration.** A template geometry change re-checks evidence coverage
  for the new padded quad; positioned listings' fits are rebuilt against the
  template's new evidence when it changes.
- The 1024px interactive composite renders a posed box with its fit once ready
  and with the editor's drag overlay until then.
- Spec rule 5 (Marigold refused) is lifted (PR 7).
- Coverage inference is a preparation job that infers only the padded quad's
  crop and publishes no maps. PR 7 queues it when a position is saved on a
  template whose evidence falls short; `plan` refuses until it finishes.

### Spike result

The spike (`docs/research/template-positions-20261102/spike.md`, PR 1)
fitted three live templates over padded quads at the default limits. Option A
failed: on worn shirts the padded fit placed the artwork 23–60 px (99th
percentile) from a direct fit, against a 2–11 px difference between two
legitimate fits, and its evidence needed fresh inference anyway. On
2026-11-02 the seller chose option B (above). Multiple-placement Marigold
templates were not measured; none exists in the live workspace.

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
| `core/preparation/`, `render/material.py` | Evidence coverage of the padded quad, per-position fits cached by geometry, background inference when limits widen (Marigold, option B). |
| `application/prepared_previews.py`, server API | Previews render the saved position; regenerate the OpenAPI client for the new listing field. |
| `src/ui` Images tab | Position mode, with a TypeScript twin of the pose maths (`pages/editor/positions/`); `QuadEditor`/`quadGeometry` edit free quads and are not reused. |
| Calibrator save | List listings holding positions for the template. |
| Settings screen | Limits form with the inference warning. |

## Out of scope

- Changing Printify placement per listing.
- Per-colour positions.
- Free-form quads, skew or perspective edits.
- Copying positions into listing templates or batch-created listings.
- Rewriting listing positions when a template is recalibrated.
