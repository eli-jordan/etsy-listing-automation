"""Explicit authoring preparation, separate from CPU rendering (ADR-0054).

Import modules directly. Runtime owns global installation; worker_client owns
subprocess communication, including idle restart. Predictions validates numeric
evidence without loading model packages. Installation and the embedded worker
distribution are implementation details reached through Runtime.
Numerics exposes plan_crop, evidence_covers, propose_mask and prepare. Its
internal geometry fitter is reached only there. Artifacts exposes typed
PreparationInputs and Artifacts.saved_inputs/inspect/readiness/publish/acquire/
reusable/cleanup. inspect reuses bounded immutable-generation validation proofs;
reusable leases exact unchanged placements during a CPU rebuild. Schema 2 maps
carry photo-coordinate extents; schema 1 full-photo generations remain readable.
Each refusal's ArtifactError subclass carries its typed readiness reason.
readiness.template_readiness answers whether any saved template can render, for
editor status, listing checks, engine refusals and the catalogue
(catalog_readiness), without consulting inference runtime or cache;
saved_preparation_facts adds the prepared engine for authoring status.
scenes.lease_scene is the one path from accepted maps to a composed scene and
its identity, shared by the render stage and every preview. Neither
artifact loading nor numerical preparation depends on the installed runtime.
Importing this package never starts workers or loads torch.
"""
