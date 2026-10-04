# Three prototypes for automatic fabric calibration

Scoped 2026-10-01, against the [mockup realism research](mockup-realism-research.md). These are experiments, not changes to the PRD or promises of measured quality. No prototype has been implemented or evaluated.

## Objective and recommendation

Choose the highest-quality rendering method that needs only a short review and occasional adjustments when adding a template. Technical complexity and unattended processing time are acceptable. Photoshop is not required. Calibration happens once per photographic scene and print placement; replacing artwork must require no recalibration.

Test three different ways of obtaining the mapping: **an AI-edited calibration grid, a vision model's numerical mesh, and predicted surface normals with a constrained UV solver**. The first exploits the image editor's visual compositing ability, the second tests whether image analysis alone is sufficient, and the third gives a geometry solver numerical surface evidence. Comparing three interpolation libraries would not answer the user's main question: how to obtain good calibration without authoring it by hand.

My strongest initial bets are the edited grid for a useful result quickly, and the normal-derived mapping for a more systematic treatment of folds. The numerical mesh is a bounded comparator: it could provide the simplest workflow, but should be dropped promptly if coordinate corrections become manual mesh authoring. These are engineering judgments, not quality rankings established by evidence.

Use **five minutes of active human work per template** as the target, and **ten minutes as the cutoff** for this evaluation. Include choosing the print area, inspecting the result, mask corrections, point adjustments, prompt edits and retries in that time. Record unattended inference time separately. These thresholds operationalize “fine adjustments, not hours”; they are proposed targets, not demonstrated performance.

## Shared foundation

Each candidate starts with the same original photograph and intended print rectangle. Reuse the existing placement quad where available. On a new template, allow a proposed quad to be accepted or corrected; photograph appearance alone does not determine the intended print size. Begin with one visible chest placement, then evaluate an occluded placement and two placements in a scene. Different color photographs count as separate calibration work unless registration actually establishes matching folds.

Build one experimental runner and comparison viewer. It accepts a photograph, placement and diagnostic artwork; runs the selected initializer; displays the locally rendered result; allows point and mask corrections; exports the approved calibration; and renders all evaluation artwork. Start with file-based adapters for model outputs so feasibility does not depend on finishing API integration. Automation of inference and extraction is part of the final prototype evaluation, however: copy/paste and hand labelling count as work.

The common artifact is a floating-point **photo-pixel to canonical artwork-coordinate map**, with a visibility mask. Record reference dimensions, coordinate direction, crop transforms and valid regions explicitly. Keep optional editable landmarks, masks and lighting fields alongside it. Baking the inverse map is a geometric operation; negating offsets or swapping forward TPS landmarks is not assumed to be an exact inverse. Preserve separate visible patches where a fold hides material.

All candidates sample the unchanged source artwork onto the **original photograph**, using the same float/premultiplied-alpha sampler and photo-based compositor. They do not use the generated grid photograph as the final background. At preview size, scale the approved full-resolution mapping consistently rather than independently recalibrating it. Approved artifacts are reused without model inference on every design.

Lighting is a shared experiment because the existing soft-light treatment cannot darken pure white ink. First compare the existing renderer with the existing quad plus a common improved compositor. Then compare the three mappings with that same compositor. Use garment-relative linear-light shading, restrained fabric detail and visibility masks; do not obtain realism by making opaque artwork translucent.

