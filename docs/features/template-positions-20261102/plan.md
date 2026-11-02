# Per-listing template positions implementation plan

Written 2026-11-02 from the [specification](spec.md), the approved
[interactions document](interactions.md) and a planning interview. Status: not
started. This plan owns the delivery sequence; the spec owns requirements and
the interactions document owns UI behaviour. Cite their sections rather than
restating them.

The clickable source is the **Template Positions** board:
[`src/ui/design/scenes/template-positions/`](../../../src/ui/design/scenes/template-positions/)
(frames 1–4) and
[`src/ui/design/scenes/template-positions-settings/`](../../../src/ui/design/scenes/template-positions-settings/)
(frames 5–6). Keep the frames fixture-driven; copy markup and styles into
production components. Screenshots for comparison are in
[`screenshots/`](screenshots/).

## Decisions from the planning interview

| Id | Decision |
|---|---|
| P1 | The Marigold spike is PR 1. Photo warp PRs build beside it while the seller reviews its report. PR 7 (Marigold support) launches only after the seller records sign-off below. **Outcome 2026-11-02:** option A failed; the seller chose option B (a direct fit per position, cached by geometry) for PR 7. |
| P2 | The spike runs on copies of real templates. The seller permitted copying template folders from the live workspace `C:\Users\Admin\iCloudDrive\naturally-inked-studio-workspace` (2026-11-02). Copy only `mockup-templates/<name>/` for the three templates named in PR 1, read-only, into a throwaway workspace under the delegate's scratch directory. Never write to, run commands in, or point `ETSY_LISTINGS_ROOT` at the live workspace. Commit no photo or composite to the repository. |
| P3 | The calibrator save warning is in scope as its own small PR (PR 6). |
| P4 | Split: spike; model and validation; Photo warp rendering; editor; Admin settings; calibrator warning; Marigold. |
| P5 | No new real-shop e2e cases. Positions change only local renders; the existing GitHub e2e workflow covers deploys. |

## Delivery sequence

Commit the spec, interactions document, screenshots, mockup scenes and this
plan as documentation before implementation; that commit is the stack base.
Record it and each PR link here when execution starts. Each PR is based on the
preceding tip.

| PR | Title | Difficulty | Branch | Link |
|---|---|---|---|---|
| 1 | Marigold padded-fit spike | hard | `feat/positions-1-spike` | — |
| 2 | Template positions model, limits and validation | standard | `feat/positions-2-model` | — |
| 3 | Render Photo warp scenes at listing positions | standard | `feat/positions-3-render` | — |
| 4 | Position mode in the Listing Images editor | hard | `feat/positions-4-editor` | — |
| 5 | Template rendering settings in Admin | standard | `feat/positions-5-settings` | — |
| 6 | Calibrator warning for positioned listings | mechanical | `feat/positions-6-calibrator` | — |
| 7 | Marigold positions, a fit per position (option B) | hard | `feat/positions-7-marigold` | — |
| 7b | Marigold upkeep: limits, recalibration and pruning | standard | `feat/positions-7b-marigold-upkeep` | — |

Spike sign-off: **2026-11-02, option A fail; proceed with option B** (seller's
decision after the PR 1 report). PR 7 implements option B.

Size: aim under about 1,500 changed lines per PR, excluding regenerated
OpenAPI/client files, goldens and lockfiles. A PR that cannot fit splits at a
seam the orchestrator agrees, not mid-feature.

### PR 1 — Marigold padded-fit spike

Answers the spec's *Spike gate*: can option A (fit maps once over a padded
quad, apply a listing position as a UV affine at composite time) match a
direct fit of the adjusted box, and how long does a refit from existing
preparation take?

Scope:

- A throwaway workspace built per P2 from three live templates, chosen for
  different failure risks: `cc1717-hanging-on-fence` (flat, hanging),
  `cc1717-man-with-tattoos-standing` (worn, folds), `cc1717-woman-with-oversize-fit`
  (drape near the print edge). All three are colour-matrix; the live workspace
  has no Marigold `multiple` template, so multiple placements are not covered
  and the report says so.
- A harness under `scripts/spike_template_positions.py` that, for each
  template and the spec's default limits (scale 0.80–1.10, offset ±10%, tilt
  ±15°):
  1. fits maps over the padded quad (template box grown to cover every allowed
     pose), reusing the template's existing preparation evidence, and times it;
  2. for a pose set covering the extremes (each limit alone, plus the four
     worst combined corners) renders the composite two ways: padded maps with
     a UV affine, and a direct fit of the adjusted box;
  3. reports per pose a pixel difference inside the print mask (mean and 99th
     percentile ΔE or RGB L2, the harness's choice, stated) and writes
     side-by-side PNGs.
- A report at `docs/research/template-positions-20261102/spike.md`: method,
  timings (padded fit, refit after a limits change, per-render composite),
  the difference table, observations on garment edges, and a recommendation.
  PNGs go on the `pr-screenshots` orphan branch under the PR's slug (per the
  finish brief), linked from the report, never committed to the branch.
