# ADR-0053: Prepare durable mockup maps before rendering

Status: accepted, not implemented. Agreed 2026-10-01 through 2026-10-03 in the
[Marigold specification](../features/marigold-20261001/spec.md) and
[technical design](../features/marigold-20261001/plan.md).

Run model inference only during explicit authoring preparation. Publish a complete
immutable map generation with the template, then render new artwork through the
pure CPU renderer. This extends ADR-0012 while keeping deterministic pixels and
exact imaging dependency pins. Copied templates can render without GPU weights
or an inference environment. Ordinary plan/apply never starts model work.

Share the main photo's preparation across a colour pack, without per-colour
exceptions. Separate incompatible photos into their own templates. Automatic
and edited masks are durable assets; brush history and predictions are cache.
Keep the latest usable prediction set until its complete replacement is validated
and active jobs release the old one. Cache cleanup must preserve the saved mask,
Reset baseline and accepted maps.

Preparation has durable jobs, resumable checkpoints and cancellation after the
active model call. ADR-0041 deployment runs remain in memory and apply stays
non-cancellable. Core owns the preparation coordinator; the server supplies its
lifecycle and HTTP/SSE adapters under ADR-0052. Runtime installation is explicit
and separate from preparation, on native Windows with no WSL dependency.

This extends ADR-0014 with an independent renderer discriminator. Replace the
old format with `renderer.type` and `renderer.config`; no compatibility parser
is required. Only multiple placements need explicit stable IDs. Workspace derives
mask locations so YAML does not repeat a path convention. Photo warp retains
its existing numerical output under the new format.

## Amendment, 2026-10-19: bound material storage by placement extent

Write schema 2 placement maps over a bounded photo-coordinate extent, retaining
schema 1 full-photo reads. The full-photo storage requirement is unworkable for
the five-second warm 2048px correction goal. A single placement retains fourteen
four-byte channels, or 235 MB, and the measured synchronous rebuild spends 2.92
of 7.38 seconds publishing and validating those arrays. Most pixels are outside
the print and cannot affect the result.

Each placement records its half-open extent and the complete reference photo
size. Pixel centres and fitted coordinates stay in the original photo frame.
Retain a sixteen-pixel halo around the quad for the pinned photographic blur and
material derivatives. Visibility outside the extent is implicitly zero. Render
the complete original-size photograph and preserve every visible map value and
final image pixel. Include the extent in schema 2 numerical identity so moving
an otherwise identical field cannot reuse an old rendered scene.

This changes storage, not inference coverage or output quality. Keep the complete
forty-percent prediction margin, conservative full-photo preflight limits,
complete-generation publication, cancellation checkpoints and reader leases.
Existing schema 1 assets remain renderable without model installation or a
migration. CPU rebuilds can publish schema 2 from their validated saved evidence.

## Amendment, 2026-10-19: deterministic lossless Marigold encoding

Use fixed PNG compression level one for both Marigold previews and deployment,
and include that encoder setting in their shared scene identity. Measurements
on the same full 2048px RGB pixels reduce encoding from 0.80 to 0.18 seconds for
the synthetic fixture and from 1.26 to 0.22 seconds for a real photograph. Files
grow by 21 and 16 percent respectively. Decoded pixels are identical. This
exchanges modest local transfer and storage for correction latency without
changing resolution, colour, material filtering or deterministic output.

Photo warp retains level six. Old Marigold output bytes remain distinct in
identity and cannot be promoted as a newly encoded scene. Pin Pillow and retain
metadata-free encoding as before.

## Amendment, 2026-10-19: separate transient editor composites

The user approved a lower-resolution interactive material preview with a
subsecond correction target. Use retained validated evidence to fit a transient
17 by 17 mesh and rasterize at 512px. Keep original photo coordinates and the
complete evidence margin. This frame is visibly approximate and has no durable
generation or approval identity. It never changes masks, history or readiness.

Reuse the existing 80ms editor debounce and one-request-at-a-time WebP loop.
Keep durable autosave at its normal 800ms idle delay so a full-resolution CPU
rebuild does not preempt each interactive response. Full-quality preview and
export continue to consume only complete accepted 49 by 49 generations.

Cap interactive artwork at a 1024px longest edge before building floating-point
material mip levels. A measured 4200 by 4800 design otherwise takes 3.75 seconds
per edit despite the 512px destination. Retain RGBA validation and use the
original complete artwork for full-quality preview and export.


## Amendment, 2026-10-19: prioritize correction under a durable rebuild

Use a 256px longest edge and 512px artwork cap for interactive composites,
retaining the transient 17 by 17 fit. This supersedes the earlier 512px frame
and 1024px artwork limits. Real two-placement edits with 4200 by 4800 artwork
still exceed one second when a full-quality rebuild competes for CPU, despite
status-request coalescing. The user explicitly permits reduced interactive
resolution. Label the approximation in the editor; full-quality Preview and
export retain original artwork, complete photo size and the accepted 49 by 49
maps. Keep the 800ms durable autosave delay and revision fences.


## Amendment, 2026-10-19: settle the interactive request before autosave

Keep the 800ms minimum idle delay, but defer automatic saving while the current
interactive composite is pending. A save must not supersede its own requested
revision mid-fit and force a slower retry. Explicit Save and preparation actions
retain their existing revision checks. This affects scheduling only; masks and
durable map publication remain unchanged.


## Amendment, 2026-10-19: yield CPU preparation to interactive requests

Give transient editor composition priority at existing CPU preparation phase
checkpoints within the same workspace. A background fit waits between phases
while an interactive request is active and continues checking cancellation.
This preserves exact numerical operations and generation leases. It does not
pause active inference or alter its dispatch guard. The settled-request run
removed revision retries but still measured a 1.017-second composite under CPU
contention; the foreground must not compete with every remaining rebuild phase.


## Amendment, 2026-10-20: readable interactive composites

Manual review found the 256px composite too blurry to judge artwork. Interactive
composites now require a 1024px longest edge, preserving non-square photo aspect
ratio and retaining smaller source photos at their native size. Rasterize from
original coordinates and validated evidence at that size. Enlarging a completed
256px frame does not satisfy this requirement. Retain enough original artwork
samples to resolve fine text and lines at 1024px; the former 512px artwork cap
is superseded. A transient 17 by 17 geometry fit remains permitted if its
high-resolution raster passes detail checks.

The final edit-to-displayed-composite target remains strictly below one second,
preferably below half a second, for masks and covered geometry on one and two
placements, including overlap with durable rebuilding. Measure the actual
1024px decoded display and report missed tails without relaxing resolution or
the threshold. Full-quality Preview and export retain original artwork and
accepted complete 49 by 49 generations. Scheduling, revision fences, explicit
inference and selected-colour background behavior remain unchanged.
