# Marigold garment trial (throwaway)

Implemented from [the handoff](mockup-marigold-handoff.md), on native Windows,
2026-10-01. This is an independently runnable experiment under `docs/research/marigold-20261001/prototype/`.
Production rendering, template YAML, listings, and dependency pins are unchanged.
The classical trial remains independently runnable.

The interactive reviewer is at <http://localhost:8773>. The exported comparison
gallery is `C:/Users/Admin/Desktop/try-workspace/.cache/marigold-trial-2026-10-01/review/index.html`.

The prototype answers whether learned normals and illumination make supplied art
follow a photographed garment better with a short calibration. It now supplies
cached model evidence, a geometry solver, explicit discontinuous patch corrections,
photographic compositing, a review viewer, reusable maps, and controlled comparisons.
It does **not** establish that real deep cloth folds have been reconstructed
correctly. The final realism verdict and active authoring time require user review.

## Native Windows feasibility

All three exact baseline models completed inference on the RTX 3070 (8 GB), with
native CPython 3.12.14, PyTorch 2.8.0+cu128 and CUDA 12.8. No WSL was used.
FP16, batch size one, model CPU offloading, and VAE tiling kept peak PyTorch
allocation between 1,952 and 1,989 MiB. These numbers exclude desktop applications,
driver allocations and host RAM. NVIDIA initially reported 2,107 MiB occupied;
PyTorch's available-memory accounting under WDDM differed.

| Model | First GPU call after loading, seconds | Subsequent default calls, seconds | Subsequent ensemble calls, seconds |
| --- | ---: | ---: | ---: |
| Normals | 21.1 default / 24.8 ensemble | 3.2–3.8 | 6.0–6.9 |
| IID Lighting | 22.0 default / 25.0 ensemble | 3.9–5.3 | 7.2–8.9 |
| Depth | 17.0 default / 21.6 ensemble | 3.0–3.2 | 6.3–9.9 |

Those are measured calls with cached weights, not download or process-start times.
The initial repeated-photo smoke test measured 4.2 / 4.2 / 3.4 seconds for warm
Normals / Lighting / Depth. Each raw prediction records its own load time,
inference time, peak allocated/reserved VRAM, package versions and transforms.
Depth ensembling required SciPy in addition to the basic Diffusers dependencies.

Checkpoint revisions are pinned in the worker, rather than depending on future
changes to model repository heads:

| Checkpoint | Revision |
| --- | --- |
| `prs-eth/marigold-normals-v1-1` | `09cfdd258cb281fa006cf1afcd2284376d16687d` |
| `prs-eth/marigold-iid-lighting-v1-1` | `08c3930bb641abf786ba44ce92547507ebefbc16` |
| `prs-eth/marigold-depth-v1-1` | `9571e7123e258cf052b4e54241f17971c290e9a8` |

The worker requirements pin Diffusers 0.35.1, Transformers 4.56.2, Accelerate
1.10.1, Hugging Face Hub 0.35.1, NumPy 2.2.6, Pillow 10.4.0, Safetensors 0.6.2
and SciPy 1.16.2. The CPU reviewer uses the existing repository environment and
its OpenCV/Pillow pins. Only the isolated authoring worker imports PyTorch.