Also evaluate **Marigold IID Lighting** as a shared alternative to the simple relative-lighting estimate. Its released model predicts albedo, diffuse shading and non-diffuse residual in linear space. Normalize the estimated shading for ink, evaluate residual transfer conservatively, and retain the original photo for the background. These components are estimates, not a validated print-material model. Run the same lighting choices across retained geometry candidates; do not give only one candidate better lighting. [Official IID model card](https://huggingface.co/prs-eth/marigold-iid-lighting-v1-1).

## Prototype 1: AI-edited grid to reusable coordinates

**Question:** Can an image editor invent a sufficiently accurate fabric-following grid that we can extract and reuse, with almost no human calibration?

Generate a canonical 5×5-node grid in code, with distinct row/column markings and readable node IDs. Supply the blank photo, grid and intended placement to an image-editing model. Ask it to preserve the photograph and wrap only the grid around the existing cloth. Trial a small, fixed set of prompt/marker variants on development photos, then freeze the winning recipe. OpenAI documents reference-based editing and explicit preservation instructions; this does not establish numerical garment-map accuracy. [Official image prompting guidance](https://developers.openai.com/api/docs/guides/image-prompting).

Recover nodes and line paths using image processing with OCR or vision assistance for identity matching. Preserve the known connectivity. Registration must use unchanged image features and also inspect the print region: matching the background does not prove the shirt geometry stayed intact. Account for resizing/cropping explicitly. Missing or ambiguous IDs are errors to flag, not positions to silently guess.

Fit a smooth, constrained mapping from the recovered correspondences. Use line paths as additional evidence where they can be recovered reliably; a 5×5 grid alone cannot capture every fine wrinkle. Reject crossings, collapsed regions and implausible discontinuities. A denser grid is a gated refinement only after sparse extraction works, since more markers may become unreadable.

The review shows the extracted grid over the original photo and a fresh local render of different artwork. Offer a few node nudges and mask corrections. Allow at most two automatic repair attempts for an invalid proposal; record every attempt and failed template. Do not require the user to write a new prompt for every photo.

**Deliverables:** fixed prompt and grid recipe; generated proposals; registration and correspondence diagnostics; editable extracted controls; saved numeric maps; locally rendered comparison gallery; human time, retry and failure records.

**Early gate:** on three contrasting photos, establish that correspondence extraction works automatically and that the recovered map transfers to new artwork. Stop if the useful result depends on the AI-modified shirt, if marker recovery repeatedly needs hand labelling, or if correction exceeds the time cutoff.

**Main uncertainty:** visually convincing grid imagery may contain hallucinated folds or inconsistent spacing. Its prospective advantage is that the model demonstrates its proposed deformation visually. Its likely weak point is precise correspondence preservation. Neither is measured yet.

## Prototype 2: image analysis directly proposes a numerical mesh

**Question:** Can a vision reasoning model supply useful mesh controls directly, avoiding generation, registration and grid extraction?

Provide the original image, a high-detail chest crop, the placement quad and a canonical 5×5 lattice with fixed IDs. Ask for destination coordinates, visibility/uncertainty flags and a small set of fold constraints in a fixed schema. Define normalized coordinates against the supplied crop and restore original-image coordinates in code. The model proposes geometry; deterministic code interpolates it and checks validity.

Render a diagnostic grid locally and provide that preview for one automatic correction pass. Keep the original photograph in both rounds. Never make validity depend solely on the same model declaring its own result correct. Structured Outputs can constrain the JSON shape, but OpenAI separately documents limitations in precise spatial localization and resizing; a valid response is not evidence of accurate coordinates. [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [vision limitations](https://developers.openai.com/api/docs/guides/images-vision#limitations).

Use the same mapping bake, compositor and review controls as Prototype 1. Initially keep the lattice sparse; only refine near a fold if the proposal reliably improves local geometry. Human corrections should be isolated nudges, not positioning most of the mesh.

**Deliverables:** input/schema/prompt recipe; raw coordinate proposals; one-round refinement trace; validity diagnostics; editable mesh; saved maps; identical evaluation gallery and effort records.

**Early gate:** test three photos before substantial editor work. If useful geometry routinely requires repositioning more than three interior nodes, or the model mostly returns the original flat lattice, discontinue this route as a low-effort calibration candidate. The three-node threshold is a proposed diagnostic gate; the timed full evaluation remains decisive.

**Main uncertainty:** a reasoning model may understand folds while placing their coordinates poorly. Sparse controls also impose a detail ceiling. Its prospective advantage is the shortest path from photo to editable calibration, with no modified photograph to register. This makes it worth a small feasibility trial, rather than assuming image generation is essential.

## Prototype 3: learned surface normals to a constrained garment map

**Question:** Can a numerical surface estimate and an optimization solver automatically recover better broad curvature and fold compression than prompted controls?

Use the publicly released **Marigold Normals v1.1** model on the chest crop, retaining numerical unit normals and ensemble disagreement. Its model card describes an effective resolution of about 768 pixels and uncertainty from ensembles larger than two. Cropping concentrates this budget on the print region; resizing predictions does not create missing wrinkle detail. The model does not output UV coordinates. [Official normals model card](https://huggingface.co/prs-eth/marigold-normals-v1-1).

Start with an unoccluded local patch. Fit a smooth surface from predicted normals with integrability and uncertainty weighting; compare the approximation on synthetic surfaces with known mappings first. Under an orthographic initialization, normals constrain depth gradients, but grazing angles, perspective and unknown scale require explicit treatment. Use the placement to set orientation, origin and scale, and test whether an approximate camera is adequate. A depth estimate may be added if that specific ambiguity prevents useful fitting; it is not a substitute for material coordinates.

Flatten the fitted patch into canonical print coordinates with near-isometry in **surface space**, weak smoothness and anchored placement constraints. Avoid demanding rigidity in image space, which would prevent useful foreshortening. Optimize mesh orientation and reject foldovers; bake a dense inverse map for the common sampler. The mapping is inferred and underconstrained, not recovered ground truth. This custom solver is the substantial research component of the prototype.

Use the **Normal-guided Garment UV Prediction** paper as an algorithm reference. The checked author resources do not expose an implementation/checkpoint download, so this scope does not assume a pretrained direct-UV model can be installed. The paper-inspired solver belongs in this prototype, rather than being counted as a separate ready-made option. [Author project and paper](https://www.yasamin.page/normal-guided-uv), [availability and feasibility notes](mockup-prototype-model-feasibility.md).

Propose the print-region mask automatically, allow short corrections, and count them in calibration time. Handle arms/necklaces with visibility masks. A self-occluding cloth fold additionally needs distinct material patches; add that only after the unoccluded solver is useful. Mark unsupported or uncertain regions explicitly rather than quietly falling back to a plausible-looking flat map.

The reviewer adjusts placement, a small number of anchors, and visibility. Regularization and model settings are tuned globally on development photos; needing per-photo solver parameter searches is a usability failure. A GPU inference worker may run separately from the tool's Windows-native renderer. Hardware, worker deployment and checkpoint terms must be verified during the feasibility stage; GPU availability is not assumed.

**Deliverables:** pinned inference recipe; normals and disagreement; reconstructed surface/mesh; UV solver and fit diagnostics; masks; saved maps; comparable render gallery; hardware/runtime and correction records.

**Early gate:** first inspect predictions on light, dark washed and folded shirts. Then demonstrate a valid mapping on synthetic known surfaces and one real unoccluded chest. Stop or narrow the supported photo class if predictions miss the relevant folds, solver ambiguity requires extensive anchors, or good results depend on hours of parameter tuning.

**Main uncertainty:** normals do not uniquely determine cloth coordinates, and material appearance can confuse prediction. This route has the strongest numerical surface evidence among the three, but its expected quality advantage is a hypothesis. Engineering complexity is acceptable only if it reduces the user's work and improves held-out renders.

## Evaluation and decision

Use twelve real blank photos: six development photos and six held-out photos, each group spanning light and dark flat lays, worn chest curvature, strong folds, washed fabric and an occluded placement. Include a multi-garment scene in the expanded check. Photography and artwork remain in a separate user-owned scratch workspace; commit recipes and aggregate findings, not private assets.

Use five artwork categories: a diagnostic grid with circles, fine text, white line art, opaque white/black blocks, and an opaque multicolor illustration. Calibrate using the diagnostic target; evaluate the saved map on the other designs without additional adjustment. Repeat calibration three times on each held-out photo to expose stochastic failures. Choose a normal result by fixed rules, not by retrospectively selecting the prettiest run.

Compare the current renderer, current quad with improved lighting, and all retained candidates with the same improved lighting. Review both full gallery-size images and 100% print-region crops with method labels hidden. Score broad curvature, local folds, lighting continuity, color credibility, artwork integrity, visibility and edges separately. A generated proposal image is never the image being scored. Compare untreated proposals and results after bounded corrections to reveal the actual automation benefit.

Acceptance is provisional because this small photo set cannot establish universal performance. A useful candidate should produce publishable results on at least five of six held-out photos, have median active calibration time at or below five minutes, and require no more than ten minutes on a successful photo. Failed and timed-out photos stay in the denominator. Log corrections, model calls, expense, unattended latency and storage separately. A method that passes only flat lays may qualify for that class, not for the entire template library.

Artifact integrity is a prerequisite: original artwork is sampled unchanged, text and line connectivity survive the intended deformation, opaque ink stays opaque, the photo outside print visibility remains unchanged, maps have valid orientation, and approved artifacts reproduce outputs with inference disabled. Neutral/synthetic mappings supply correctness checks; visual garment reviews measure realism. Neither stands in for the other.

Among candidates that meet the human-effort limit, choose the best visual output and record the quality/time tradeoff. Do not prefer cheaper implementation over better output. If none qualifies, report that rather than recommending the least unsuccessful candidate. If grid correspondences and normals have complementary strengths, run a final combination experiment using the grid as anchors for the normal-derived solver; score it under the same budget. This is a reuse of the evaluated components, not a fourth independent hypothesis.

## Build sequence and boundaries

First assemble the common viewer, compositor and baseline gallery. In the same feasibility stage, test automatic grid extraction, direct coordinate proposals and normal quality on three photos. Continue full development only for routes that clear those early gates. Prototype 3's solver needs the most research; its normal-quality check should happen early so that work is not invested in unsuitable predictions.

Then complete the retained initializers, freeze their recipes, run the held-out comparison, and deliver the side-by-side gallery, calibration artifacts and a decision report explaining successes, failures and effort. No production UI, schema migration, remote listing work, or automatic template rollout is needed to answer the question.

Use isolated experimental code/dependencies and preserve the pinned production OpenCV/Pillow versions. Existing baseline renders go through `render_scene`; experimental geometry/compositing stays clearly separate until a decision is made. Adoption would require the deliberate PRD 5/6c and A7 revisions identified by the research, plus asset hashing and shared preview/final-render behavior. Prototype findings do not silently amend those settled decisions.