- No production code changes. The harness may import production modules; any
  helper it needs lives in the script.

Exit when the harness runs end to end from a clean checkout plus the throwaway
workspace, the report is complete with numbers for all three templates, the
images are linked, and shared gates G2 and G7 pass. The seller's sign-off is
**not** an exit condition; it is recorded above and gates PR 7 only.

### PR 2 — Template positions model, limits and validation

Spec: *Listing file*, *Validation*, *Settings*, *Scope and decisions*.

Scope:

- `TemplatePositions` model in `core/config` (single/colour-matrix
  `bounding_box`; multiple `placements.<id>.bounding_box`), reusing
  `render.config.BoundingBox`, as `Listing.template_positions` (optional,
  absent by default).
- Pure pose maths in `core/render` (new module, e.g. `positions.py`):
  decompose a quad against a template box into scale, offset and tilt in the
  box's own frame through the template homography; similarity residual;
  compose a pose back into corners; nearest allowed pose (fit, then clamp)
  for *Fit within limits*. Property tests: compose ∘ decompose round-trips,
  non-axis-aligned (perspective) boxes, identity, limits.
- `Settings.template_positions` limits section with the spec's defaults and
  validation (min ≤ 1 ≤ max, ranges as the interactions table).
- `listing_validation` refusals 1–5 with the spec's messages; rule 5 refuses
  any position on a Marigold template until PR 7. Limits are passed in.
- API: `ListingDetail.template_positions`; the PATCH merge accepts it; the
  editor's `listingDocument.ts` includes it. Regenerate OpenAPI and the client.
- ADR-0058 *Allow per-listing template positions within limits* (mockup-only,
  absolute corners, similarity constraint, refuse rather than clamp) and a
  `CONTEXT.md` entry for **Template position**.

Exit when the refusals are proven through `listing_validation` and `plan`
(behaviour tests through the public plan path, not just unit), a positioned
listing round-trips through PATCH byte-preservingly (ADR-0055), the ADR is
indexed, and shared gates pass.

### PR 3 — Render Photo warp scenes at listing positions

Spec: *Rendering — Photo warp*; interactions *Adjusting* (preview of the saved
position).

Scope:

- `engine/stages/render.py` resolves each layer's effective box from the
  listing's positions (`_layer_specs`, `_resolve_layers`, `scene_layers`
  callers); `RenderConfig` carries it, so the lockfile hash changes only for
  affected scenes.
- `scene-preview` and the render warm-up use the saved position.
- Swatch sampling (`sample_swatch`) keeps sampling the template's own box,
  since it reads garment colour, not print; state this in a comment and test.

Exit when a golden proves a positioned scene renders at the listing box, a
behaviour test proves `plan` is a no-op for unchanged positions and re-renders
only the affected scenes after a change, previews match renders, and shared
gates pass.

### PR 4 — Position mode in the Listing Images editor

Interactions: *Entry and the Adjust position switch*, *Adjusting*, *Multiple
templates*, *Gallery badge*, *Position outside the limits*, *What the
production implementation must finish*. Frames 1–4.

Scope:

- Adjust position switch in the Images tab preview foot (template entries
  only); stage handles for move, uniform resize, tilt and arrow nudge, clamped
  to the workspace limits; ghost of the template box; Reset to template;
  saving once per gesture through the existing PATCH; drag overlay replaced
  by the real preview after save.
- A TypeScript twin of PR 2's pose maths for the stage (or an endpoint, if
  the builder prefers; record the choice). Its tests mirror PR 2's round-trip
  cases so the two cannot drift.
- Multiple templates: dimmed, labelled, click-to-select placements; per-
  placement Reset.
- Gallery badge on positioned tiles in `MediaReel`.
- Out-of-limits state: red box, note, Fit within limits (nearest allowed pose
  from PR 2), and the issues-banner action that removes a stale key.
- Limits read from workspace settings via the existing settings read.

Exit when vitest covers the pose maths and every interaction state, browser
tests drive move/resize/tilt/nudge/reset and the out-of-limits fix against a
real server, mockup-vs-app screenshots for frames 1–4 are in the PR, and
shared gates pass.

### PR 5 — Template rendering settings in Admin

Interactions: *Settings: Template rendering*. Frames 5–6.

Scope:

- Admin Settings subnavigation: AI (existing panels unchanged) and Template
  rendering.
- Template positions panel: four sliders, draft state, Discard, Review and
  save; the confirmation dialog with its focus and dismissal rules.
- A read that, for candidate limits, names the listings whose positions would
  fall outside and the Marigold templates whose evidence would need inference
  to cover the wider limits (empty until PR 7; the dialog omits that bullet
  and uses the plain "Save new limits?" wording when empty).
- Saving through the existing settings save (validated, revision-checked,
  source-preserving per ADR-0055).

