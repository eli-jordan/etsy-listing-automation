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
