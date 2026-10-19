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
