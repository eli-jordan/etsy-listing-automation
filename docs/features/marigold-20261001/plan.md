# Marigold implementation plan and technical design

Written 2026-10-03 from the agreed architecture and subsequent YAML/API review.
This is a production design, not a claim that the integration is implemented.
The [product spec](spec.md) defines behaviour; the
[interaction companion](interactions.md) defines the editor flow.
Status: approved design, not implemented. The feature began on 2026-10-01.
Current authority follows the [documentation rules](../../README.md#documentation-authority).
[ADR-0053](../../adr/0053-prepare-durable-mockup-maps-before-rendering.md) records
the preparation decision. The frozen PRD and original plan are historical context.
Delivery PR links will be added as this plan ships.

## Purpose

Prepare garment maps from a template's main photo on native Windows. Save those
maps with the template. Rendering new artwork then needs only the CPU renderer,
with no PyTorch import, model installation or GPU. The same accepted maps feed
template preview, listing preview, deployment preview and final images.

The current renderer is named **Photo warp**, serialized as `photo-warp`. It
perspective-warps artwork into a quad, optionally displaces it using gradients
of blurred photo luminance, applies photo-derived shading and composites the
result. Its numerical output must remain unchanged.

The template format changes outright. There is no legacy parser, implicit
renderer default or support for top-level `shade` and `displace`. Convert repo
fixtures and document the new format with the implementation. Do not silently
rewrite external user workspaces.

## Template configuration

Keep `kind` as the existing three-way discriminator. Add a required `renderer`
object, discriminated by `type`. Its `config` is specific to that renderer.
Reject unknown fields rather than silently dropping settings from the old format.

Single and colour-matrix templates have one implicit placement. Only multiple
templates store placement IDs. Geometry remains outside renderer configuration
because both renderers use it.

```yaml
kind: colour-matrix
bounding_box:
  - {x: 420, y: 360}
  - {x: 920, y: 350}
  - {x: 950, y: 1080}
  - {x: 400, y: 1090}
renderer:
  type: marigold
  config:
    inference:
      num_inference_steps: 10
      ensemble_size: 3
    appearance:
      lighting_source: estimated
      lighting_strength: 1.0
      fabric_texture: 0.25
      print_shine: 0.0
```

Single templates use the same shape with `kind: single` and the existing optional
`colour` and `artwork`. Multiple templates retain `colour_coverage` and the
existing artwork override per placement:

```yaml
kind: multiple
colour_coverage: exact
placements:
  - id: left-shirt
    colour: Pepper
    bounding_box:
      - {x: 100, y: 200}
      - {x: 450, y: 200}
      - {x: 450, y: 650}
      - {x: 100, y: 650}
  - id: right-shirt
    colour: Ivory
    bounding_box:
      - {x: 600, y: 200}
      - {x: 950, y: 200}
      - {x: 950, y: 650}
      - {x: 600, y: 650}
renderer:
  type: marigold
  config:
    inference:
      num_inference_steps: 10
      ensemble_size: 3
```

Omitted nested settings take defaults. `renderer` and `renderer.type` are required;
`config: {}` is valid. The examples' geometry is illustrative. Appearance defaults
use the prototype's texture amount of 0.25 and residual amount of zero, with
estimated lighting at full strength. Earlier review examples used illustrative
values of 0.35 and 0.10; those did not establish defaults.

Photo warp configuration is:

```yaml
renderer:
  type: photo-warp
  config:
    displace:
      enabled: false
      strength: 0.0
    shade:
      enabled: true
      opacity: 0.6
      blend: soft-light
```

Placement IDs are unique, non-empty safe path segments. Generate them when adding
a multiple placement; never derive them from its array position or colour.
Moving, recolouring and reordering preserve IDs. Removing an ID and adding a new
one creates a new placement. Internal contracts represent the implicit placement
with `None`, not a fabricated ID that leaks into YAML or HTTP requests.

Marigold strength fields are finite floats in `[0, 1]`; lighting source is
`estimated | photo`. Inference values are positive integers. The mock's bounds
of 50 steps and 10 ensemble members are not validated model limits. Establish
and publish operational upper bounds during runtime validation before release.
Depth remains enabled. Processing resolution 768 and seed 2026 are internal
engine settings, taken from the prototype.

Switching renderer changes only the active configuration. Keep the last saved
inactive configuration in a template-owned `renderer-settings.json` sidecar so
switching back restores it. This sidecar is editor state, not render identity.
Switching does not delete compatible maps or masks and never starts inference.

## Ownership and module interfaces

Use the existing core domain modules. Add `core/preparation` for runtime,
numerics and artifacts, and `core/application/preparation` for the coordinator.
The isolated inference worker has its own distribution. Under ADR-0052, core
owns workflows; server and CLI translate requests and supply host dependencies.
Paths below are relative to `src/etsy_listings`. Preparation interfaces are
proposed; existing modules retain their established public interfaces.

| Module | Interface and responsibility |
| --- | --- |
| `core/workspace` | Resolve assets, reference photo, cache records and safe paths. Enumerate photos here only. Provide recoverable calibration save/load. |
| `core/render/config.py` | Parse template-kind and renderer unions and resolve immutable settings without workspace access. |
| `core/preparation/runtime.py` | `inspect`, `setup`, `update`; pinned installation and capability reports. Own the global installation layout. |
| `core/application/preparation` | `submit`, `status`, `list_jobs`, `cancel`, `events`, `reconcile_saved`; durable queue, snapshots, scheduling, recovery and cleanup. Host supplies lifecycle dependencies. |
| `core/preparation/numerics.py` | Pure crop planning, coverage checks, mask proposal, fitting and baking. Arrays and immutable settings in; typed results out. |
| `core/preparation/artifacts.py` | `readiness`, `acquire`, `publish`; artifact validation, generation ownership and manifest replacement. No model runtime imports. |
| `core/render` | Pure Photo warp and Marigold scene composition over supplied arrays and accepted maps. |
| `core/config/listing_validation.py` | Shared local refusals from preparation facts in `WorkspaceFacts`. Engine adapters return `Blocked`. |
| `core/application/mockup_templates.py` | Extend existing config/save/preview operations to coordinate calibration transactions and preparation. Return typed results/refusals without HTTP dependencies. |
| `server/api` | Translate HTTP requests, refusals and SSE events. App lifespan constructs and starts/stops the coordinator. No scheduling rules in routes. |
| `cli` | Runtime commands through core operations, without importing server or constructing its queues. |

React lives in `src/ui`; generated OpenAPI types live under `src/ui/src/api`.
Extend Import Linter to protect preparation internals and preserve dependency
direction. Add a distinct mockup-template lock domain: the current
`WorkspaceLocks.listing_template` protects listing templates, which are different
files. Listing document locks stay in `core/workspace/listing_documents.py`.

Keep runtime imports out of artifact loading and rendering. An artifact reader
must work when inference dependencies are absent. Inject a worker adapter and
executor into the coordinator for behaviour tests; use real files for publication
and restart tests. Do not make the numerical code imitate a background job.

`WorkspaceFacts` collects map readiness once per request, alongside template and
garment facts. The editor and engine consume the same result. Only the engine
computes deployment diffs or runs deployment stages. This preparation queue does
not change sequential `apply` or the existing deploy-run recovery policy.

## Storage

All template paths below are relative to the template directory. They are
conventions implemented by `Workspace`, not values written into YAML.

```text
mockup-templates/example/
  template.yaml
  renderer-settings.json
  ivory.png
  pepper.png
  masks/
    automatic.png                 # single or colour-matrix
    edited.png
    metadata.json
    left-shirt/                   # multiple placement instead
      automatic.png
      edited.png
      metadata.json
  maps/
    current.json
    generations/<generation-id>/
      manifest.json
      placement.npz               # implicit placement
      left-shirt.npz              # explicit placement instead
  .calibration-transaction/        # present only during a recoverable save
```

Mask PNGs are full main-photo dimensions in photo pixel coordinates. Zero hides
print, 255 permits print, and intermediate values soften an edge. Moving the
quad does not move painted corrections. `metadata.json` records the photo
identity, automatic-mask algorithm version and checksums. A photo identity
change must not silently reinterpret an old mask on a different garment.

Both automatic and edited masks are durable. Before an automatic mask exists,
mask editing reports unavailable with a preparation explanation. A normal
rebuild preserves the saved automatic baseline and edited mask. Explicit fresh
preparation may replace the baseline only where no manual correction would be
lost; otherwise preserve the saved masks. For a changed main photo, refuse mask
reuse and require an explicit reset for that photo. Do not reconstruct manual
corrections from disposable brush history.

Workspace cache, reached through accessors:

```text
.cache/preparation/
  jobs/<job-id>.json
  predictions/<template>/current.json
  predictions/<template>/sets/<set-id>/...
  work/<job-id>/...
  brushes/<template>/...
```

Global installation:

```text
<home>/.etsy-listings/marigold/
  current.json
  runtimes/<engine-version>/...
  weights/<checkpoint-revision>/...
```

Keep the latest usable prediction set per template. A set covers all required
placement crops and contains normals, lighting and depth. Write replacements
separately, validate the entire set, then replace `current.json`. Retain partial
completed evidence under the owning job for retry or cancellation recovery.
Delete superseded sets once no active job references them; unfinished replacement
work must not delete the last usable set. Terminal job leftovers that contribute
to neither the current set nor a resumable attempt can be removed. Bound this
cleanup by references, not by an arbitrary age that could erase active work.

Map generations follow the same reference rule. Each render acquires one fixed
generation and releases it when done. After publication, remove superseded
generations only when no render or job holds them. Use `workspace.remove_tree`
for cleanup on Windows. Cache deletion loses historical brush Undo and reusable
predictions, but leaves masks, Reset and prepared rendering intact.

To publish maps, write all archives and the generation manifest into staging,
validate the complete set, then move it to its immutable generation directory.
Under the template lock, compare current preparation inputs and atomically
replace `maps/current.json` with `{schema_version, generation_id,
manifest_checksum}`. Readers see the old complete generation or the new one.
On failure leave the old pointer intact. Recovery can remove unreferenced staging
and generation directories after checking persisted jobs and reader ownership.

## Calibration saves and revisions

Fixed mask filenames mean a save changes several files. A series of renames is
not an atomic multi-file commit. Use a short per-template write lock and a
template-owned recovery transaction:

1. Check the caller's revision and read the complete current calibration.
2. Apply mask operations and validate all new configuration and mask data.
3. Stage new files and backups, then write a transaction manifest containing
   expected checksums and a durable commit intent.
4. Replace destination files. Keep the template lock until completion.
5. Verify the committed files, mark the transaction complete and remove it.

On startup or before reading that template, recover an interrupted transaction.
No commit intent means discard staging; a commit intent means roll forward from
the staged payloads. Keep those payloads until every destination is verified.
If recovery data is damaged, block with a repair explanation rather than reading
a mixed calibration. The transaction lives with the template so cache deletion
cannot destroy it. Readers in the server acquire the same lock. Concurrent CLI
reads refuse a template with an active transaction; they do not recover a live
server's transaction. This design assumes one server owns a workspace.

The revision returned as an ETag covers the effective config, resolved main
photo identity and saved mask checksums. It changes when an external edit changes
those inputs. It is an edit-concurrency token, not a render hash. Identical saves
do not create new jobs or invalidate maps.

Brush history is a cache of operations and the raster checkpoints needed to undo
them. Each history is bound to a committed mask checksum. A crash after committing
the visible mask but before recording history may lose Undo; it must never lose
the saved mask. Discard mismatched histories. Reset copies the durable automatic
mask and clears manual history. A template-level lock serializes configuration,
mask changes and publication checks.

## Reference photo, crops and evidence

For colour-matrix templates choose the first actual photo by ordinal filename
ordering, with a single backend implementation. Single and multiple templates
use `scene.png`. Do not use the current thumbnail helper's unconditional
`scene.png` preference for a colour-matrix template. Report the chosen path to
the browser. A newly added photo that sorts first changes the reference identity.

Main-photo identity includes its template-relative filename and canonical decoded
pixels, dimensions and colour conversion version. Shared-colour photos must have
identical dimensions. Different folds or foreground objects can still make a
pack unsuitable; dimensions are a mechanical gate, not a visual certification.

For each placement, find the enclosing axis-aligned rectangle. Expand it by
40% of its width on each horizontal side and 40% of its height on each vertical
side, round outward and clip to photo bounds. Persist the original-pixel crop
rectangle and the complete resize/padding transform with each prediction.

Reuse evidence only if its photo, model revisions, inference settings and
preprocessing identity match, and it covers the edited placement plus a safety
margin. Measure that smaller reuse margin during implementation. Until validated,
use the full 40% crop requirement conservatively. At photo boundaries, compare
the clipped requirement rather than demanding pixels outside the photo.

Overlapping placement requirements may share one existing prediction crop when
it passes the same coverage rule. Do not merge distant placements into a huge
crop merely to avoid another model call. Placement reorder does not change the
evidence set. Inference never consumes the selected preview artwork.

## Runtime and worker protocol

Add explicit `etsy-listings marigold setup`, `status` and `update` commands.
Setup and update install into a staged versioned directory, verify capabilities
and weights, then switch the global installation manifest. Preparation never
downloads packages or weights. An active job retains its engine version through
an update. Report that a newer engine is available when preparing an older
template; compatible maps remain renderable without updating.

Start from the prototype's native Windows environment: Python 3.12,
torch 2.8.0 with CUDA 12.8 wheels, diffusers 0.35.1, transformers 4.56.2,
accelerate 1.10.1, huggingface-hub 0.35.1, numpy 2.2.6, Pillow 10.4.0,
safetensors 0.6.2 and scipy 1.16.2. Resolve a complete installation lock before
shipping. The isolated environment must not change production imaging pins.

The prototype pins these checkpoint revisions:

| Role | Checkpoint | Revision |
| --- | --- | --- |
| Normals | `prs-eth/marigold-normals-v1-1` | `09cfdd258cb281fa006cf1afcd2284376d16687d` |
| Lighting | `prs-eth/marigold-iid-lighting-v1-1` | `08c3930bb641abf786ba44ce92547507ebefbc16` |
| Depth | `prs-eth/marigold-depth-v1-1` | `9571e7123e258cf052b4e54241f17971c290e9a8` |

Capability checks test the installed worker, CUDA availability, weight integrity
and a small inference. A missing installation blocks preparation with a setup
instruction. A model out-of-memory error fails that step without reducing quality
settings silently or discarding earlier evidence.

One warm subprocess belongs to each workspace coordinator. Send UTF-8 JSON-lines
over stdin/stdout; stderr is diagnostic logging. Drain both streams independently.
One inference call runs at a time. Keep models in system RAM with bounded eviction,
and move only active components to GPU. Exit after five idle minutes. The RAM
budget and eviction thresholds require measurement on the supported machine.
Different workspaces may contend for the GPU; there is no global ownership lock.

Protocol v1 has `hello`, `infer`, `cancel`, `shutdown`, `progress`, `result` and
`error` messages. Every request/reply includes protocol version and request ID.
The handshake reports engine version and supported roles before accepting work.
For example:

```json
{
  "protocol": 1,
  "type": "infer",
  "request_id": "prep-42-normals-1",
  "role": "normals",
  "input": "work/prep-42/crop-1.png",
  "output": "work/prep-42/normals-1.npz",
  "settings": {"num_inference_steps": 10, "ensemble_size": 3}
}
```

The worker receives a native absolute cache root at launch. Message paths are
relative to that root, validated against traversal, symlink escape and unexpected
files. Arrays never travel as JSON or pickle. A result names its artifact and
checksum; the coordinator validates both before accepting completion. The worker
writes a temporary file and renames only a complete artifact.

Cancellation records intent immediately. The worker finishes its active model
call, saves valid evidence, and runs no remaining calls. A reader thread must
accept control messages while inference is busy. The coordinator retains the
warm worker after normal cancellation. An unexpected worker exit fails the
current attempt with a retryable error. Establish watchdog and forced-shutdown
timeouts by measurement; a stopped process never publishes a partial result.

## Numerical preparation and artifact format

Port the prototype's numerical operations into pure production code; do not
import scripts from `docs`. Preserve explicit OpenCV interpolation and border
choices. Fit material coordinates using normals and depth, propose visibility,
bake sampling maps, then derive both lighting alternatives, texture and restrained
residual fields. Remove experimental overlap/anchor controls from the public
configuration. A single coordinator thread in the server process executes CPU preparation and
checks cancellation between fitting phases. It may overlap GPU inference.

The map generation manifest contains:

| Field | Meaning |
| --- | --- |
| `schema_version` | Artifact reader contract, initially 1. |
| `generation_id` | Storage identity only. Excluded from render hashing. |
| `preparation_inputs` | Main-photo identity, placement IDs/quads, masks, effective inference settings and the accepted compatibility versions. |
| `placements` | Exact required placement set, array file/checksum, extent and array descriptors. The implicit placement has a null ID. |
| `provenance` | Engine, checkpoint and package versions, timing and diagnostics. Not render identity. |
| `content_digest` | Canonical digest of the accepted numerical fields and their semantic layout. |

Each placement archive stores canonical float32 material coordinates, visibility,
estimated RGB lighting gain, photographic RGB lighting gain, scalar texture and
RGB residual, plus int32 patch labels if required by the sampler. Coordinates
use the prototype's material-space convention; declare axis order, pixel-centre
rule, extent and outside-domain behaviour in schema v1. This is a required porting
check, not permission to infer conventions from array shapes.

Visibility is in `[0, 1]`. Lighting gain is bounded to `[0.04, 1.7]`, texture to
`[0.9, 1.1]`, and residual to `[0, 0.035]`, matching the prototype. All float data
must be finite. Validate shapes, dtypes, declared extents, placement uniqueness,
photo dimensions, file checksums and archive size limits before allocating or
rendering. Load with `allow_pickle=False`. Unsupported schema versions produce
a migration/preparation explanation, never a best-effort reinterpretation.

Retain both lighting choices in the map. For strength `s`, use
`gain = 1 + s * (selected_gain - 1)`. Fabric texture and print shine scale their
stored fields without refitting geometry. Compose premultiplied artwork in
linear colour, preserving opaque ink and unchanged background pixels. Pin the
numerical conventions in golden tests. Share the main photo's fields across the
colour pack and use each selected colour photo as the background. Do not multiply
artwork by the main garment's albedo.

Production needs an explicit shared-reference artifact contract. The prototype's
per-photo assertion cannot simply be disabled. Main photo, permitted target
dimensions and shared coordinate meaning remain validated on every scene load.

## Jobs, edits and recovery

An atomic JSON job record contains `schema_version`, ID, template, request ID,
action, kind, saved input snapshot, engine selection, phase, step, timestamps,
cancellation intent, validated evidence references, CPU checkpoints, result or
error, and ordered events with increasing sequence numbers. Store events with
the record so an event cannot announce work that was never persisted. Progress
is step-level; do not emit every model iteration into an unbounded journal.

Jobs have kind `prepare | rebuild`. Lifecycle phases are:

```text
queued -> running -> completed
                  -> failed
queued/running -> cancelling -> cancelled
queued/running -> superseded
```

`step` distinguishes loading models, normals, lighting, depth, fitting, baking
and publication. Counts report actual completed placements. A completed job has
published a current generation or proved current maps already satisfy the request.
Superseded work retains valid evidence but publishes nothing. These phases do
not replace template readiness.

The coordinator keeps one GPU lane and one CPU lane. Queue additional templates
in persisted submission order. A save can coalesce obsolete queued CPU rebuilds
into one job for the latest saved snapshot. All model calls remain serial, even
when CPU fitting overlaps them.

Save first commits calibration, then reconciles desired preparation. If valid
cached evidence covers it, queue CPU rebuilding. Otherwise report preparation
needed and wait. Appearance-only saves keep map readiness and mark rendered
images stale. Publication locks the template, re-reads current preparation inputs,
and compares them with the job snapshot. Appearance changes do not prevent
publication because they are not fitting inputs. Geometry or mask changes do.

For obsolete work, finish only the active model call or CPU phase, retain valid
evidence, skip remaining obsolete work, and reconcile the latest saved inputs.
An earlier Prepare click must not authorize inference for new inputs that need
different evidence. Publishing an automatic mask from first preparation is part
of the same guarded transaction; the job must not overwrite a user's newer mask.

Persist cancellation before acknowledging it. Queued cancellation is immediate;
running cancellation waits for the active safe checkpoint. Explicit cancelled
jobs remain cancelled after restart. Recovery loads records, validates referenced
files and requeues unfinished work. Interrupted model calls restart that call;
valid results survive. If publication succeeded before the completed record was
written, recognize the matching accepted generation and finalize the record.

Reconcile saved templates at startup as well as recovering jobs. This closes the
crash window between a calibration commit and creating its rebuild job. Recovered
work rechecks current inputs and never restores stale maps as Ready. A missing
engine installation blocks the attempt with an actionable error; recovery does
not install it. Copying a complete template preserves rendering without copying
the job cache.

## Readiness, invalidation and render identity

Map state is `needs_preparation | out_of_date | ready`. Return structured reasons
such as `missing_maps`, `placement_changed`, `mask_changed`, `photo_changed`,
`invalid_artifact`, `unsupported_schema` or `incompatible_dimensions`. Photo warp
uses `not_required`. Missing or invalid required placement maps block the entire
multiple scene. Preserve existing `colour_coverage: subset` artwork selection;
preparation still covers the configured placement set.

| Change | Evidence | Maps | Rendered output |
| --- | --- | --- | --- |
| Artwork or target colour selection | Reuse | Reuse | Re-render |
| Appearance settings | Reuse | Reuse | Re-render |
| Quad or edited mask | Reuse if coverage/identity permit | CPU rebuild, otherwise Prepare | Block until maps current |
| Add/remove placement | Reuse matching evidence | Publish full new placement set | Re-render after readiness |
| Reorder multiple placements | Reuse | Reuse per ID | Re-render in new composition order |
| Main photo identity | Require matching evidence | Rebuild or Prepare | Block until current |
| Other colour photo pixels | Reuse | Reuse subject to dimensions | Re-render that scene |
| Inference settings | Require matching evidence | Explicit Prepare unless already matching | Block until current |
| Installed engine update | Preserve accepted evidence/maps | No automatic invalidation | Unchanged |
| Unsupported map schema | As available | Explicit migration or Prepare | Block |
| Delete workspace cache | Lost | Reuse durable maps | Render normally |

An explicit Prepare again selects the installed engine and refreshes predictions.
Ordinary rendering uses the accepted compatible artifact version. An engine
update notice is informational. Rebuilding with old evidence uses a supported
compatible fitter; otherwise explain why explicit preparation is required.

Separate evidence identity, preparation-input identity and render identity.
Evidence includes exact checkpoint and preprocessing versions. Preparation inputs
include geometry, mask pixels and evidence identity. Render identity includes
accepted map numerical content, composition order, appearance, artwork and target
photo pixels. Exclude timestamps, job IDs, absolute paths, engine availability,
inactive renderer settings and provenance from render identity. Use the existing
`canonical_hash` for engine documents. Hash canonical array content separately,
not ZIP timestamps or filenames, then include that digest in the render document.

Preserve the two engine axes: input identity decides whether to render; output
file hashes decide whether to upload. A copied template or newer installed model
must not cause a remote write when accepted content and settings are unchanged.

## HTTP contracts

Retain `/api/templates` and extend existing config and preview routes. The new
config body replaces the old body; there is no legacy request-body union.

| Method and route | Contract |
| --- | --- |
| `GET /api/templates` | Add renderer type and shared readiness summary to each template. |
| `GET /api/templates/{name}/config` | New template config; ETag contains calibration revision. |
| `PUT /api/templates/{name}/config` | Required `If-Match`; save envelope below; return saved config and new ETag. CPU reconciliation follows commit. |
| `POST /api/templates/{name}/preview` | Existing photo/design selection with renderer-specific settings. Marigold allows unsaved appearance; geometry/masks must match accepted maps. Return PNG plus render identity. |
| `GET /api/templates/{name}/design-preview` | Saved configuration; shared readiness and CPU renderer. |
| `GET /api/marigold/runtime` | Installed and app-required engine, capabilities, setup problem and update notice. No installation side effect. |
| `GET /api/templates/{name}/preparation` | Current readiness, reference photo, placement states, revision and active/latest jobs. |
| `GET /api/templates/{name}/mask` | Implicit placement's edited PNG; `source=automatic` reads the Reset baseline. |
| `GET /api/templates/{name}/mask-history` | Implicit placement's cached Undo history, bound to mask revision. |
| `GET /api/templates/{name}/placements/{id}/mask` | Same mask contract for a multiple placement. |
| `GET /api/templates/{name}/placements/{id}/mask-history` | Same history contract for a multiple placement. |
| `POST /api/preparation/jobs` | Explicit Prepare, Prepare again or Retry; return 202 with job reference. |
| `GET /api/preparation/jobs` | Queue and recent records; optional template filter and pagination. |
| `GET /api/preparation/jobs/{id}` | Authoritative persisted job detail, including last event sequence. |
| `GET /api/preparation/jobs/{id}/events` | SSE replay after `Last-Event-ID`, then live events. Disconnect does not cancel. |
| `DELETE /api/preparation/jobs/{id}` | Request cancellation; return current record, retaining history and evidence. |

Single-placement mask requests reject a multiple template and vice versa. The
server resolves paths and validates IDs. The browser never constructs asset paths.

Save envelope for an implicit placement:

```json
{
  "request_id": "save-unique-id",
  "config": {
    "kind": "single",
    "bounding_box": [
      {"x": 420, "y": 360}, {"x": 920, "y": 350},
      {"x": 950, "y": 1080}, {"x": 400, "y": 1090}
    ],
    "renderer": {"type": "marigold", "config": {}}
  },
  "mask_edits": [
    {"operations": [
      {"type": "stroke", "mode": "mask", "diameter_px": 24,
       "points": [[520, 410], [525, 417], [531, 424]]}
    ]}
  ]
}
```

Multiple entries additionally carry `placement_id`. Operations are ordered
`stroke`, `undo` or `reset`; strokes use `mask | unmask`. Validate coordinates,
finite diameter and bounded request size. Rasterization is deterministic at
original-photo resolution. The browser draws an immediate approximation, then
uses the saved raster returned through the mask endpoint. `request_id` makes a
lost-response retry return the original result rather than paint a stroke twice.
A stale `If-Match` returns 412; no matching history for Undo returns 409.

Persist the latest save receipt with the calibration transaction, including
request ID, request digest and resulting revision. Return that receipt for an
exact retry. Reusing its ID with different content returns 409. Older retries
whose receipts have been retired still fail their stale revision check. The
receipt is template metadata and never enters render identity.

Preparation request:

```json
{
  "template": "example",
  "config_revision": "revision-18",
  "action": "prepare",
  "request_id": "prepare-unique-id"
}
```

Actions are `prepare`, `prepare_again` and `retry`; Retry includes `previous_job`.
Prepare reuses valid evidence. Prepare again intentionally refreshes it. Retry
uses completed work but always targets the supplied current saved revision.
Persist request deduplication with the job record. Identical active work returns
its job instead of creating another; a reused request ID with a different body
returns 409. Reject changed revisions with 412. Unsupported preparation capability
returns 409 with a structured setup reason. Validation errors return 422.

Prepare first saves outstanding edits, then submits that response's revision.
If another save wins between those requests, the preparation request fails
without starting inference. GET endpoints never enqueue work. Failed/cancelled
jobs require explicit Retry; repeated cancellation is idempotent.

Readiness example:

```json
{
  "template": "example",
  "config_revision": "revision-18",
  "main_photo": "./ivory.png",
  "maps": {"state": "out_of_date", "reason": "placement_changed", "can_render": false},
  "active_job": {"id": "prep-42", "kind": "rebuild", "phase": "running",
                 "step": "fitting", "placements_completed": 0, "placements_total": 1}
}
```

SSE events carry sequence, job ID, phase, step, elapsed time, placement counts
and optional structured error. Persist before emitting. Include an initial state
snapshot when no cursor is supplied; reconnect with a cursor replays subsequent
events. Missing retained history returns a resync instruction so the client reads
status. No reconnect path starts another job. The queue can refresh on events
and periodic status reads without adding a second authoritative state store.

## Editor and rendering flow

Keep the accepted mockup layout. The renderer selector reads Photo warp or
Marigold. Show Advanced settings only for Marigold. Placement overlay, mask
painting and design-box visibility remain local interactive work. Done or Escape
exits mask mode without discarding edits; Save commits them.

First full-quality preview runs automatically once maps are ready. Later input
changes mark it stale and use the existing red Re-render button. Sliders do not
launch fitting or inference. A request captures design, target photo, appearance
and generation identity; discard late responses if that identity no longer
matches the current view. Retain full-size inspection and design upload/selection.

Acquire maps once per scene render and hold the generation throughout it. An
accepted deployment preview may supply final bytes only when the engine's exact
render identity matches. Missing maps block with the same explanation in the
editor, listing previews and CLI plan/apply. Ready scenes may render independently,
but an incomplete required listing image set prevents deployment.

## Verification and delivery

Build the complete integration before the shared-colour and multiple-placement
quality review. Those reviews remain release gates. The prototype demonstrates
local model execution and individual-photo quality; it does not establish either
gate. Keep measurements separate from quality judgements.

| Layer | Required evidence |
| --- | --- |
| Unit | New config discrimination, safe IDs, crop bounds, evidence coverage, invalidation and pure numerical operations. |
| Golden | Unchanged Photo warp bytes after config conversion; deterministic Marigold composition, lighting controls, masks and transparent edges. |
| Behaviour | Queue deduplication, one GPU lane, CPU overlap, cancel/retry, edits during work, stale publication refusal and all-placement completeness. |
| Filesystem recovery | Interrupt each transaction/publication checkpoint, restart, verify coherent calibration and maps; remove cache and retain rendering/Reset. |
| Protocol | Real subprocess handshake, malformed output, stderr draining, cancellation during a call, missing runtime and worker exit. No production weights required for these tests. |
| Frontend | Renderer configuration, mask Undo/Reset, stale response rejection, SSE reconnection, Save/Prepare sequencing and accessible controls. |
| Browser | Edit, Save, Prepare, reconnect, preview and final asset read across all three kinds, using a controlled worker. |
| Native Windows integration | Pinned real models, setup/update, warm reuse, GPU/RAM bounds, cancellation latency and cold/warm timings. |
| CPU-only rendering | Prepared template renders in an environment without torch, CUDA or weights; no model import on that path. |

Compare shared maps against independent per-photo preparation at full resolution
for light/dark colours, changed folds and foreground edges. Use opaque white,
saturated artwork, fine text, transparency and the real design. Verify every
multiple placement with distinct artwork and overlapping composition order.
Record failures and split incompatible colour photos into separate templates.

Implementation measurements still needed are the evidence reuse margin, bounded
model RAM budget, numerical thread limits during overlap, inference input caps,
watchdog/shutdown deadlines and end-to-end responsiveness. Do not turn prototype
timings into guarantees. Store the results beside the existing performance report.

## Delivery sequence

The [stack execution contract](stack.md) assigns these stages to PRs and names
their exit conditions and shared verification gates.

These stages are unshipped. Add delivery PR links as they land. Build the complete
integration before the final visual quality review, as agreed.

| Stage | Deliverable and verification | Delivery |
| --- | --- | --- |
| 1 | Renderer union, fixture conversion, mask paths and recoverable saves. Preserve Photo warp goldens. | Pending |
| 2 | Pinned runtime, worker protocol, explicit installation and native Windows smoke inference. | Pending |
| 3 | Pure preparation, immutable artifacts and CPU rendering; map roundtrips and CPU-only tests. | Pending |
| 4 | Core coordinator, durable jobs, retention, cancellation and recovery; race tests. | Pending |
| 5 | Server adapters and React editing/preparation/preview; OpenAPI regeneration and browser verification. | Pending |
| 6 | Shared readiness, engine identity and preview promotion; idempotency and refusal tests. | Pending |
| 7 | Colour/multiple-placement quality review, memory/latency measurements and release-gate results. | Pending |

ADR-0053 extends ADR-0012 and ADR-0014 and distinguishes durable preparation from
ADR-0041 deployment runs. Preserve ADR-0008, ADR-0013, ADR-0039, ADR-0040 and
ADR-0052. Update the living architecture as implementation changes. Do not edit
frozen history to authorize this feature or describe this plan as shipped.
