# Automatic garment mapping: model feasibility

Verified **2026-10-01** against primary sources. This note supports prototype selection; no models were installed or run, and quality and authoring-time claims remain hypotheses.

## Recommendation

Use **Marigold normals plus a custom constrained UV solver** as one credible prototype. Do not count a pretrained Normal-guided Garment UV model as another readily runnable option: I found no public implementation/checkpoint link on the authors' project or publication pages. A faithful reimplementation would require new engineering, and overlaps strongly with the normal-derived solver. The alternatives can instead test automatically extracted correspondences from an AI-edited grid and directly proposed sparse mesh coordinates. Those three have different sources of geometric evidence.

## Normal-guided Garment UV: relevant algorithm, unavailable turnkey implementation

The authors' project links the paper and demonstrations, but no code or weights. The lead author's publication entry links PDF, video, project and a patent; neighboring papers explicitly link code when available. This is evidence that we cannot currently plan around an accessible released implementation, not proof that none exists elsewhere. [Project](https://www.yasamin.page/normal-guided-uv), [author publication list](https://www.yasamin.page/home).

The paper optimizes a coordinate network from normals and an initial proxy map; it is not simply an image-to-UV pretrained predictor. Its normal-derived isometry loss, proxy constraint and orientation penalty are a useful solver reference. It assumes orthographic projection and no self-occlusion, uses a 256-pixel garment crop, and reports erroneous continuity at folded-over cloth. Shading is a separate component and can confuse pattern contrast with illumination. [Paper, sections 3 and 5](https://arxiv.org/pdf/2303.06504).

**Engineering judgment:** implementing those constraints with a dense grid or control mesh, rather than reproducing the neural optimizer, is a legitimate experimental route. Separate visible patches are needed where overlapping cloth causes jumps in material coordinates. The paper does not establish quality on our photographs, or supply a usable model/code license for an absent release.

## Marigold normals: accessible initializer, UV solver still required

Marigold Normals v1.1 has published weights and returns unit surface normals in camera space. Its effective prediction resolution is approximately 768 pixels; upsampling does not establish recovery of finer fabric geometry. Ensembling more than two predictions supplies an uncertainty map, which measures disagreement rather than validated physical accuracy. [Model card](https://huggingface.co/prs-eth/marigold-normals-v1-1).

The official repository provides normals inference and published checkpoints. It was tested with Ubuntu, Python 3.10, CUDA and an RTX 3090; it recommends WSL2 for Windows. This is a tested configuration, not a minimum GPU specification. The authors offer a hosted demo and Diffusers integration, so the first feasibility pass can avoid changing this project's environment. Seeds and deterministic settings can improve reproducibility; freeze accepted arrays rather than repeatedly infer geometry during renders. [Official repository](https://github.com/prs-eth/Marigold).

**Proposed solver, not shipped by Marigold:** segment the printable chest; define print origin, axis and scale from an existing placement or a few anchors; optimize photo-to-material coordinates to preserve the normal-implied surface metric, while penalizing flipped cells, excess curvature and implausible stretch. Weight uncertain regions down and preserve a conservative placement prior. Export fixed full-resolution coordinates for the existing OpenCV sampler. Solve geometry once per template, then reuse it across designs.

**Failure modes to measure:** dark fabric, dyed wash mistaken for geometry, missed shallow wrinkles, grazing surfaces, perspective mismatch and self-overlapping folds. Normals do not uniquely fix print placement or recover hidden cloth. Near-tangent normals make foreshortening constraints ill-conditioned; constrain or exclude those pixels instead of allowing huge warps. These are engineering inferences from the model output and geometric assumptions, not observed failures on our templates.

Code uses Apache-2.0; model weights use CreativeML Open RAIL++-M with use and redistribution conditions. Do not describe the weights as Apache-licensed or academic-only. No Photoshop dependency is present. [Code license](https://raw.githubusercontent.com/prs-eth/Marigold/main/LICENSE.txt), [model license](https://raw.githubusercontent.com/prs-eth/Marigold/main/LICENSE-MODEL.txt).

## Shared lighting candidate

Marigold IID Lighting v1.1 is also released. It predicts linear-space albedo, diffuse shading and a non-diffuse residual, with approximately 768-pixel effective resolution and the same stated model-license family. This is a more directly accessible learned shading option than the academic-use implementation discussed in the earlier report. Test it as a shared lighting ablation against garment-relative photographic lighting; do not let different lighting hide geometry differences. Domain suitability and fine texture preservation remain unverified. [Lighting model card](https://huggingface.co/prs-eth/marigold-iid-lighting-v1-1).

## Goal alignment of the three proposed authoring inputs

- **AI-edited grid:** potentially low manual work and dense correspondence, but generated grid regularity and cloth alignment are hypotheses. Measure grid topology, unchanged photographic structure and correspondence reliability before rendering production artwork.
- **Vision-proposed sparse mesh:** inexpensive automatic comparator. Allow only a few corrective handles; stop if it becomes manual authoring of 16–25 points. A sparse map may capture broad chest shape while missing localized folds.
- **Normals plus constrained UV:** highest algorithmic effort, but most explicit geometric evidence and automated validity checks. Bound manual repair time and report unsupported overlapping folds.

These are experimental assessments. Evaluate them independently with shared placement, masks, lighting and artwork. A grid-plus-normal hybrid is worth a later combination trial if their errors complement each other, after independent comparisons identify which contribution helped.
