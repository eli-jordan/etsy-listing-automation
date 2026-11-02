# Marigold padded-fit spike (option A)

Dated evidence, 2026-11-02. PR 1 of the
[template positions plan](../../features/template-positions-20261102/plan.md)
(decision P1). It answers the spec's
[*Spike gate*](../../features/template-positions-20261102/spec.md#spike-gate):
can [option A](../../features/template-positions-20261102/spec.md#marigold-option-a)
(fit maps once over a padded quad, then apply a listing position as a UV affine
at composite time) match a direct fit of the adjusted box, and how long does a
refit from existing preparation take? This record does not change the spec. The
seller's sign-off, recorded in the plan, gates PR 7.

**Recommendation: fail, as specified.** On the flat, hanging shirt option A
holds for single-limit poses but not at the combined corners. On both worn
shirts it misregisters the artwork by 23–60 px (99th percentile) even at the
template's own box, three to four times the difference between two legitimate
fits. Refit timing is not the problem (2–3 s on the CPU). Reasons and a
possible re-scope are under [Recommendation](#recommendation).

## Data and rules (decision P2)

The three templates named in the plan were copied from the live workspace into
a throwaway workspace under the system temp directory (`mockup-templates/<name>/`
only, read-only, plus the fixture `shop.yaml`). Nothing was written to or run in
the live workspace, and no photo, composite or map is committed.

| Template | Kind | Risk it covers | Box (photo px) |
| --- | --- | --- | --- |
| `cc1717-hanging-on-fence` | colour-matrix | flat, hanging | 793 × 793, axis-aligned |
| `cc1717-man-with-tattoos-standing` | colour-matrix | worn, folds | ≈ 840 × 1020, perspective |
| `cc1717-woman-with-oversize-fit` | colour-matrix | drape near the print edge | ≈ 860 × 1000, perspective |

All three photos are 2048 × 2048. The live workspace has **no Marigold
`multiple` template**, so multiple placements are untested. PR 7 would need its
own check that one padded placement does not overlap another's.

Preparation evidence lives in the source workspace's `.cache/preparation/` and
was not copied (P2). It could not have been reused in any case: the evidence
crop production planned for each template box does not cover the crop the
padded quad needs (table below). The harness therefore ran Marigold inference
once per template, in the throwaway workspace, on the crop production's
`plan_crop` would choose for the padded quad. The direct fits and the padded
fit use this same evidence, so the comparison isolates the fitting domain.

## Method

Harness: [`scripts/spike_template_positions.py`](../../../scripts/spike_template_positions.py),
run as

```sh
uv run python scripts/spike_template_positions.py --workspace <throwaway> --out <dir>
```

It imports production modules and changes nothing under `src/`. Reruns reuse
the stored predictions, so everything after inference is deterministic.

1. **Box frame.** Each template box's own (pre-homography) frame is a
   rectangle whose sides are the box's mean side lengths, mapped onto the box by
   its homography. A pose is a uniform scale, an offset (fraction of box width
   and height) and a rotation about the box centre in that frame
   (spec *Allowed shape*). Positive tilt is clockwise on screen.
2. **Padded quad.** The frame rectangle that covers every allowed pose at the
   default limits (scale 0.80–1.10, offset ±10%, tilt ±15°), mapped through the
   box homography. Its half-extent is `1.10 · (w/2·cos15° + h/2·sin15°) + 0.10·w`
   (and likewise for height), about 1.55× the box on each axis.
3. **Padded fit.** Production `numerics.prepare` on the padded quad with the
   template's edited mask, timed. Then a **limits-change refit**: `prepare` on
   the padded quad for narrower limits (0.90–1.05, ±5%, ±10°) from the same
   evidence, timed.
4. **Poses.** Thirteen: identity; each limit alone (scale 0.80, scale 1.10,
   offset left/right/up/down 10%, tilt ±15°); and four combined corners at scale
   1.10 with a diagonal 10% offset and ±15° tilt (down-right and up-left at +15°,
   up-right and down-left at −15°).
5. **Two composites per pose.**
   - *Direct*: `prepare` on the posed box, then `render_marigold_scene`.
   - *Option A*: the padded maps with material UV transformed by one affine
     (padded UV → frame → posed-box UV) and visibility recomputed from the
     transformed UV (zero outside [0, 1]²), as the spec describes. The same
     renderer and the template's appearance settings are used.

   Two option A variants were also measured:
   - *Renormalised*: rescales both lighting gains so their 70th percentile over
     the posed print is 1, as a direct fit's lighting normalisation would. This
     tests whether exposure explains the difference.
   - *Anchored*: replaces the analytic affine with the least-squares affine
     taking the padded UV sampled at the posed box's four corners to the unit
     square. This is how `flatten` anchors its own frame, and it costs four
     samples per composite.
6. **Designs.** A generated opaque test chart (12 × 12 hue cells, 3 px black
   grid, text), and the repository's ruler fixture design
   (`tests/fixtures/workspace/designs/take-a-hike.png`: a ruled grid, a circle
   and corner swatches on transparency; called `hike` in `results.json`).
7. **Metrics**, inside the print mask: every photo pixel that either composite
   changed from the blank photo.
   - **ΔE**: CIE76 colour difference (OpenCV float CIELAB, D65), mean and 99th
     percentile.
   - **Tone ΔE**: CIE76 after a σ = 6 px Gaussian blur of the print. This hides
     pixel-scale misregistration and keeps lighting and colour differences.
   - **Shift**: artwork misregistration in photo pixels. This is the UV
     difference between the two maps over pixels both show, scaled by the
     posed box's side lengths, at the mean and 99th percentile.

   Raw ΔE p99 is dominated by thin black lines landing a pixel or two apart, so
   shift and tone are the readable measures.
8. **Noise floor.** At the template's own box, the published production maps
   (fitted from the original, smaller evidence crop) are compared with a direct
   refit on the padded-quad evidence. That is how far two legitimate fits of
   the same box differ when only the evidence crop changes.

Correctness check: with zero padding (limits 1.0–1.0, 0%, 0°), option A
reproduces the direct fit exactly (0.00 px shift on all three templates).

## Timings

The machine is the seller's Windows workstation, with an RTX 3070 for
inference and the CPU for everything else. Fits and composites run at the full
2048 px.

| Template | Inference, once (normals / lighting / depth) | Padded fit | Refit after limits change | Direct fit per pose | UV affine per composite | Composite per render |
| --- | --- | --- | --- | --- | --- | --- |
| hanging-on-fence | 68 / 45 / 18 s | 1.93 s | 1.55 s | 0.86–2.40 s | ≤ 0.19 s | 0.18–0.95 s |
| man-with-tattoos | 34 / 32 / 18 s | 3.19 s | 2.52 s | 1.66–2.54 s | ≤ 0.25 s | 0.41–1.33 s |
| woman-oversize-fit | 43 / 32 / 14 s | 2.96 s | 2.74 s | 1.26–5.84 s | ≤ 0.42 s | 0.27–2.69 s |

- The fit times are `prepare` only. Publishing a generation (archive write and
  validation, about 2.9 s per placement per ADR-0054's 2026-10-19 amendment)
  comes on top.
- The composite times are `render_marigold_scene` medians over three renders.
  The UV affine is extra work over the padded extent, and the composite is
  slower than a direct one because its visible region is cropped from larger
  maps.
- The first inference (hanging-on-fence) includes model warm-up.

**Evidence coverage.** This is the timing finding that matters most. A refit
is CPU-only only while the template's evidence crop covers the new padded
quad's 40% margin.

| Template | Original evidence crop | Crop the padded quad needs | Original covers it | Padded evidence covers wider limits (0.70–1.25, ±15%, ±25°) |
| --- | --- | --- | --- | --- |
| hanging-on-fence | 313,123 – 1741,1550 | 0,0 – 2048,1941 | no | no |
| man-with-tattoos | 223,68 – 1826,1921 | 0,0 – 2048,2048 | no | yes |
| woman-oversize-fit | 221,77 – 1846,1944 | 0,0 – 2048,2048 | no | yes |

So adopting option A at the default limits needs one inference run per
Marigold template, about 1.5–2 minutes on this GPU, not just a CPU refit.
Widening the limits later can need inference again (hanging-on-fence). The
spec's "no model inference" refit holds only for limits whose padded quad stays
inside the stored crop. One way out is to always infer a full-photo crop.

## Differences

ΔE values below are for the ruler design unless marked *chart*. All values are
99th percentiles except "mean".

### Noise floor and identity (template's own box)

| Template | Published vs direct refit: shift mean / p99 | Published vs direct refit: tone p99 | Published vs option A: shift mean / p99 | Published vs option A: tone p99 |
| --- | --- | --- | --- | --- |
| hanging-on-fence | 0.9 / 2.0 px | 4.6 | 2.0 / 4.4 px | 13.5 |
| man-with-tattoos | 3.0 / 8.5 px | 12.0 | 15.9 / 33.2 px | 69.1 |
| woman-oversize-fit | 4.8 / 11.2 px | 21.0 | 14.2 / 29.2 px | 42.2 |

### Per pose: direct fit vs option A

Shift is the same for both designs because it compares maps. "A" is option A as
specified. "Anch." is the anchored variant. Renormalising the lighting changed
tone p99 by less than 1 ΔE in every row, so it is omitted.

**cc1717-hanging-on-fence**

| Pose | Shift p99 A | Shift p99 anch. | ΔE mean / tone p99 A (chart) | ΔE mean / tone p99 A | ΔE mean / tone p99 anch. |
| --- | --- | --- | --- | --- | --- |
| identity | 3.1 | 2.1 | 4.4 / 18.8 | 7.7 / 13.0 | 5.0 / 6.0 |
| scale 0.80 | 4.0 | 1.9 | 5.7 / 29.2 | 9.3 / 13.2 | 4.8 / 4.0 |
| scale 1.10 | 3.1 | 2.2 | 4.4 / 17.8 | 7.2 / 12.6 | 4.9 / 6.7 |
| offset left | 5.1 | 2.1 | 6.0 / 32.2 | 9.3 / 17.4 | 4.5 / 6.7 |
| offset right | 3.6 | 2.4 | 4.3 / 22.6 | 7.1 / 13.8 | 5.1 / 10.2 |
| offset up | 3.4 | 2.7 | 5.6 / 23.1 | 8.3 / 11.8 | 5.0 / 10.8 |
| offset down | 2.9 | 2.0 | 4.6 / 17.3 | 7.7 / 10.9 | 4.6 / 5.4 |
| tilt −15° | 3.3 | 2.6 | 4.5 / 16.7 | 7.5 / 11.8 | 6.1 / 8.6 |
| tilt +15° | 6.2 | 2.0 | 6.2 / 28.6 | 10.0 / 17.6 | 4.4 / 12.0 |
| corner down-right | **31.9** | 4.1 | 18.8 / 113.9 | 13.8 / 45.0 | 8.8 / 32.7 |
| corner up-left | 12.6 | 3.2 | 6.8 / 22.4 | 10.5 / 26.4 | 5.6 / 24.5 |
| corner up-right | 5.5 | 2.9 | 6.1 / 23.6 | 8.7 / 11.9 | 5.1 / 9.2 |
| corner down-left | 6.9 | 4.7 | 8.5 / 48.2 | 9.3 / 23.6 | 8.7 / 22.9 |

**cc1717-man-with-tattoos-standing**

| Pose | Shift p99 A | Shift p99 anch. | ΔE mean / tone p99 A (chart) | ΔE mean / tone p99 A | ΔE mean / tone p99 anch. |
| --- | --- | --- | --- | --- | --- |
| identity | 36.0 | 11.7 | 23.0 / 114.3 | 13.5 / 70.5 | 10.1 / 26.1 |
| scale 0.80 | 24.6 | 9.1 | 22.2 / 111.3 | 13.6 / 67.8 | 8.9 / 16.8 |
| scale 1.10 | 25.0 | 16.0 | 16.8 / 100.8 | 11.7 / 60.5 | 10.4 / 38.4 |
| offset left | 28.8 | 12.6 | 18.9 / 105.1 | 11.9 / 69.8 | 9.2 / 29.4 |
| offset right | **60.2** | 11.4 | 29.6 / 121.1 | 14.0 / 65.7 | 8.5 / 37.5 |
| offset up | 31.3 | 11.7 | 20.7 / 105.0 | 12.8 / 60.2 | 8.8 / 22.0 |
| offset down | 23.0 | 14.6 | 16.6 / 107.6 | 11.4 / 63.7 | 9.3 / 29.7 |
| tilt −15° | 56.3 | 10.1 | 25.2 / 108.7 | 14.2 / 76.2 | 9.3 / 26.9 |
| tilt +15° | 26.1 | 7.3 | 17.9 / 97.2 | 12.0 / 59.3 | 8.3 / 22.2 |
| corner down-right | 23.4 | 17.9 | 14.7 / 76.1 | 10.8 / 57.6 | 9.6 / 33.7 |
| corner up-left | 39.1 | 12.9 | 16.2 / 91.3 | 10.9 / 44.9 | 8.9 / 24.2 |
| corner up-right | 46.3 | 18.3 | 21.1 / 98.2 | 11.9 / 63.9 | 9.3 / 25.5 |
| corner down-left | 41.8 | 20.4 | 22.3 / 118.1 | 13.0 / 64.5 | 9.4 / 26.5 |

**cc1717-woman-with-oversize-fit**

| Pose | Shift p99 A | Shift p99 anch. | ΔE mean / tone p99 A (chart) | ΔE mean / tone p99 A | ΔE mean / tone p99 anch. |
| --- | --- | --- | --- | --- | --- |
| identity | 23.1 | 12.8 | 20.1 / 100.7 | 13.8 / 39.2 | 12.4 / 30.7 |
| scale 0.80 | 16.9 | 8.1 | 17.3 / 70.3 | 14.1 / 40.4 | 10.3 / 21.5 |
| scale 1.10 | 31.0 | 16.7 | 23.7 / 115.2 | 13.7 / 44.5 | 11.5 / 32.1 |
| offset left | **51.6** | 25.1 | 26.0 / 105.7 | 15.2 / 54.0 | 12.0 / 37.2 |
| offset right | 32.6 | 10.9 | 24.7 / 112.3 | 15.2 / 50.1 | 11.8 / 24.9 |
| offset up | 20.4 | 13.9 | 17.8 / 88.1 | 13.5 / 29.4 | 11.7 / 23.1 |
| offset down | 28.1 | 19.6 | 25.9 / 122.1 | 13.7 / 47.7 | 12.7 / 37.7 |
| tilt −15° | 42.9 | 13.2 | 19.3 / 80.1 | 14.6 / 56.4 | 11.4 / 35.9 |
| tilt +15° | 41.8 | 17.2 | 25.2 / 115.7 | 14.1 / 61.6 | 11.4 / 28.6 |
| corner down-right | 36.0 | 12.6 | 26.8 / 119.6 | 13.4 / 50.4 | 11.1 / 27.9 |
| corner up-left | 34.3 | 17.2 | 21.2 / 105.1 | 14.2 / 56.3 | 12.8 / 30.4 |
| corner up-right | 27.2 | 11.7 | 15.9 / 89.7 | 13.4 / 47.3 | 9.4 / 29.3 |
| corner down-left | 40.0 | 18.9 | 14.7 / 58.4 | 13.7 / 50.9 | 11.3 / 41.2 |

Worst option A shift per template: hanging-on-fence 31.9 px (corner
down-right), man-with-tattoos 60.2 px (offset right), woman-oversize-fit
51.6 px (offset left). With anchoring: 4.7, 20.4 and 25.1 px.

### Pictures

Each picture shows direct fit | option A | ΔE heat map (0–10).

![Hanging on fence, identity, chart: option A matches apart from 1–3 px line offsets](PENDING:cc1717-hanging-on-fence-identity-chart.png)
![Hanging on fence, corner down-right, chart: the worst flat-shirt pose, where the print runs onto the sleeve](PENDING:cc1717-hanging-on-fence-corner-down-right-chart.png)
![Man with tattoos, identity, ruler: option A shifts and bends the grid at the template's own box](PENDING:cc1717-man-with-tattoos-standing-identity-hike.png)
![Man with tattoos, identity, chart, anchored variant: most of the shift removed, a few-pixel residual](PENDING:cc1717-man-with-tattoos-standing-identity-chart-anchored.png)
![Woman oversize fit, offset left, chart: the drape on the left is rendered differently](PENDING:cc1717-woman-with-oversize-fit-offset-left-chart.png)
![Woman oversize fit, offset left, chart, anchored variant](PENDING:cc1717-woman-with-oversize-fit-offset-left-chart-anchored.png)
![Published maps vs option A at the template box, man with tattoos, ruler](PENDING:cc1717-man-with-tattoos-standing-published-vs-option-a-hike.png)

The harness writes the same three-panel picture for every template, pose and
design (and an `-anchored` twin), 162 in all.

## Garment-edge observations

- **Padding leaves the flat front on the worn shirts.** The padded quad is 93%
  garment on the hanging shirt but only 81% on both worn shirts, where it
  reaches the arms, the sleeves and the background. The posed boxes themselves
  stay 96–100% on garment. The misregistration is therefore not the print
  running off the shirt. It is the padded fit's single surface being shaped by
  cloth the print never touches.
- **It is not only off-garment cloth.** A diagnostic run, not part of the
  harness, padded to half the default limits, where the padded quad stays
  97–100% on garment. Shift p99 at identity was already 37 px (man) and 31 px
  (woman), against 3.4 px for the hanging shirt. The 49 × 49 fitting mesh
  spreads over a 1.55× larger area, so it is coarser over the print. It also
  flattens folds, such as the woman's left-side drape and the man's chest
  creases, in a different global frame.
- **Most of the error is a frame offset.** Anchoring the affine at the posed
  box corners cuts the worn-shirt shift p99 from 23–60 px to 7–25 px. Removing
  a best-fit global affine in the diagnostic left 7–11 px at default limits:
  bending that no single affine undoes. This residual is near the evidence
  noise floor (8.5 and 11.2 px p99), but tone p99 with anchoring (17–41 ΔE)
  stays one-and-a-half to three times the floor's (12 and 21).
- **Lighting is not the cause.** Renormalising the lighting gains over the
  posed print moved tone p99 by less than 1 ΔE everywhere. The tone differences
  come from geometry: thin lines and fold shading land in different places.
- **On the flat shirt, the corner poses fail.** Corner down-right (31.9 px)
  pushes the print over the right sleeve seam. There the padded fit, which also
  spans the sleeve and the fence, drapes it differently from a direct fit.
  Anchoring brings it to 4.1 px, but tone p99 stays 33 ΔE at the sleeve fold.
- **Both renderings look plausible on their own.** No option A composite looks
  broken. The prints still follow the cloth, and a buyer would not notice
  without the direct fit beside it. The gate as written is "match a direct
  fit", and on worn shirts option A does not.

## Recommendation

**Option A as specified: fail.**

1. On both worn templates, which most templates are likely to be, the padded
   fit misregisters the artwork by 23–60 px p99 (2–7% of the print width),
   including at the template's own box. That is three to four times the
   difference between two legitimate fits of the same box.
2. Even the flat template fails at the combined corners (31.9 px).
3. Timing passes: a padded fit or refit takes 1.5–3.2 s on the CPU. But
   adopting option A needs one inference run per template (about 1.5–2 min),
   and later limit widening can need another. That contradicts the spec's
   inference-free refit unless the evidence is a full-photo crop.

If the seller fails the spike, the plan already applies: PR 7 is dropped and
validation rule 5 (Marigold templates refuse positions) stays.

**Possible re-scope, for the seller to decide, not recommended as is.** The
anchored affine (four UV samples at the posed corners) is cheap. It brings
the flat template within 5 px everywhere and the worn templates to 7–25 px,
close to the evidence noise floor. It still fails the gate's tone criterion at
the extremes. If the seller judges the anchored pictures acceptable by eye, a
follow-up spike could test anchored option A with full-photo evidence and,
possibly, a denser mesh for the padded fit. That would be a spec change and
needs its own sign-off; this report does not establish it.

## Reproducing

1. Copy the three `mockup-templates/<name>/` folders into an empty directory
   with a `shop.yaml` (the fixture's will do).
2. Install Marigold (`etsy-listings marigold setup`).
3. Run the command under [Method](#method). The first run infers three roles
   per template; later runs reuse
   `<workspace>/.cache/spike-evidence/<template>/` and are deterministic.
4. Keep the workspace path short on Windows. The harness opens map archives by
   absolute path, and a deep temp directory exceeded the 260-character path
   limit.

Output: `results.json` (every number above) and the PNGs, in `--out`.
