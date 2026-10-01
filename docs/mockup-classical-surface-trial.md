# Classical surface and fold trial (throwaway)

Question: can a blank photograph produce useful print geometry with four placement
corners and a few quick corrections, instead of manually authoring a displacement
template? This experiment is separate from the production renderer and does not
change any PRD decision, listing, template YAML, or dependency pin.

## Run

From this checkout in Cygwin zsh, with the project dependencies installed:

```sh
PYTHONPATH=src uv run --no-sync python scripts/prototype_surface.py \
  --root C:/Users/Admin/Desktop/try-workspace \
  --template cc1717-hanging-on-fence \
  --colour pepper \
  --samples C:/Users/Admin/Desktop/try-workspace/.cache/surface-fold-trial-2026-10-01/samples.json \
  --design C:/Users/Admin/Desktop/try-workspace/designs/coding-x-music-master-of-packets.png \
  --port 8770 --start-sample 2
```

Open <http://localhost:8770>. The three reconstructed blanks, trial manifest, maps,
and image exports live in the user workspace, outside this repository. The
manifest is specific to this trial and is not committed. Omit `--samples` to use
just the genuine blank. Omit `--design` to use the procedural landscape artwork.
`--photo <path>` accepts another blank without requiring a production template.
All user path arguments accept native Windows or Cygwin paths.

This worktree's Python dependencies were installed with
`uv sync --frozen --no-install-project`. A normal editable installation attempted
the unrelated frontend build and failed when native Python launched npm. The
command above bypasses that build and uses this checkout's `src` directly.

## What to try

1. Start with the fence photo. Its existing four corners are loaded directly from
   the workspace template. The worn-shirt presets have initial corners supplied
   for this experiment; automatic garment segmentation/placement is not implemented.
2. Compare **Quad + local lighting**, **Broad surface**, and **Surface + folds**.
   These share artwork filtering, illumination, and visibility. Their differences
   isolate geometry. **Current renderer** uses the selected production template's
   settings (the default RenderConfig for standalone photos).
3. Switch to the white grid to inspect line curvature and circle shape. Switch
   back to a real RGBA design to judge whether the distortion helps the mockup.
4. Drag placement corners if necessary. Brush out overlapping hands, necklaces,
   or clothing. Candidate numbers let you disable suspect fold regions without
   tracing individual folds. The moss preset includes an initial arm mask.
   Mesh detail defaults to 49×49; 33×33 and the original 17×17 are available for
   comparison. Switching photos now retains each photo's corners, mask, and
   controls in memory. A server restart still requires an exported calibration.
5. If the broad estimate is implausibly flat, turn off automatic curvature and
   make one small adjustment. The batch experiment also tried curve `0.2` and
   relief `0.09`, unchanged across all three worn shirts. These are hypotheses,
   not recovered measurements or recommended production settings.
6. Download the full-resolution PNG and reusable `.npz` map. Reload the map on
   the same photo and change artwork. A different photo is rejected by its pixel
   hash. Changing calibration controls replaces the imported map with a new fit.

The session timer includes idle time. It is a convenience for a future authoring
trial, **not a measurement of active calibration effort**. No user timing study
has been performed.

## Implementation being evaluated

The print quad is rectified to a 256px crop. A multiscale Hessian identifies
elongated brightness structures after texture suppression. A smooth least-squares
fit uses those regions as weak relief constraints on a 49×49 surface. The broad
component is a cylindrical height profile; its automatic amplitude comes from
coarse cross-shirt lighting. A stress-minimizing flattening solve turns surface
edge lengths into material UV coordinates. Triangle interpolation bakes a
photo-to-artwork map. A foldover guard blends towards a neutral map if needed.
The fit and flattening use a sparse graph and preconditioned conjugate gradients,
avoiding a dense inverse when increasing mesh detail. Weak connected regions grow
from strong detector seeds. Relief is not forced to zero at the print boundary,
because a print quad crops an interior part of the cloth.

Visibility and normalized local illumination are separate arrays. Artwork is
filtered in premultiplied linear color before resampling, preventing hidden RGB
fringes and reducing fine-artwork aliasing. Linear-light illumination can shade
white ink. Pixels outside visible artwork remain byte-identical to the blank.

The saved artifact contains full-resolution material coordinates, visibility,
illumination, calibration controls, format revision, and source-photo hash.
Artwork changes reuse the fitted geometry; they do not rerun fold detection or
surface optimization. It is an experimental interchange format, not a production
template schema. Full-resolution maps are baked from the preview's fitted mesh,
so preview and export use the same calibration.

## Initial observations, 2026-10-01

These initial numbers describe the original 17×17 detector/fit, before the
finer-mesh revision below.

Four cases were exercised with the workspace's **Master of Packets** artwork,
followed by the white grid:

| Case | Source | Auto curvature | Default max UV shift | Fold candidates |
|---|---|---:|---:|---:|
| Fence / pepper | Genuine blank | 0.000 | 0.085% | 5 |
| Espresso worn | AI reconstructed blank | 0.000 | 0.193% | 6 |
| Pepper worn | AI reconstructed blank | 0.008 | 0.075% | 7 |
| Moss worn | AI reconstructed blank | 0.034 | 0.078% | 6 |