Exit when vitest covers draft/discard/confirm/cancel/failure, a browser test
saves new limits and sees an out-of-range listing blocked, mockup-vs-app
screenshots for frames 5–6 are in the PR, and shared gates pass.

### PR 6 — Calibrator warning for positioned listings

Spec: *Recalibration*. Not prototyped; match the calibrator's existing save
feedback.

Scope: a read of which listings hold positions for a template (and which
placements), and a note in the calibrator's save flow naming them, shown
before and after saving geometry. The calibrator never edits listings.

Exit when a behaviour test proves the listing set (including placement-level
entries), the note renders in the calibrator, and shared gates pass.

### PR 7 — Marigold positions, a fit per position (option B)

Launches after the spike sign-off above and on a base containing PRs 3 and 5.
Spec: *Rendering — Marigold (option B: a fit per position)*, *Spike result*;
interactions *Marigold templates* and *Settings: Template rendering*. The
spike harness (`scripts/spike_template_positions.py`) and report are the
starting point: they already run padded-evidence inference and direct fits.

Scope:

- Evidence coverage: decide whether a template's preparation evidence covers
  its padded quad (template box grown to the current limits); when it does
  not, preparation runs inference for the padded quad, in the background, with
  the existing preparation scheduling and leases (ADR-0054).
- Per-position fits: a durable, content-addressed fit artifact keyed by
  template, placement, evidence identity, posed quad and inference settings;
  shared across listings; validated on load like published maps; pruned when
  unreferenced. Fits queue when a position saves.
- Render stage and scene-preview route: a positioned Marigold layer renders
  with its fit; `plan`/apply and the preview wait for a missing or running fit
  instead of using the template's maps. Render identity includes the fit
  digest.
- Limits changes: PR 5's candidate-limits read names the templates whose
  evidence would need inference; saving queues it. Recalibration re-checks
  coverage and rebuilds affected fits.
- Lift spec rule 5.

Exit when goldens prove a positioned Marigold scene matches a direct fit of
the posed quad, behaviour tests prove fit caching and sharing, the plan and
preview waits, inference queued on widening and not on narrowing, and pruning;
the settings dialog lists templates needing inference; and shared gates pass.
Real-model inference stays out of CI: tests use the existing fake predictor.

**Split (2026-11-02).** PR 7 outgrew the size budget and split at the
coverage seam the orchestrator agreed. PR 7 ships coverage jobs, per-position
fits, rendering and the position-save queue. PR 7b, stacked on it, carries the
deferred limits, recalibration and pruning items below; the exit conditions
above span both.

### PR 7b — Marigold upkeep: limits, recalibration and pruning

Based on PR 7's tip. Spec: *Marigold (option B)* (*Limits changes*,
*Recalibration*, pruning); interactions *Settings: Template rendering*.

Scope:

- PR 5's impact read fills `templates_needing_inference`: each template a
  listing positions whose evidence misses its padded quad under the candidate
  limits. Limits that widen no axis list nothing.
- The settings PATCH queues the same coverage inference after the response
  when the limits widen; narrowing queues nothing.
- A calibration save of a positioned template re-checks coverage and queues it
  when short; old fits are keyed by geometry, so they refit on demand.
- Pruning: fits no listing's current position produces against the template's
  current evidence are removed at startup and when scene warming drains,
  sparing fits being written, leased by a scene, or stored after the scan began.
- PR 5's dialog already renders the non-empty list; no UI change.

Deviation: only *positioned* templates are covered on widening (ADR-0058
amendment). Inference costs about two minutes per template, and a template no
listing has moved gets it when a position is first saved there.

Exit when behaviour tests prove the impact read and the queue on widening and
not on narrowing, the recalibration re-check, and pruning that removes only
unreferenced fits and spares leased ones; and shared gates pass.

## Shared gates

| Gate | Exit condition |
|---|---|
| G1 | Test-first for production behaviour (`tdd` skill). Fakes for workflows; no new real-shop e2e cases (P5). |
| G2 | `uv run poe check` from the repository root in Cygwin zsh. Python and frontend keep their 85% branch floors. Do not lower gates or exclude new code. |
| G3 | `npm run test:design` from `src/ui`. UI PRs build the SPA and run the relevant `pytest -m browser` cases. Mockup frames stay fixture-driven. |
| G4 | After API shape changes regenerate `docs/openapi.json` and the typed client in the same commit. Core stays free of server/CLI imports; Import Linter passes. |
| G5 | UI PRs compare against the frames and the interactions document: keyboard, focus, save/error states and both themes. |
| G6 | No local e2e. After green CI run the GitHub e2e workflow (`gh workflow run e2e --ref <branch>`), one run at a time, and record its URL; waived for PR 1 (no production code). Never use the live workspace except PR 1's read-only copy (P2). |
| G7 | Update affected docs (spec, architecture, guides, ADR citations, `CONTEXT.md`) in the owning PR. Record deviations here. |
