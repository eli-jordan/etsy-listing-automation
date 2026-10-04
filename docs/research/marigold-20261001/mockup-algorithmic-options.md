# Algorithmic alternatives for fabric calibration

Research date: **2026-10-01**. Scope: existing single blank-garment photographs, good output, and only a few minutes of manual adjustment. No experiments or production changes were made.

## Recommendation

Include a **classical broad-surface fit plus constrained fold mesh** as the algorithmic prototype. It offers a useful comparison against learned normals and an AI-edited grid, with inexpensive CPU execution and transparent controls. Treat the surface and fold estimates as hypotheses; do not promise automatic physical reconstruction from one photograph.

For current purchased photographic templates, pure shape-from-shading is a plausible research route but a weaker first bet than using it as a restrained refinement of a simple surface prior. For newly captured templates, multiple controlled lighting images or a physically printed calibration pattern supply stronger evidence, at the cost of changing the capture workflow.

## What classical algorithms can and cannot infer

**Shape from shading / inverse rendering.** Classical methods fit a surface, light and sometimes albedo so that the rendered result explains the photograph. The problem is ambiguous: different surfaces can render the same image even with fixed lighting. Uniform reflectance, smoothness, boundary normals and lighting assumptions constrain possible answers; they do not establish unique cloth geometry. The University of Toronto's research page includes folded-cloth reconstructions and physically demonstrated ambiguity examples. [Shape-from-shading research](https://www.cs.toronto.edu/~jepson/researchSFS.html), [Cornell lecture, single-image assumptions](https://www.cs.cornell.edu/courses/cs5670/2019sp/lectures/lec15_light.pdf).

SIRFS is a concrete optimization-based research reference that jointly infers shape, illumination, reflectance and shading using statistical priors. Its author provides code and data. It demonstrates that learned image-editing models are not the only route, but does not provide a ready garment-coordinate calibrator. An implementation or port would need a separate dependency and license review. [Original paper](https://arxiv.org/abs/2010.03592), [author's code/data links](https://jonbarron.info/).

Garment-specific classical research also exists: *Garment Modeling from a Single Image* builds broad geometry from estimated mannequin pose/body and garment outlines, then refines folds with shape from shading. This supports a broad-prior-plus-detail approach, rather than proving that a generic grayscale map recovers the garment. The publicly readable abstract does not establish turnkey code availability or a low-manual-work workflow. [Publisher's original article](https://onlinelibrary.wiley.com/doi/abs/10.1111/cgf.12215).

**Engineering inference for our photos:** washed dye, strong patterns, shadows from arms and near-black fabric are reasons a photometric solver can explain appearance with the wrong surface. A low photographic fitting error should not be its success criterion. Evaluate how the resulting map deforms grids, fine text and artwork, and how much correction it needs.

**Silhouette / broad shape.** Boundary information constrains the outer garment, but it does not directly reveal interior chest curvature or wrinkle depth. An assumed cylinder, elliptical cross-section or smooth height surface supplies a prior. Its dimensions and turn relative to the camera should be fitted or given a few controls, not treated as measurements from a silhouette alone. This is a proposed modeling choice.

**TPS, MLS and mesh interpolation.** These construct a deformation from correspondences or handles. Scikit-image's TPS explicitly requires matching source and destination points; MLS builds image deformation from user-defined handles. They solve interpolation and editing, not automatic discovery of where the cloth coordinates belong. Automated calibration still needs a source of those correspondences or an optimization objective. [TPS documentation](https://scikit-image.org/docs/stable/api/skimage.transform.html#skimage.transform.ThinPlateSplineTransform), [original MLS paper](https://people.engr.tamu.edu/schaefer/research/mls.pdf).

**Registration / optical flow.** OpenCV provides alignment and motion between two images. That can propagate an already calibrated reference to a sufficiently similar photo, such as another colorway shot in the same pose. It cannot establish material coordinates from an isolated blank shirt. The reference must already have a material map; weak texture, changing folds and occlusion can make propagation unreliable. This proposed reuse workflow follows from the two-image interface and intensity-matching objective. [OpenCV tracking/alignment documentation](https://docs.opencv.org/4.10.0/dc/d6b/group__video__track.html).

**Photometric stereo.** Multiple images under different lighting add evidence for surface normals. A CMU implementation uses a calibrated ring of LEDs, multiple captures and mesh optimization. This is credible for a controlled new-capture workflow, not a method for processing one downloaded photograph. Cloth must remain sufficiently stationary between lighting exposures, and visible surface geometry still needs parameterization into print coordinates. [Primary project and capture details](https://www.cs.cmu.edu/~ILIM/projects/IM/nearPS/).

## Scoped classical prototype

The following is our proposed heuristic, not a verified off-the-shelf garment method:

1. Begin with the existing print quad and a garment/chest mask. Give the user a few mask corrections if automatic separation fails.
2. Initialize a broad surface using a fitted elliptical cylinder or a smooth height model. Expose only chest curvature, turn and print origin/scale.
3. Detect candidate fold ridges and valleys at several scales within the mask. Exclude seams, print-region boundaries and weak evidence where possible; do not assume every brightness edge is a fold.
4. Optimize a small surface/control mesh with the broad prior, restrained photometric evidence, smoothness, plausible material stretch and no flipped cells. Let the user approve or remove a few major fold constraints. If needed, add shallow local fold profiles rather than unconstrained brightness displacement.
5. Parameterize the accepted visible surface into material coordinates and export a photo-to-print sampling map. Preserve the photographic background, transfer lighting separately, and reuse the map across artworks.

**Evaluation gate:** compare broad-surface-only, broad-surface-plus-folds and existing quad under identical lighting. Target at most five minutes of active correction per template; record setup time, error-prone parameter adjustments and rejected templates. Reject the route if acceptable results depend on hand-tracing many folds or authoring the entire mesh. Time limits are evaluation targets, not demonstrated performance.

Use worn, flat-lay, light, dark and washed garments. Prefer this route if it gives comparable realism with less intervention; prefer learned normals if photometric ambiguities consistently require repair. Combine the broad prior with learned normals later if independent comparisons show a useful contribution from both.
