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
