# ADR-0058: Allow per-listing template positions within limits

Status: accepted. First recorded 2026-11-02.

A listing may position artwork on a mockup without changing its Printify print
placement. Store absolute photo-pixel corners under `template_positions`, using
the same box schema as the mockup template. Relative offsets would silently
move a listing's saved box when the template is recalibrated; absolute corners
preserve what the seller approved and make the next validation reveal a mismatch.

Accept only uniform scale, translation and rotation in the template box's unit
frame, mapped through its homography. Fit the similarity there and measure its
maximum corner residual in photo pixels (one pixel tolerance). Applying these
operations directly in photo pixels would change the apparent perspective of
an angled garment. Offsets are fractions on each unit-frame axis; positive
rotation is clockwise about the unit square's centre, before translation.

Workspace limits constrain how far a mockup may depart from the actual print.
`plan` refuses stale keys, incompatible shapes and positions outside those
limits, rather than clamping or grandfathering them. Only the editor's explicit
Fit within limits action fits then clamps the pose. Reset removes the stored
entry. Recalibration never rewrites a listing. Listing templates and batches
never copy positions into newly created listings.

The [specification](../features/template-positions-20261102/spec.md) owns the
limits and refusals. The [plan](../features/template-positions-20261102/plan.md)
splits model/validation, rendering and editing into separate PRs (P4). Marigold
positions remain refused until PR 7 follows spike sign-off (P1); this work adds
no real-shop e2e cases (P5). Edits retain listing source through ADR-0055's
existing document owner.

## Amendment (2026-11-02): tilt is a rigid rotation

Seller decision 2026-11-02. A pose applied in the unit square shears a
non-square box into a parallelogram when tilted, unlike the approved prototype.
The pose is therefore applied in the box's *rectified frame*: the template
quad's unit-square parameterisation scaled by `(W, H)`, the mean lengths of its
top/bottom and left/right sides in photo pixels. Uniform scale and rotation act
about the centre of that frame, offsets are fractions of W and H, and the result
is mapped through the template homography. Fitting, the residual and Fit within
limits use the same frame. The unit-frame wording above is superseded by this.

## Amendment (2026-11-02): Marigold positions and inference

Marigold positions ship with option B (plan P1): each distinct position is
rendered with maps fitted directly to its posed quad, from template evidence
that covers the *padded quad* (the template box grown to the largest box the
current limits allow). Fits are content-addressed cache artifacts, validated on
load like published maps; a plan or preview waits for a missing or running fit
and never renders the template's own maps for a positioned layer.

ADR-0054 runs model inference only for explicit authoring. Saving a Marigold
position, confirming wider limits in Settings, and saving the geometry of a
template a listing positions are such explicit requests:
each may queue a *coverage* job that infers the padded quad's crop through the
existing preparation queue and leases. A coverage job retains its evidence after
the template's own, publishes no maps, and so leaves the template's generation
unchanged. `plan` and apply never queue inference; they refuse until coverage
exists. Only templates some listing positions are covered: wider limits never
queue inference for a template no listing has moved, since saving a position
there queues it then.

## Amendment (2026-11-07): the editor draws a moving position itself

A flat overlay on the saved composite left the old print in place under a
thumbnail of the new one for the seconds a render takes, which made fine
adjustment guesswork. Rendering faster cannot close that gap: a Marigold
position needs its own fit. The stage therefore composes the scene in the
browser with WebGL while a position is ahead of its composite, from the bare
photo, each layer's artwork and, for Marigold, the template's mask.

This puts a second, approximate compositor in the browser, which is only ever a
stand-in. It never reaches a file, a hash or a lockfile; the server's composite
replaces it as soon as it has loaded and stays the only picture `apply` writes.
The artwork comes from `GET /api/listings/{name}/scene-artwork`, resolved on the
server as the preview is, so the stand-in and the render print the same file.

## Amendment (2026-11-06): coverage belongs to preparation

The 2026-11-02 amendment covered a template only once a listing positioned it,
to spare inference on templates nobody moves. In use that put about two minutes
of inference at the moment a seller first saved a position, in an editor that is
expected to be fast, and the preview refused until it finished. A seller who
adjusts designs across many templates spends that inference anyway.

Asking to prepare a template is already an explicit request for inference, and
preparation is where slow work, queueing and progress are expected. So a
completed Prepare, Prepare again or Retry goes on to queue the template's
coverage job, whether or not a listing positions it. It stays a second job rather
than a larger crop in the first: the template's own maps must keep coming from
its own crop, or preparing would change renders of listings that never moved
anything. A CPU rebuild queues nothing, since it is not a request for inference.

`POST /api/preparation/coverage` queues coverage for every prepared Marigold
template at the seller's request, for templates prepared before this change or
limits widened since. Saving a position still queues coverage when it falls
short, as the safety net for the cases preparation does not reach: limits
widened over a template no listing positions, and geometry rebuilt from existing
evidence. `plan` and apply still never queue inference.

For those same cases the editor refuses to enter Position mode until the template
is ready, rather than letting a save start inference behind a broken preview. It
reads `GET /api/templates/{name}/coverage`, kept out of the preparation status
because the catalog reads that for every template: this read skips validating
the prediction files, which is most of the cost, and queueing still validates
them. Asking to adjust a template that falls short queues its coverage through
`POST /api/templates/{name}/coverage`: that click is an explicit request for the
inference, as saving a position was.