The task-specific pipelines and output semantics follow the
[official Diffusers examples](https://huggingface.co/docs/diffusers/en/using-diffusers/marigold_usage).
Lighting returns `[3,H,W,3]`, ordered albedo, shading, residual, all linear; its
installed `target_properties` is explicitly checked. Normals return `[1,H,W,3]`
in the original camera frame. Depth returns `[1,H,W,1]`, affine-invariant near-to-far
depth. Raw floats and uncertainty are retained; visualizations are never solver inputs.

## Run the reviewer

From this checkout in Cygwin zsh:

```sh
PYTHONPATH=src uv run --no-sync python docs/research/marigold-20261001/prototype/prototype_marigold.py \
  --root C:/Users/Admin/Desktop/try-workspace \
  --samples C:/Users/Admin/Desktop/try-workspace/.cache/surface-fold-trial-2026-10-01/samples.json \
  --holdout-colour ivory \
  --output C:/Users/Admin/Desktop/try-workspace/.cache/marigold-trial-2026-10-01 \
  --design C:/Users/Admin/Desktop/try-workspace/designs/coding-x-music-master-of-packets.png \
  --port 8773 --start-sample 2
```

Open <http://localhost:8773>. The initial photo is pepper. Choose a diagnostic,
then compare the selected result with production or the classical method. Click
a comparison for full-size review. White, saturated colour, fine text and
transparent-edge targets expose failures that distressed art can hide.

Drag corners, exclude foreground with the brush, or restore a mistaken exclusion.
**Reset placement & corrections** restores the selected photo's original placement
and mask (including its supplied exclusions), clears patches and anchors, and
returns to Corners mode. It keeps depth, illumination, texture, highlights and
the loaded artwork. Reset refits from cached predictions and replaces an imported map.
For an actual overlap, click around a visible patch and finish it. Its U/V offset
represents a hidden material interval in the shared artwork plane. Larger patch
order is frontmost. This is a corrective prior, not an inferred cloth measurement.
An anchor pairs a clicked photo pixel with a desired canonical U/V position.
Orientation barriers and residual anchor error appear in the diagnostics.

Download the full-resolution PNG and `marigold-garment-v1.npz`. Reload that map
and replace artwork. The map stores full-resolution float32 material coordinates,
visibility, linear RGB gain, texture and residual, int32 patch IDs, editable
controls, diagnostics and inference provenance. Loading uses `allow_pickle=False`
and rejects wrong photos, shapes, types, non-finite fields and invalid ranges.
Accepted numeric fields and render settings have their own identity; provenance
and timestamps do not enter it.

To demonstrate GPU-independent reuse, start a fresh reviewer with
`--calibration <saved-map>` and `--output <a nonexistent cache directory>` on the
same selected photo. It renders the accepted map and new artwork without loading
predictions or importing a GPU library. Refit requires cached predictions again.

## Reproduce inference in a fresh native worker

Weights, photos, caches and exports must stay outside the repository. Example
setup uses the same experimental folder as the measured trial:

```sh
uv venv --python 3.12 C:/Users/Admin/Desktop/try-workspace/.cache/marigold-trial-2026-10-01/worker-env
uv pip install --python C:/Users/Admin/Desktop/try-workspace/.cache/marigold-trial-2026-10-01/worker-env/Scripts/python.exe \
  torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python C:/Users/Admin/Desktop/try-workspace/.cache/marigold-trial-2026-10-01/worker-env/Scripts/python.exe \
  -r docs/research/marigold-20261001/prototype/prototype_marigold_requirements.txt

PYTHONPATH=src uv run --no-sync python docs/research/marigold-20261001/prototype/prototype_marigold_inputs.py \
  --root C:/Users/Admin/Desktop/try-workspace \
  --samples C:/Users/Admin/Desktop/try-workspace/.cache/surface-fold-trial-2026-10-01/samples.json \
  --holdout-colour ivory \
  --output C:/Users/Admin/Desktop/try-workspace/.cache/marigold-trial-2026-10-01

/cygdrive/c/Users/Admin/Desktop/try-workspace/.cache/marigold-trial-2026-10-01/worker-env/Scripts/python.exe \
  docs/research/marigold-20261001/prototype/prototype_marigold_worker.py \
  --jobs C:/Users/Admin/Desktop/try-workspace/.cache/marigold-trial-2026-10-01/jobs.json \
  --output C:/Users/Admin/Desktop/try-workspace/.cache/marigold-trial-2026-10-01
```

Repeat the final worker command with `--quality ensemble`; use `--smoke` for two
successive calls on the first photo. The native worker protocol takes native
Windows paths. Repository input/reviewer/verifier options also accept Cygwin
paths through `Workspace`'s path conversion. Model settings are global: default
four steps / one member, or ten steps / three members with uncertainty, fixed
seed 2026, processing resolution 768. No per-photo model selection or tuning.

The unwarped contextual crop extends 40% beyond the existing print quad on each
axis, clipped to the source. Resize dimensions, VAE padding and original crop
origin are stored. Model predictions are sampled in original photo coordinates;
resampled normals are renormalized. The cache includes source pixels, crop,
checkpoint revision, settings, execution configuration and package versions.
Artwork and placement corrections do not trigger inference. If placement leaves
the cached crop, the reviewer asks for more contextual evidence.
Cache hits reactivate the exact requested archive and retain its original measured
runtime. Output-writing commands resolve paths before refusing repository descendants,
including relative paths and `..` segments.

Marigold's code is [Apache-2.0](https://github.com/prs-eth/Marigold/blob/main/LICENSE.txt);
the baseline weights have [CreativeML Open RAIL++-M terms](https://huggingface.co/prs-eth/marigold-iid-lighting-v1-1).
No model weights are committed or distributed with these scripts.

## Geometry and appearance being evaluated

Normals constrain `dz/dx = -Nx/Nz`, `dz/drow = +Ny/Nz` under an orthographic
initialization. A weighted graph solve with uncertainty, three robust residual
reweightings and weak smoothness fits an integrable height field. Boundary height
is free. Near-grazing normals are downweighted and reported. Explicit patch
boundaries cut integration and flattening edges. Relative depth is scale/offset
fitted into that same frame and used as a weak broad constraint.

A stress-minimizing 49×49 mesh preserves surface edge lengths, with a weak
placement prior and orientation barriers. One global material frame uses the
four placement corners. Patches are not separately normalized. Baking avoids
interpolating displacement across different patch IDs and applies explicit hidden
intervals in canonical U/V. Unsupported patch support is visible in the mask.
Mesh labels use nearest-neighbour sampling. Preview resampling and texture-footprint
derivatives stay inside each patch, preserving sharp hidden-material discontinuities.
Diagnostics distinguish fitted edge strain from strain after frame normalization
and corrective anchors; neither is a realism score. There is no blend-to-flat
foldover guard.

The RGB ink colour is shaded in linear light using a garment-relative gain;
garment albedo is not multiplied into ink. Normalization uses the 70th percentile
of shading luminance on confident visible cloth inside the placement. High-frequency
photographic texture is bounded to 0.9–1.1 and affects reflectance, not opacity.
Residual transfer starts off and is bounded to 0.035 before its strength control.
Derivative-selected mip filtering uses premultiplied linear alpha. Pixels outside
visible artwork remain byte-identical to the blank. Preview fields use the same
baked calibration with explicit half-pixel resize conventions.

## Evidence and provisional choices

The local `review/index.html` gallery exports the controlled matrix: production,
classical and normals with shared photographic lighting; photographic versus IID
lighting on fixed normals; normals versus normals plus depth; texture off versus
restrained transfer; and complete results against the original methods. Real art
and the grid use every method. Five additional diagnostic targets use the selected
pipeline. `blind-review.html` hides method names; `blind-key.json` reveals them.
`review/evidence/index.html` compares default and ensemble normals on unwarped
photo crops; its JSON includes all inference runtimes and uncertainty percentiles.

Default versus ensemble mean normal changes were 4.5° on fence, 5.3° on espresso,
6.2° on pepper, 5.5° on moss and 3.9° on ivory. That disagreement establishes
that settings matter; it does not prove which prediction is physically correct.
The ensemble is the provisional shared default because it permits uncertainty
weighting at an acceptable unattended cost. The pepper diagonal and lower folds
are present as broad changes in the normals, but fine texture and sharp crease
topology are not recovered at this effective resolution.

The provisional complete pipeline is normals, IID lighting, texture 0.25 and
residual off. Depth remains available for controlled evaluation but is off in
the selected result: the initial comparison made small mapping changes without
establishing a deep-fold advantage. These are experiment defaults, not a user
approval of quality. A user can compare appearance options, but never selects a
checkpoint per photo. IID Appearance was deliberately deferred.

Foreground masks are seeded GrabCut proposals through a separate adapter, with
the existing moss arm polygon retained. They need inspection around hair, chains
and similarly coloured clothing. Self-overlap is not automatically solved. The
viewer supports discontinuous corrections, and synthetic checks verify a known
hidden interval and front order, but uncertain real folds remain explicitly
unresolved until corrected. The ivory holdout is another genuine blank from the
same hanging-shirt setup; it is not an independent worn-garment validation set.

`review/corrected-pepper/` records one browser-authored split over the lower-left
fold region, with an illustrative U offset of 0.04. Its map, controls, diagnostics
and four artwork exports exercise corrective reuse. The interval is a declared
prior; this example does not prove the photographed fold's hidden material length.

No active-time study was performed. Presets were reused; automatic inference and
batch exports were unattended. Pointer interaction timing in the viewer excludes
reading and retries, so it cannot establish the proposed five-minute target or
ten-minute cutoff. Per-dimension realism scores remain blank for user review.

## Verification commands

```sh
PYTHONPATH=src uv run --no-sync python docs/research/marigold-20261001/prototype/prototype_marigold_verify.py
```

Checks cover coordinate sign/physical scale, flat/tilted/cylinder/ripple mappings,
non-inverted visible triangles, fitted affine depth, grazing refusal, corrective
anchors, frontmost patch order and known hidden material, white-ink shading,
transparent RGB isolation, preserved outside pixels, exact saved-map rendering,
photo mismatch rejection and replacement artwork without GPU imports. Analytical
height error is under 0.003 placement-width units; planar U/V error under 0.004;
curved arc-length U/V error under 0.025 (observed under 0.0013).
Regression checks also cover A/B/A cache selection, relative output-path rejection,
discrete patch labels, preview discontinuities and sharp texture filtering at splits.

For exports, run a second reviewer at `--port 8775`, then:

```sh
PYTHONPATH=src uv run --no-sync python docs/research/marigold-20261001/prototype/prototype_marigold_verify.py \
  --url http://localhost:8775 \
  --cache C:/Users/Admin/Desktop/try-workspace/.cache/marigold-trial-2026-10-01 \
  --output C:/Users/Admin/Desktop/try-workspace/.cache/marigold-trial-2026-10-01/review
```

The batch intentionally changes that server's selected photo/artwork, so never
point it at the interactive reviewer. The five-photo run passed 35 exact
full-resolution PNG roundtrips and five mismatched-photo rejections. Browser
review used T3 preview for photo/diagnostic switching, brush correction and undo,
full-resolution decoding, artifact reload, artwork replacement and explicit overlap
authoring. The browser-authored map additionally passed four exact full-size artwork
roundtrips after the discontinuity fixes.

`scripts/check.sh` passed: Python lint/format/type checks, 2,579 pytest cases,
frontend formatting/lint/types, and 997 Vitest cases. Pytest skipped 104 cases and
deselected 62; browser tests skip when their built SPA/Chromium prerequisites are
absent. Existing Windows process-kill tests required the full check to run outside
the sandbox; no production code changed to accommodate that. Production integration
is a separate decision.
