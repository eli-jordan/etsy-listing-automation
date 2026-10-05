# Durable material maps, schema 1

This is the implemented CPU contract under ADR-0053. Preparation coordination,
HTTP integration and deployment wiring ship in later stack stages. Real photo
quality and maximum-size performance remain PR7 release gates.

`preparation.numerics` accepts decoded arrays and explicit `Evidence`. `plan_crop`
expands the enclosing quad rectangle by 40% on every side, floors lower bounds,
ceils upper bounds and clips the half-open rectangle to the photo. `Crop` retains
the original rectangle, photo dimensions, prediction dimensions, padding and the
complete transform. A resized prediction uses
`(photo_coordinate - crop_origin + 0.5) * scale - 0.5 + padding`. Evidence reuse
requires exact photo, checkpoint, inference and preprocessing identity and the
full clipped 40% requirement. No smaller margin is certified.

`prepare` ports robust normal integration, the affine depth prior, metric
flattening, orientation barriers and material baking. Camera normals use X right,
Y up, Z toward the viewer. Surface coordinates use X right, Y down, Z toward the
viewer, in photo pixels divided by placement width. Integer photo coordinates
are pixel centres. Material channels are U right and V down. Normalized 0 and 1
sample the first and last artwork pixel centres. Cancellation checkpoints precede
fitting, flattening, baking and lighting phases.

The automatic mask is a seeded GrabCut proposal, not a garment certification.
Seed and call run on the same thread under a proposal lock. That lock serializes
this module's calls, with no control over external OpenCV callers. Chroma seeds
exclude disagreement rather than dark folds. Insufficient seeds return a visible
mask for manual correction. Authoring stores the proposed raster and algorithm
identity through the calibration store.

Each placement archive stores the following arrays. Required fields are float32;
optional patch labels are int32. The extent is the full main photo, with shape
`height,width` and a final channel axis where specified.

| Field | Channels | Bounds |
| --- | --- | --- |
| `material` | U,V | -4 to 4 |
| `visibility` | Scalar | 0 to 1 |
| `estimated` | RGB gain | 0.04 to 1.7 |
| `photographic` | RGB gain | 0.04 to 1.7 |
| `texture` | Scalar | 0.9 to 1.1 |
| `residual` | RGB | 0 to 0.035 |
| `patch_ids`, optional | Scalar | 0 to 100 |

Visibility outside the quad is zero. Explicit linear sampling uses constant zero
borders, so a filter near an artwork edge can mix ink with transparent black.
Derivatives respect discrete patch boundaries and choose premultiplied linear
colour mip levels. Both lighting choices persist. Strength interpolates gain
toward one; texture and shine scale their own fields. Artwork never multiplies
by the main garment's albedo. Ordered layers compose in one linear buffer;
untouched background pixels retain their bytes. Shared colour photos require
identical dimensions and an exact main-photo identity. Dimensions do not certify
compatible folds.

`Artifacts.publish` accepts the complete placement set and a callback that reads
current saved preparation inputs under the template lock. Single and colour-matrix
sets have one null ID. Multiple sets have unique stable IDs. Input identity sorts
IDs; composition order remains the caller's ordered layers. The callback reports
geometry, masks and evidence, excluding appearance.

`PreparationInputs.evidence` is an opaque digest of accepted inference semantics,
including checkpoint/preprocessing, photo and crop identity. It is independent of
cache filename and installed-engine selection. Explicit preparation supplies the
complete identity set to `saved_inputs`. Ordinary readiness omits that argument,
recovers accepted identity from the manifest, and reads current photo pixels,
geometry, masks and inference settings. Cache deletion and compatible installed
model updates do not invalidate maps. Artwork, target colour and appearance
change rendering only.

The manifest records array shapes, dtypes and numerical checksums, photo identity,
placement extents, semantic conventions and provenance. The content digest hashes
canonical contiguous array bytes and semantic layout by placement ID. Archive
bytes, generation names, paths and provenance are excluded. Storage has separate
checksums. Readers validate ZIP member counts, uncompressed size, NPY headers,
exact byte lengths and dimensions before allocation, load with pickle disabled,
and validate finite values, bounds and numerical identity. Unsupported schemas
require migration or preparation.

Operational safety limits are 32 placements, 8192 pixels per photo axis, 32 Mi
photo pixels and 2 GiB per archive or complete generation of numerical arrays.
These bound hostile or accidental allocations. They are not measured throughput
or quality guarantees. Editor configurations may exceed these preparation limits;
PR7 measures practical limits on the supported machine. Imaging pins are unchanged
and the port adds no SciPy dependency.

Publication registers an owner before exposing staging, writes and validates the
complete set, moves the immutable directory and replaces the current pointer
under the template lock. Failure before that pointer preserves its predecessor.
Reader leases hold one generation through rendering. Cleanup protects current
maps, active publishers/readers and durable job references supplied by the
coordinator. Workspace owns all directory conventions and Windows-safe removal.
Interrupted unreferenced staging and generations can be cleaned after restart.