The automatic geometry is nearly flat in these trials. Visual improvements over
the current renderer are mainly due to local lighting; these results do **not**
establish a convincing automatic fold-geometry advantage. The two-control trial
makes a larger deformation available without individual fold tracing, but its
physical correctness still requires visual judgment.

With the same two overrides on each worn shirt, maximum UV shifts increased to
1.59% (espresso), 1.10% (pepper), and 1.35% (moss). All three adjusted cases also
passed both full-resolution artwork roundtrips with no flipped triangles. The
grid makes the deformation visible; this is still a shallow smooth model, not a
reconstruction of the pulled hem or deep folds.

The generated blanks successfully removed the prints but also reconstructed
cloth texture and some folds. They are useful stress tests of rendering and
authoring, not ground truth for the original photographs. Their lower-right
labels were retained. The genuine fence photograph is the independent control.

Default geometry runs had no flipped triangles. Full-resolution PNG bytes were
identical after map export/reload for both artworks on all four photos. Numerical
smoke checks also verified neutral UV identity, unchanged outside pixels, hidden
transparent-color isolation, deterministic output, white-ink shading, and
non-inverted maps at bounded control extremes. Those extreme checks use a flat
synthetic input; the photo trials provide the textured cases.

The repository's `scripts/check.sh` also passed: formatting/lint, source type
checks, the Python suite and coverage gate, and frontend lint/type checks plus
997 frontend tests and its coverage gate. Repository browser tests skipped where
the production SPA build was absent. The separate trial was opened in the T3
preview and its rendered PNGs decoded successfully; this is not a substitute for
a timed user calibration study.

The final default fit and four-preview render times were roughly 1.6–1.8 seconds
in the recorded batch, excluding artwork upload/premultiplication and full-size
export. Runtime depends on photo/design sizes and competing workloads.

## Evidence and next decision

The local trial folder contains `final/verification.json`, per-photo comparison
JPEGs, individual preview/full-resolution PNGs, grids, and reusable calibrations.
`adjusted/` contains the separate two-control trial. Re-run the batch against the
running server with:

```sh
PYTHONPATH=src uv run --no-sync python scripts/prototype_surface_verify.py \
  --port 8767 --output C:/path/to/scratch \
  --design C:/path/to/design.png
```

For the second trial append `--sample 1 2 3 --curve 0.2 --relief 0.09` and choose
another output directory. The verifier mutates the server's in-memory sample and
artwork selection; use it while nobody is interacting with the page. It restores
the fence and supplied artwork afterward.

## Finer mesh revision after the pepper trial

The user reported a missed upper-right-to-lower-left ripple and poor lower-left
deep folds. A focused, synthetic Lambertian-surface loop reproduced weak-feature
rejection and edge-fold attenuation at the original default relief setting:

```sh
PYTHONPATH=src uv run --no-sync python scripts/debug_surface_features.py --mesh 49
```

The original loop failed: only 22.2% of the gentle band had detector support, and
the deep edge fold retained 17.5% of its known height variation, producing 0.23%
maximum material shift. These thresholds check whether a feature is suppressed;
they are not a physical-accuracy acceptance test for real photographs.

Growing weaker connected pixels from strong seeds improved gentle-band coverage
to 36.0%. Removing the artificial zero-height constraint at the **print** boundary
made the deep response substantially stronger. Increasing mesh resolution then
retained more detail:

| Corrected mesh | Deep relief response ratio | Maximum UV shift | Two synthetic checks |
|---|---:|---:|---:|
| 17×17 | 41.6% | 1.54% | 0.17 s |
| 33×33 | 55.5% | 3.41% | 0.43 s |
| 49×49 | 62.2% | 4.78% | 1.05 s |

All three pass the focused checks with no flipped cells. The ratio is variation
retained in this particular fixture, not a claim that the model recovers 62% of
arbitrary cloth depth. The same brightness-to-height proxy can overestimate the
gentle fixture's relief, so passing does not resolve the depth ambiguity.

The new default is 49×49 (2401 vertices versus the original 289). An isolated
four-photo batch passed full-resolution map roundtrips with both artworks and no
flipped cells; fit plus four previews took 1.7–1.9 seconds in the recorded runs.
Artifacts are under `finer-mesh/` beside the original trial results. The revised
pepper grid bends more strongly into the creases, but correctness of the gentle
ripple and deep cloth geometry still needs visual evaluation. Self-occlusion and
hidden cloth remain outside this height-field model.

The updated interactive instance uses port 8770. The original port 8767 instance
was left running during diagnosis to preserve the user's live calibration. Use
an isolated port for batch verification. `--controls <state.json>` can initialize
the updated trial from a captured `/state` response; its active photo index is
reused unless `--start-sample` is supplied explicitly.

Current verdict: **the deterministic render/export path is feasible; the goal of
better geometry with automatic calibration remains unproven**. If a few control
adjustments do not produce a clear visual win, improve the surface prior or test
the normal-assisted prototype rather than spending hours tuning fold brightness.
Single-image lighting does not identify physical depth, and this model cannot
represent hidden cloth, self-occlusion, or sharp overhanging folds.

Primary artifacts: `scripts/prototype_surface.py`, `scripts/prototype_surface_math.py`,
`scripts/prototype_surface.html`, and `scripts/prototype_surface_verify.py` on the
throwaway `t3code/60d351b5` working branch. No production integration is implied.
