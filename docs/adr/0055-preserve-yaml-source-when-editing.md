# ADR-0055: Preserve YAML source when editing

Status: accepted, implementation planned in the
[Admin page plan](../features/admin-page-20261030/plan.md).

Workspace YAML is seller-edited source. Every application writer must retain
comments, key order and untouched bytes when changing a value. A semantic no-op
must leave the complete file byte-identical without replacing it. Rebuilding a
document from a pydantic dump loses the seller's explanations and creates
unrelated changes during autosave.

Use ruamel.yaml round-trip documents through the existing workspace storage
owners. Retain original source bytes and apply source-preserving edits where
round-trip emission would normalize untouched whitespace, quotes or line endings.
The library choice alone does not prove the preservation guarantee. Golden text
fixtures through each writer establish it. Brand-new files use the owning
workflow's documented layout and defaults.

Validation still uses the complete candidate model before the write. Existing
atomic replacement, ListingDocuments locks, calibration transactions and
create-if-absent rules remain the write boundaries. Shared YAML mechanics do not
give callers another way to edit a listing or assemble workspace paths.

Admin edits compare a hash of the original file bytes under the write lock and
refuse an outdated revision. A successful write returns the new revision. This
prevents a browser save from silently removing a concurrent hand edit, including
a comment-only edit. Missing files have an explicit revision state so creation
also participates in conflict detection.

The conversion includes setup, listings, templates, calibration, garment profiles
and pricing plans. PyYAML reads need not all move at once, but no write may
discard source structure. This replaces setup's existing comment-regeneration
policy. It does not migrate or reformat arbitrary external workspaces.

First recorded 2026-10-30 during Admin page planning.
