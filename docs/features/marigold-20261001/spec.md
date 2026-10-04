# Marigold mockup integration product specification

Status: agreed, not implemented. Started 2026-10-01 after prototype evaluation
and a product design interview; YAML and HTTP contracts agreed through 2026-10-03.
This specification owns the intended integration requirements under the
[documentation authority rules](../../README.md#documentation-authority).
The [plan](plan.md) records technical design and delivery;
[ADR-0053](../../adr/0053-prepare-durable-mockup-maps-before-rendering.md) records
the preparation decision. The frozen PRD and original plan are historical context.

The template format changes outright. Backward-compatible loading is not required.
This spec does not claim that the prototype implements the production feature
or has passed its remaining quality gates.

## Outcome

Offer Marigold as an optional renderer on a mockup template. Prepare reusable
garment maps once from its fixed main photo, then render any artwork locally
without running models again. Keep placement editing responsive with a simple
overlay, and retain the existing full-quality preview and listing review flows.

The user found the prototype's full-resolution quality convincing, with depth
improving the moss example. That establishes confidence in the approach, not
universal accuracy or successful shared preparation across a whole colour pack.

## Scope and decisions

| Area | Agreed behaviour |
| --- | --- |
| Adoption | Explicit renderer chosen per template: Photo warp or Marigold. Photo warp preserves the current rendering mathematics. |
| Template kinds | Support colour-matrix, single and multiple, including every placement in a multiple scene. |
| Reference | Always use the fixed first/main photo. No reference picker and no automatic switch when browsing colours. |
| Colour reuse | Share the main photo's preparation and calibration across all colours. No per-colour preparations, corrections or placement overrides. |
| Incompatible photos | Use a separate template with that photo as its main image. |
| Editing | Fast straight artwork overlay; placement and mask controls, lighting and detail adjustments. |
| Depth | Enabled internally. No depth toggle required in the initial product UI. |
| Advanced geometry | Do not expose overlap patches or corrective anchors in this version. |
| Preparation | Explicit Prepare template action, background queue, progress, Cancel and Retry. |
| Readiness | Entire template ready only when all required placements have current valid maps. No template approval state. |
| Save | Automatically rebuild from cached predictions on the CPU where possible. New inference requires explicit preparation. |
| Persistence | Final maps are durable template assets. Raw predictions and rendered images are rebuildable cache. |
| Preview | Preserve current triggers: automatically render the first time; subsequent changes require the existing re-render button. |
| Recovery | Browser closure does not stop work. Unfinished preparation resumes on server startup. |

## Template setup and calibration

The template editor offers Photo warp and Marigold. Choosing Marigold does not
start inference. Show its preparation status and a Prepare template button.
Require `renderer.type` and nest that renderer's settings under `renderer.config`.
Photo warp uses `type: photo-warp`; Marigold uses `type: marigold`. The old
top-level rendering settings are replaced, with no legacy loading requirement.

Single and colour-matrix templates retain their top-level `bounding_box` and
have no placement ID. Multiple templates keep their placement list and give each
placement a stable ID. Mask paths are derived by Workspace, never stored in YAML.
Automatic and edited masks live under `./masks/`, with a placement-ID subdirectory
for multiple templates. Both masks survive cache cleanup and template copying.

Resolve the main photo using one stable, documented ordering of the template's
actual photos. The first photo in that ordering is the reference; navigating the
UI or reordering listing media never changes it. Show which photo is being used.
Single and multiple templates use their existing scene photo. If the resolved
main photo changes, preparation becomes stale. The ordering rule must be shared
by backend readers, not independently reconstructed by the browser.

All authoring uses the main photo. Colour-matrix templates keep one shared
placement and calibration. A multiple template has separate placement controls
and maps for each design placement on its one scene photo. Preparation may reuse
model evidence between placements when it covers them adequately; do not require
one identical crop to fit unrelated regions of the scene.

Lighting and detail adjustments remain scene-level for multiple templates,
consistent with existing rendering settings. Placement and mask authoring apply
to the selected placement.

Expose:

- Four placement corners and the existing placement editing interactions.
- Foreground exclusion and cloth restoration, with a proposed garment mask as
  the automatic starting point that can be corrected. Do not expose an automatic-
  mask enable/disable checkbox.
- Lighting choice, including estimated illumination and the photographic
  alternative demonstrated in the prototype.
- Detail/texture and restrained highlight/residual adjustments.
- Undo for brush strokes and Reset mask to restore the automatic starting mask,
  without changing placement, artwork or appearance settings.

Use the selected option D: Edit mask above the image; a floating brush dock at
its lower edge while editing. Name its buttons **Mask** and **Unmask**, with
brush size and a three-dot menu for Undo brush stroke and Reset mask beside them. Placement is the default when mask editing is inactive; no Move placement
tool is needed. Done or Escape returns to placement and hides the overlay.

The placement box positions the design. The mask hides portions of that design,
such as areas behind an object, in a gap or outside the garment. Mask adds hidden
regions; Unmask removes them. Foreground exclusion edits this same mask.

Show an unlabelled design-box icon and adjacent switch above the image (selected
option A). The switch shows or hides placement outlines and corner handles while
leaving artwork visible, including on multiple-placement scenes. Provide a
Show/Hide design box tooltip and an accessible Show design box label. This switch
is independent of mask editing and available while editing the mask too.

Show the effective mask clearly over the image, including automatic exclusions
and manual corrections. Use transparent red for excluded regions, labelled
**Red = hidden print**. Keep the placement box visible by default as a reference while
mask editing. Overlay visibility is separate from the mask's effect on rendering;
Edit mask automatically reveals it, and Done or Escape hides it. There is no
separate visibility checkbox or eye button. The selected dock is integrated into
[the full workflow mockups](ui-mockups/README.md). Earlier alternatives remain
archived for reference.

The [UI interaction companion](interactions.md) describes each control,
its differences from the current frontend, and the mock component and style references.

Use plain labels in Print realism: Lighting source, Light & shadow strength,
Fabric texture and Print shine. Give each field a clickable information icon
with an explanation of its effect and its low/high settings. Help closes on a
second click or Escape.

Advanced inference exposes custom numeric values only: **Inference steps**
(`num_inference_steps`, default 10) and **Ensemble size** (`ensemble_size`,
default 3), matching the prototype ensemble. Use these same readable names
for the corresponding information-card headings.
Do not show a quality-preset selector, processing resolution or seed. Resolution
and seed remain internal at the prototype settings. Provide information cards
explaining each exposed parameter and linking to the official Marigold
documentation, plus Reset to defaults for both values. Changed inference
settings require explicit template preparation. Use the selected option C dialog,
with fields on the left and information cards on the right. Title the dialog **Advanced Marigold Settings**. Put its **Advanced settings** button inside the Renderer section and show it only when Marigold is
selected. See the [integrated mockup](ui-mockups/inference-settings.png).

Keep model settings, solver tuning, overlap patch offsets and corrective anchors
out of the normal editor. A mask changes where artwork is visible; it does not
reconstruct hidden cloth or repair a material-coordinate discontinuity.

Keep the preview design selector beside the Calibrate and Preview tabs.

The edit canvas shows an immediate straight overlay while positioning or masking.
Label it as a placement preview so users understand why folds and lighting differ
from the finished render. Slider changes need not launch a full-quality render.

Save persists the calibration. When current raw predictions cover the edited
region, automatically rebuild affected maps on the CPU in background work.
Appearance-only settings that do not require geometry changes should avoid
unnecessary fitting. Otherwise mark the template as needing preparation and
enable Prepare template. Saving must not silently trigger GPU inference.

## Preparation and readiness

Prepare template snapshots the saved main photo, placements and calibration,
then queues the work. Run one model preparation at a time to bound GPU usage;
additional templates wait in the queue. CPU rebuilding also reports progress
without blocking editing or competing uncontrollably with model work.

Use one warm native Windows worker per workspace, with JSON-lines over
stdin/stdout and validated array files in cache. It exits after five idle minutes.
Run CPU rebuilding on one dedicated coordinator thread in the server process, allowed to overlap GPU work.
Assume one server per workspace. Different workspaces may contend for the GPU;
there is no global ownership lock.

Configure placements before preparation. Expand each placement's enclosing
rectangle by 40% on every side and clip to the photo. Reuse sufficiently covering
predictions after small edits; establish the smaller reuse margin through
validation. New inference always needs explicit preparation.

Report the current step, elapsed time, completed/total placements where relevant,
and actionable errors. Steps may include loading models, estimating normals,
illumination and depth, constructing maps, and saving assets. Do not imply an
accurate completion percentage or ETA unless it can actually be measured.

Readiness and job activity are related but distinct:

| Map state | Meaning and rendering behaviour |
| --- | --- |
| Needs preparation | Required maps are absent. Rendering is blocked. |
| Out of date | Maps exist but do not match the saved preparation inputs. Rendering is blocked. |
| Ready | Every required placement has valid current maps. Rendering is allowed. |

| Job state | Behaviour |
| --- | --- |
| Queued | Awaiting the worker; can be cancelled. |
| Preparing / rebuilding | Shows progress; can be cancelled. |
| Failed | Shows the failed step and reason; Retry is available. |
| Cancelled | Stops remaining work and retains any reusable completed evidence. |
| Completed | Publishes maps only if they match current saved inputs. |
| Superseded | Inputs changed; retain usable evidence but publish no obsolete maps. |

Cancellation finishes the active model call, retains its valid predictions and
stops remaining calls. Keep the worker warm. CPU cancellation occurs between
fitting phases. A cancelling state explains why the request has been accepted
but work has not yet stopped.

A failed or cancelled refresh must not destroy previously valid assets. Old maps
remain usable only when they still match the current configuration. They must
never be presented as current after a calibration change. Multiple-placement
templates become Ready only after every placement is current; rendering only a
subset of intended artwork is not permitted.

Publish a coherent map generation atomically. If inputs change during a job,
retain reusable evidence but do not publish its obsolete result as Ready. Avoid
duplicate jobs for the same inputs. Retry reuses valid completed work.

Queue state and progress checkpoints belong to the server and survive browser
closure. Persist pending work so server startup resumes queued and interrupted
jobs. An interrupted model call may restart that step; exact mid-inference
resumption is not required. A cancelled job stays cancelled after restart.
This is a preparation queue, not a change to the existing deploy-run lifecycle.

Persist jobs as atomic JSON records in the workspace cache. The status endpoint
and SSE stream report that record; reconnecting never starts work. Jobs retain
their input snapshots. After edits, skip obsolete downstream work and rebuild
the latest saved inputs from reusable predictions where possible.

## Shared preparation across colours

The product prepares the main photo only, rather than running models for every
colour. Its material coordinates, visibility/mask and estimated illumination are
shared with the other photos. Each render uses the selected colour's own blank
as its background. Do not multiply artwork by the reference garment's dye colour.
Cheap target-photo appearance processing is allowed, but must not introduce
per-colour model inference or manual overrides.

This requires sufficiently compatible framing, folds, foreground objects and
lighting. Matching dimensions alone does not prove compatibility. Reject
unsupported coordinate/dimension relationships with an actionable explanation;
do not invent an automatic registration feature in this version.

Nano Banana recolouring has changed garment shape in the current pack. A cached
pepper/ivory comparison found approximately 4.3 photo-pixels mean and 8.3 pixels
95th-percentile mapping difference inside the print area, with larger lighting
differences. Those comparisons are between model-derived maps, not physical
ground truth, and do not prove that sharing is visually acceptable.

Validate shared preparation at full resolution against independent per-photo
preparation as experimental evidence. The production feature still has no
per-colour exceptions. If sharing is visibly unsuitable, split those photos into
separate templates. Readiness means maps are current, not that every photo has
passed a human approval process. Listing review remains the quality review gate.

## Full-quality previews and listing rendering

Preserve the existing preview lifecycle: render automatically the first time,
then mark results out of date after changes and use the existing button to
re-render. Do not introduce automatic accurate renders after dragging or saving.
Use the existing red Re-render button for stale results rather than adding a
separate stale-render banner. Map readiness remains distinct from render freshness;
the button stays disabled while the maps required for rendering are unavailable.

During rendering show a loading/updating state. A previous result may remain
visible with a clear stale indicator; never imply it represents the new inputs.
Ignore late results that belong to a previous design, colour or configuration.
Apply this to full-quality template and listing previews without changing their
established triggers. The edit overlay does not count as a finished preview.

Full-quality preview, deployment preview and final output all use the accepted
maps and the same deterministic CPU renderer. A missing, stale or invalid map
blocks the scene with a clear Prepare template explanation. Neither listing
preview nor CLI plan/apply starts model inference or falls back silently to the
existing renderer. Switching renderers is an explicit template setting.

Retain the existing deployment contract: previews finish before Apply is enabled,
and matching full-quality preview bytes can be promoted to final output. Rendering
continues to be driven by referenced media, not by all listing colours.

## Asset lifecycle and deterministic rendering

Store final versioned maps with the template in the user workspace so copying or
syncing a complete template preserves its ability to render. Store raw predictions
and intermediate evidence in disposable cache. Removing that cache must not
invalidate Ready maps, but a subsequent calibration edit may require preparation
again if its raw evidence is unavailable.

Retain only the latest usable prediction set per template, covering every
required placement crop. Replace it only after the new set is complete and
validated. Delete superseded predictions once active jobs release them. Retain
valid partial evidence needed by an unfinished or retryable replacement.

Generated maps occupy immutable generation directories beneath the template.
Atomically switch the current manifest only when the whole required set matches
saved inputs. Each render holds one fixed generation; delete superseded
generations after active readers release them.

Brush history belongs in cache. Cache deletion removes historical stroke Undo,
but preserves the flattened edited mask and Reset to the saved automatic mask.
YAML contains neither mask details nor generated map bookkeeping.

Validate artifact schema, arrays, dimensions, finite values, ranges and identity
on load. Use safe non-pickled numerical storage. A partial write, mismatched file
or unsupported schema must produce an actionable readiness error.

| Input change | Consequence |
| --- | --- |
| Artwork or listing selection | New output; maps and raw predictions remain reusable. |
| Placement or mask | Saved maps need updating; CPU rebuild if suitable cached evidence exists. |
| Lighting/detail setting | New output identity; reuse evidence and geometry wherever valid. |
| Main-photo pixels or reference identity | Preparation required unless matching evidence already exists. |
| Added/removed/changed placement | Update required maps; Ready requires the full current placement set. |
| Other colour photo changes | That scene's output changes; reference preparation remains reusable, subject to compatibility checks. |
| Checkpoint/preprocessing changes | New evidence identity; explicit preparation is required. |
| Solver/artifact changes | Rebuild or prepare according to compatibility; never silently reinterpret unsupported maps. |

Do not invalidate existing templates simply because the installed software has
newer model defaults. Their recorded compatible preparation remains usable until
an explicit upgrade or an input change requires rebuilding.

Manage versioned runtimes and weights under `<home>/.etsy-listings/marigold` with
explicit setup/update commands. Preparation never silently installs them. Show
an informational notice when a newer inference engine is available for
preparation; compatible prepared maps remain usable.

Render-input identity includes concrete accepted map content, pixel-affecting
settings, artwork and the target blank. Exclude timestamps, absolute paths, job
states and inference provenance from hashes. Preserve the separate axes for
render-input changes and output-byte changes. Rendering passes remain pure.

Model inference is an authoring dependency. A machine with prepared templates
must render without CUDA, model weights or importing PyTorch. Preparation runs
on native Windows in an isolated worker environment, driven through Cygwin.
Do not require WSL or change production OpenCV/Pillow pins. Missing GPU/worker
capability should prevent preparation with a clear explanation, while existing
rendering and use of prepared maps continue to work.

## Performance context

These are prototype measurements, not service-level promises. See the
[trial](../../research/marigold-20261001/mockup-marigold-trial.md) and [CPU report](../../research/marigold-20261001/marigold-performance.json).
GPU: RTX 3070 8 GB. CPU: Intel i9-10850K. Artwork: 4200 Ã— 4800.

| Operation | Observed time |
| --- | --- |
| Warm normals + lighting + depth inference | About 10â€“12 seconds with defaults; 20â€“26 seconds with the trial ensemble. |
| Initial ensemble GPU calls | About 71 seconds combined, plus about 11 seconds model loading; excludes downloads. |
| CPU maps from cached predictions | About 5â€“7 seconds at 1254 square; 9â€“11 seconds at 2048 square. |
| Save compressed map | About 1.5â€“3 seconds. |
| Load accepted map | About 0.3â€“1.1 seconds. |
| Depth-enabled render at 1254 square | About 2.7â€“3.9 seconds CPU; 3.2â€“4.5 seconds including PNG encoding. |
| Depth-enabled render at 2048 square | About 4.4â€“6 seconds CPU; 6â€“8 seconds including PNG encoding. |
| Map size | About 19â€“28 MiB per tested preparation. |

The first complete preparation is estimated around 1.5â€“2 minutes with cached
weights, not a measured cold end-to-end guarantee. A warm complete preparation
is estimated around 30â€“40 seconds. Multiple placements can add fitting, baking,
storage and possibly inference work; the single-placement measurements must not
be advertised as a bound for those scenes. Models download separately on first
setup. GPU use is limited to preparation, not rendering new artwork.

Do not block the edit canvas for these operations. Measure integration latency
and concurrency on the supported Windows setup. Reusing artwork mipmaps and
derived sampling fields is a possible optimization, not an achieved speedup.

## Amendments and preserved constraints

This feature amends the earlier [multi-placement requirements](../multi-placement-rendering-20260903/spec.md)
for renderer selection, configuration, masks and preparation. The three kinds,
explicit listing media and artwork selection remain. The amendments are approved
but unimplemented; earlier documents describe shipped Photo warp behaviour where
this feature does not revise it.

| Decision | Marigold contract |
| --- | --- |
| ADR-0012 | Pure composition also accepts durable maps. Editing may use an approximate overlay; full-quality preview and final output share rendering. Photo warp pixels stay unchanged. |
| ADR-0014 | Keep the kind union. Require renderer type/config, with explicit IDs only for multiple placements. Replace the old YAML format. |
| ADR-0013 / ADR-0046 | Workspace owns paths and assets. Derive mask locations without YAML references. |
| ADR-0008 / ADR-0039 / ADR-0040 | Include accepted map content in render identity, exclude volatile provenance and preserve preview promotion. |
| ADR-0041 / ADR-0053 | Deploy lifecycle stays unchanged. Preparation has its own durable, cancellable queue and restart policy. |
| ADR-0052 | Core owns calibration and preparation; server owns HTTP/SSE and host lifecycle; CLI uses core directly. |

Foreground masks and durable maps belong to this feature. Missing or stale maps
block rendering, and plan/apply never starts inference. Use Workspace for safe
paths, the engine for diffs/runs and shared validation for refusals. Do not add
UI-only readiness rules.

## Acceptance criteria

1. Templates converted to the new Photo warp configuration retain unchanged
   output bytes. The old YAML format does not need to remain loadable.
2. All three kinds support Marigold. Every multiple-scene placement renders the
   correct artwork; failed preparation never produces a partially printed scene.
3. A colour pack prepares only its main photo, shares calibration and needs no
   per-colour inference. No exception controls appear in the UI.
4. Placement editing stays responsive using the overlay; full-quality previews
   preserve initial automatic rendering and explicit rendering after changes.
5. Save rebuilds from cached predictions where possible, never silently starts
   inference, and never marks obsolete job results Ready.
6. Queue progress, Cancel, Retry, browser reconnection and server restart work.
   Completed work is reusable and cancelled jobs do not restart themselves.
7. Maps survive cache deletion and complete-template copying. Prepared rendering
   works without GPU dependencies; map load/render roundtrips are deterministic.
8. Missing/stale/invalid maps yield consistent actionable blocks in UI and CLI,
   with no silent fallback, template approval flag or implicit inference.
9. Full-resolution shared-map comparisons include representative light/dark
   colours, changed folds, foreground edges, and all multiple placements. Use
   opaque white, saturated art, fine text, transparent edges and the real design.
   Inspect geometry, shadows, masks and edges separately. Record failures and
   split incompatible photos into separate templates.
10. Add meaningful checks for artifact validation, invalidation/hash behaviour,
    queue recovery/races, multi-placement completeness, CPU-only use and browser
    editingâ†’prepareâ†’preview. Preserve production golden checks and pinned imaging
    dependencies. Measure performance independently from visual quality.

## Non-goals and remaining validation

No automatic geometry alignment between colour photos, per-colour exceptions,
reference picker, template approval workflow, exposed overlap/anchor tools,
cloud inference, WSL setup or universal recovery of hidden cloth.

Shared full-preparation quality and multiple-placement support are release gates,
not demonstrated capabilities of the current prototype. The prototype currently
prepares individual photos and uses only the first placement when given a
multiple scene. Its photo-hash validation must not simply be disabled to implement
reuse: production artifacts need an explicit main-photo/target-photo contract.

The [technical design](plan.md) specifies storage names,
queue persistence, HTTP contracts and module interfaces. It must satisfy the
behaviour here. Crop reuse margins, RAM budgets and responsiveness remain
implementation measurements. Build the full integration before quality review;
shared-colour and multiple-placement quality remain release gates.
