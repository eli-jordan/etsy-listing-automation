# ADR-0038: Expose stage facts; let the frontend compose the view

Stages may expose typed snapshots of desired and live facts, including unchanged fields. The API passes them through and the frontend owns comparison layout; highlighting still comes only from `Change` objects. This avoids a second backend listing assembler and API code casting erased stage internals by name. Snapshots are excluded from the plan fingerprint because display facts are not execution authority.

First recorded 2026-09-17 in [commit c455e61](https://github.com/eli-jordan/etsy-listing-automation/commit/c455e616bc59c0340ab410d3c2b813bb61f466a3).
