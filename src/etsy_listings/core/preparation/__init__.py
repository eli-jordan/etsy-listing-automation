"""Explicit authoring preparation, separate from CPU rendering (ADR-0053).

Import modules directly. Runtime owns global installation; worker_client owns
subprocess communication, including idle restart. Predictions validates numeric
evidence without loading model packages. Installation and the embedded worker
distribution are implementation details reached through Runtime.
Numerics exposes plan_crop, evidence_covers, propose_mask and prepare. Its
internal geometry fitter is reached only there. Artifacts exposes typed
PreparationInputs and Artifacts.saved_inputs/readiness/publish/acquire/cleanup.
Rendering consumes MaterialMaps through render.render_marigold_scene. Neither
artifact loading nor numerical preparation depends on the installed runtime.
Importing this package never starts workers or loads torch.
"""
