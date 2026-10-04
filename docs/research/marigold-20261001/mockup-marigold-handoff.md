# Marigold garment mockup prototype: implementation handoff

Status: approach agreed with the user on 2026-10-01; implementation pending.
This document scopes the next experimental prototype, not production integration.
No Marigold checkpoint has been installed or evaluated in this thread.

## Goal and agreed approach

Make supplied artwork look physically printed on the photographed garment.
Evaluate the complete appearance: broad shape, wrinkles, deep creases, illumination,
fabric texture, print edges, and occlusion. More deformation alone is not success.

The user prioritizes output quality and minimal manual configuration. Technical
complexity and unattended processing are acceptable. A few placement or mask
adjustments are acceptable; hours calibrating each template are not. Changing
artwork on an approved photo must require no recalibration.

Implement **Marigold Normals + Marigold IID Lighting**, a custom geometry/mapping
solver, explicit visibility handling, and a deterministic photographic compositor.
Evaluate **Marigold Depth** as an additional geometry constraint in a controlled
comparison. Retain depth if it improves results; do not make the user choose models
or tune their settings per photo. IID Appearance is a later material experiment,
not a substitute for the core geometry and lighting components.

Keep the original blank photograph as the background and the supplied artwork as
the print source. Model inference estimates calibration fields; it does not
regenerate the finished mockup or redraw the artwork.

## Starting point and evidence

The classical trial is implemented on branch `t3code/60d351b5`, in commits
`33a553ef` and `7bedc4a5`. The user judged it better than the production renderer,
but insufficiently convincing, especially around deep creases. Their clarified
goal is overall print integration, not only crease recovery.

Read [the classical trial](mockup-classical-surface-trial.md) for commands and
measured results, and [model feasibility](mockup-prototype-model-feasibility.md)
for earlier model research. This handoff supersedes the earlier normals-only
emphasis for the next prototype. Those research notes are not production authority;
the PRD and implementation plan retain their existing roles.

| Existing file                         | Reuse or replace                                                                                                                     |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `docs/research/marigold-20261001/prototype/prototype_surface.py`        | Reuse photo/artwork loading, local API, controls, caching and export pattern.                                                        |
| `docs/research/marigold-20261001/prototype/prototype_surface.html`      | Reuse comparison viewer, artwork switching, placement corners, mask brush and full-size review.                                      |
| `docs/research/marigold-20261001/prototype/prototype_surface_math.py`   | Reuse linear colour conversion, premultiplied sampling and numerical helpers where appropriate. Replace brightness-derived geometry. |
| `docs/research/marigold-20261001/prototype/prototype_surface_verify.py` | Adapt numerical checks, batch gallery and saved-map roundtrip verification.                                                          |
| `docs/research/marigold-20261001/prototype/debug_surface_features.py`   | Reference for known synthetic folds; its existing thresholds measure sensitivity, not physical accuracy.                             |

The classical pipeline rectifies a print quad to 256 pixels, fits a 49×49 height
field from brightness structures, and flattens its surface edge lengths. That
brightness-to-height assumption remains ambiguous. Its single continuous height
field cannot represent cloth folding over itself. Increasing mesh detail improved
response but did not resolve those limitations.

Create separately named Marigold scripts/modules and artifact versions. Preserve
the classical method as an independently runnable comparator. Production render
passes, dependency pins, template YAML and listing behaviour remain unchanged
during this experiment.

## Photos, artwork and local environment

User workspace: `C:/Users/Admin/Desktop/try-workspace`.

Trial inputs and previous exports:
`C:/Users/Admin/Desktop/try-workspace/.cache/surface-fold-trial-2026-10-01`.

| Case                  | Input                                                                                               |
| --------------------- | --------------------------------------------------------------------------------------------------- |
| Genuine blank control | Template `cc1717-hanging-on-fence`, colour `pepper`; resolve the scene through `Workspace`.         |
| Espresso worn shirt   | Trial folder `espresso-blank-ai.png`; pulled hem and necklace.                                      |
| Pepper worn shirt     | Trial folder `pepper-blank-ai.png`; diagonal ripple, deep lower-left folds and hand/coat occlusion. |
| Moss worn shirt       | Trial folder `moss-blank-ai.png`; arm overlap and asymmetric pose.                                  |

`samples.json` in that folder contains the additional photo paths and normalized
placement presets. The moss preset includes an initial arm mask. Use the manifest
rather than reconstructing those controls from screenshots. Existing comparisons
are in `final/`, `adjusted/` and `finer-mesh/`.

The three worn-shirt blanks were AI edits of already printed photos. They also
reconstructed some cloth and texture: they are stress tests, **not ground truth**
for the original garment geometry. Score new renders against each reconstructed
blank's visible structure. Obtain a genuine worn blank before claiming accuracy
on real cloth. Do not overwrite any existing inputs or calibrations.

Use the white diagnostic grid/circles, procedural landscape, and real RGBA design
`designs/coding-x-music-master-of-packets.png`. Add solid white, saturated colour,
small text and sharp transparent-edge targets to distinguish appearance failures.
Ensure at least one diagnostic placement actually intersects each troublesome
crease; a design that misses a fold cannot establish that it is handled.

Run repository commands through **Cygwin zsh** as instructed in `AGENTS.md`.
The existing prototype can run without an editable installation:

```sh
PYTHONPATH=src uv run --no-sync python docs/research/marigold-20261001/prototype/prototype_surface.py \
  --root C:/Users/Admin/Desktop/try-workspace \
  --template cc1717-hanging-on-fence --colour pepper \
  --samples C:/Users/Admin/Desktop/try-workspace/.cache/surface-fold-trial-2026-10-01/samples.json \
  --design C:/Users/Admin/Desktop/try-workspace/designs/coding-x-music-master-of-packets.png \
  --port 8772 --start-sample 2
```

Dependencies previously used `uv sync --frozen --no-install-project`; see the
classical trial note for the unrelated editable-install frontend build failure.
Ports 8767 and 8770 were user-facing trial instances. Check current state before
using them, and run batch verification against an isolated instance: the verifier
changes the selected photo/artwork and can interfere with interactive calibration.

The machine has an RTX 3070, expected 8 GB VRAM. Confirm actual CUDA access and
available memory. Start with a separate inference environment, FP16, batch size
one, and one loaded model at a time; use CPU offloading if needed. Measure peak
VRAM, cold/warm runtime and successful settings on this machine. Hardware
feasibility remains to be verified, not promised.

Prefer a separate WSL2 GPU worker if available: the authors recommend WSL2 for
Windows. Keep repository orchestration in Cygwin; isolate worker dependencies
from the production environment. First inspect existing WSL/CUDA availability;
document a concrete blocker if host provisioning is needed. A tested native
Windows Diffusers worker is an acceptable alternative. [Official setup guidance](https://github.com/prs-eth/Marigold).

## Model roles and numerical contract

Use these explicit baseline checkpoints; record exact checkpoint revisions and
tested package versions. Recheck availability at implementation time, and document
any replacement rather than silently changing the experiment.

| Checkpoint                             | Role and constraint                                                                                                                                                                                                                               |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `prs-eth/marigold-normals-v1-1`        | Camera-space unit surface normals. Primary local geometry evidence; not UV coordinates or complete surface topology. [Model card](https://huggingface.co/prs-eth/marigold-normals-v1-1).                                                          |
| `prs-eth/marigold-iid-lighting-v1-1`   | Linear-space albedo, diffuse shading and non-diffuse residual, with decomposition `I = A*S + R`. Use for ink illumination, not garment-colour multiplication. [Model card](https://huggingface.co/prs-eth/marigold-iid-lighting-v1-1).            |
| `prs-eth/marigold-depth-v1-1`          | Affine-invariant relative depth, not metric distance. Fit its scale/offset consistently with the chosen geometry/camera. [Model card](https://huggingface.co/prs-eth/marigold-depth-v1-1).                                                        |
| `prs-eth/marigold-iid-appearance-v1-1` | Albedo, roughness and metallicity. Defer unless a measured material failure justifies additional rendering work. Its albedo is sRGB, unlike Lighting's linear outputs. [Model card](https://huggingface.co/prs-eth/marigold-iid-appearance-v1-1). |

Use task-specific Diffusers pipelines, not the generic image-generation snippets
sometimes displayed in Hugging Face's automatic usage panel. Save raw floating
predictions; colourized visualization PNGs are diagnostics only. Inspect the
installed pipeline's output layout and intrinsic property metadata explicitly.
[Official Diffusers usage](https://huggingface.co/docs/diffusers/main/en/using-diffusers/marigold_usage).

Normals convention: X right, Y up, Z toward the viewer; image rows increase
downward. Convert once into the solver's documented convention, and test the sign
conversion on known tilted planes. Resampled normals require renormalization.
Retain the original camera frame when mapping predictions into other coordinates.
[Normal coordinate convention](https://huggingface.co/docs/diffusers/main/en/using-diffusers/marigold_usage#surface-normals-estimation).

Predict on an **unwarped garment crop with surrounding context**, initially using
the roughly 768-pixel effective resolution documented for these models. Store crop,
resize and padding transforms. Avoid the classical 256-pixel bottleneck. A projective
rectification does not turn camera normals into normals in a new physical camera;
sample fields back into original image coordinates for the solver. Upsampling a
prediction does not recover missing wrinkle detail. [Normals resolution](https://huggingface.co/prs-eth/marigold-normals-v1-1).

Start with checkpoint defaults and a fixed seed. Compare a globally selected
higher-quality ensemble configuration against the initial run; request uncertainty
with at least three ensemble members. Disagreement is a weighting signal, not a
guarantee of accuracy. Keep model settings global, record them, and accept longer
unattended inference when it improves the result. [Ensembling and uncertainty](https://huggingface.co/docs/diffusers/main/en/using-diffusers/marigold_usage#using-predictive-uncertainty).

Inference cache identity includes source pixels, preprocessing, checkpoint
revision and inference settings. Placement/solver changes invalidate the mapping,
but artwork changes invalidate neither inference nor approved calibration.

## Implementation sequence and completion gates

### 1. Establish the inference worker and inspect its evidence

Produce normals, Lighting components, optional depth, and available uncertainties
for all four trial photos. Export aligned numerical arrays and an inspection
gallery over the original blanks. Propose a garment/foreground mask using a
separate segmentation adapter; Marigold does not provide segmentation. Existing
placement and brush masks are the initial fallback, and their manual cost counts.

Completion: all fields have validated dimensions, coordinate conventions, finite
values and provenance; a fresh command reproduces the cached-input workflow;
RTX 3070 runtime/memory is recorded. Inspect the pepper diagonal ripple and deep
folds before solver tuning. If predicted normals omit a visible crease, a denser
mesh cannot supply missing evidence; report that limitation and compare crop or
inference quality settings systematically.

### 2. Implement geometry-to-material mapping

Define `UV(x, y)` as the canonical artwork coordinate sampled at an original photo
pixel. Reuse four placement corners to establish print origin, orientation and
scale. They constrain intended placement, not four physical cloth boundaries.
Normals do not determine where the customer intends the print to sit.

Use a weighted integrable surface fit followed by near-isometric flattening as
the initial solver. A direct normal-constrained UV optimization is also acceptable
if synthetic checks and diagnostics establish its correctness. The
[Normal-guided Garment UV paper](https://arxiv.org/pdf/2303.06504) is an algorithm
reference: it relates normals to a surface-aware texture metric under orthographic
projection. Its checked project page does not supply a turnkey implementation.

For a visible height-field patch under an orthographic initialization, normals
constrain depth slopes through their component ratios. Express those constraints
in physical image-axis units with the correct row sign; preserve aspect and pixel
spacing. Fit an integrable field robustly rather than integrating each scanline
independently. Weight uncertainty, use weak smoothness and a conservative placement
prior, and measure residual disagreement. Near-grazing normals make ratios unstable:
flag or treat those regions separately instead of generating enormous UV offsets.

Flatten using surface-space lengths/metric, allowing measured strain where cloth
is not exactly developable. Retain orientation barriers and distortion diagnostics.
Initialize with 49×49 or adaptive comparable resolution, and refine only where the
evidence supports it. Avoid smoothing across identified discontinuities, forcing
height to zero at the print boundary, or independently normalizing every visible
patch into its own complete print rectangle.

Evaluate depth as a confidence-weighted broad surface constraint with fitted
scale/offset. Compare normals-only with normals-plus-depth using identical lighting
and placement. Do not directly add independent depth and normals fields. Test an
approximate perspective camera if orthographic fitting causes a visible systematic
error; expose the assumption in diagnostics rather than creating another manual
camera-calibration workflow.

Completion: known flat/tilted/cylindrical/ripple surfaces recover the expected
mapping within documented tolerances; valid visible cells remain non-inverted;
photo comparisons isolate geometry changes; all fallback/regularization effects
are reported. A foldover guard that flattens away the feature is not a quality win.

### 3. Represent foreground and cloth self-occlusion

Foreground exclusion (hand, arm, necklace, coat) and cloth self-overlap are separate
problems. Propose discontinuity/overlap boundaries from available image and model
evidence, then allow a brief split/visibility correction when ambiguous. A dark
line alone is not proof of a hidden cloth boundary.

Represent visible cloth patches with shared canonical material coordinates,
boundary relationships and front/back ordering. Allow a UV discontinuity where
hidden material lies between visible regions; keep ordinary wrinkles continuous.
Preserve the photograph's frontmost surface, and sample the corresponding material
region rather than merely painting out every dark crease. Use a discontinuous
inverse map or patch mesh/rasterizer where the continuous grid is inadequate.

One photo cannot uniquely recover hidden material or every patch offset. Use
explicit priors, diagnostics and occasional corrective anchors; flag unresolved
regions. Do not claim exact reconstruction from normals/depth alone. The reference
UV paper itself identifies self-occlusion as a limitation. [Paper limitations](https://arxiv.org/pdf/2303.06504).

Completion: a synthetic overlapping-cloth case preserves patch ordering and a
known hidden material interval; real crease/foreground examples show no artwork
bridging hidden cloth or leaking onto hands. Mark any unsupported real case clearly.
A prototype that only supports shallow continuous patches is an intermediate result.

### 4. Integrate lighting, texture and print edges

Treat sampled artwork RGB as the starting ink colour, not a measured BRDF. Apply
garment-relative illumination from the Lighting estimate in linear space. Derive
exposure normalization from confident visible cloth rather than the entire scene;
preserve crease shadows and plausible illumination colour. Estimate the model's
`A*S + R` reconstruction error on the blank as a diagnostic, not a proof of ink realism.

Start without residual transfer, then evaluate a restrained residual option.
Highlights/non-diffuse effects can change when ink covers fabric, so wholesale
transfer of `R` is not automatically correct. Compare controlled fine texture
derived from the original blank, separating it as far as possible from broad
illumination and dyed wash. Exclude hands/jewellery and avoid copying removed-print
ghosts. Retain enough texture for ink to sit in the weave without making opaque
artwork globally transparent or tinting white ink with the shirt's albedo.

Reuse premultiplied linear-alpha filtering. Evaluate antialiasing under compression
using local map derivatives or equivalent supersampling/prefiltering; preserve thin
text, transparency and sharp artwork edges. Match photographic sharpness conservatively
with a global print profile. Distressing or aged-print opacity should be explicit
style choices, not the mechanism that hides a bad mapping.

Completion: white ink receives shadows, colour remains recognizable, texture is
restrained, edges have no halos/jaggies, and the result remains convincing with
opaque high-contrast art. Pixels outside visible artwork are byte-identical to the
blank. Review at listing size and 100% resolution.

### 5. Build review, reusable export and controlled evaluation

Extend the trial viewer with geometry, shading, texture and visibility diagnostics.
Offer placement, a few corrective anchors, a mask/split correction and restrained
appearance adjustment. Propose initial calibration automatically using existing
placement when available. Keep numerical solver/model tuning out of the normal
review flow. Show uncertain regions and explicit fallback reasons.

Store a new versioned artifact. Minimum contract:

- Source pixel hash and dimensions; preprocessing/camera convention and transforms.
- Full-resolution float32 `material[H,W,2]`, normalized canonical artwork coordinates;
  `visibility[H,W]` in `[0,1]`; patch IDs and optional editable patch topology.
- RGB linear illumination gain and separately identified optional texture/residual
  fields, with declared normalization and bounded ranges.
- Placement/anchor/mask controls and diagnostics, including uncertainty support,
  strain, invalid/grazing areas and fallbacks.
- Checkpoint revisions and tested inference/solver settings as provenance.

Keep provenance separate from render-input identity: accepted numeric fields and
render settings determine deterministic output. Timestamps, absolute paths and
fresh model calls must not enter production input hashes. This is an experimental
artifact; production hashing/schema changes require their own design later.

Use safe non-pickled array loading, validate field shapes/ranges/finiteness and reject
a different photo. Bake full-resolution maps from the accepted geometry; derive
preview coordinates consistently with explicit pixel-centre conventions. A coarse
preview need not be pixel-identical to a downscaled final image, but it must show
the same placement, deformation and visibility. Save/reload must reproduce the
full-size render exactly on the same pinned environment. Changing artwork after
reload must work without GPU access or inference.

Build this comparison matrix, keeping photo, placement and artwork fixed:

| Comparison                                                          | Question                                                     |
| ------------------------------------------------------------------- | ------------------------------------------------------------ |
| Production vs classical vs normals, shared photographic lighting    | Does the mapping improve shape independently of lighting?    |
| Photographic vs IID lighting, fixed normals mapping                 | Does estimated illumination make the print sit in the cloth? |
| Normals vs normals+depth, fixed lighting                            | Does depth improve geometry enough to retain it?             |
| Texture/residual off vs restrained transfer, fixed geometry/shading | Which appearance components help without dirtying ink?       |
| Complete selected pipeline vs production and classical              | Is the finished mockup actually more convincing?             |

Score broad placement, ripple/crease alignment, deep-fold behaviour, illumination,
texture/edges and occlusion separately, then judge overall realism with real artwork.
Randomize/hide method labels for the final visual comparison where practical.
Record failures alongside successful photos; numeric strain or UV displacement is
not a substitute for the user's visual judgment.

Use the earlier **five minutes active work target / ten minutes cutoff per photo**
as proposed evaluation bounds, not achieved results. Count placement, mask edits,
anchors, retries and per-photo tuning; record idle and unattended inference time
separately. Globally tune on development photos, freeze defaults, then include
at least one additional genuine blank not used for tuning. Avoid claiming general
quality from the four development cases alone.

Completion: export an inspectable gallery, per-case raw predictions and approved
maps, a runtime/manual-effort record, reproducible commands, and a findings note
that identifies the selected depth/lighting/texture options and remaining failures.
The next agent must deliver a runnable prototype and evidence, not stop at model
visualizations or a plan. Production integration is a separate decision after review.

## Verification and repository boundaries

Add meaningful numerical checks for coordinate sign/scale, known geometry,
discontinuous patches, premultiplied-alpha isolation, white-ink shading, preserved
outside pixels, deterministic saved-map rendering, mismatched-photo rejection and
artwork replacement without inference. Reuse the trial verifier where appropriate.
Synthetic checks validate the implementation; they do not prove learned predictions
are physically correct on real garments.

For browser work, use the T3 collaborative preview tools when available. Exercise
sample switching, diagnostics, a corrective edit, full-size export, reload and
artwork replacement. Perform batch mutation on an isolated server, preserving the
user's current interactive work. Run the repo's required checks before committing.

Keep user photos, model weights, caches and exports outside this repo. Follow
`Workspace` path accessors for production template reads and native/Cygwin user-path
conversion for new CLI inputs. Keep ndarray render math pure (A7), explicit OpenCV
resampling/border choices, and current OpenCV/Pillow pins. The GPU worker is an
authoring dependency; deterministic rendering of an accepted calibration must
remain independent of it.

Marigold code is Apache-2.0; the baseline weights carry CreativeML Open RAIL++-M
terms. Preserve the distinction and check exact checkpoint terms before distributing
weights. [Code license](https://raw.githubusercontent.com/prs-eth/Marigold/main/LICENSE.txt),
[model license](https://raw.githubusercontent.com/prs-eth/Marigold/main/LICENSE-MODEL.txt).
