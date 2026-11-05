# Mockup template rename

Status: implemented. Started 2026-11-05.
This specification owns the requirements under the
[documentation authority rules](../../README.md#documentation-authority).

## Outcome

A seller renames a mockup template in the calibrator by double-clicking its name
in the breadcrumb, as they rename a listing. The template keeps its calibration,
its Marigold maps and its place in every listing that uses it, and a deployed
listing sends nothing new to Etsy because of the rename.

A template's name is its directory under `mockup-templates/`, and nothing else
identifies it. Renaming the folder by hand breaks every reference to it, which is
why this is an operation rather than a file move.

## What follows the name

| Holder | What changes |
| --- | --- |
| Template directory | Moves whole, with `template.yaml`, photos and `_renderer/`. Marigold maps are template-relative and stay valid. Photo filenames do not change (ADR-0004). |
| `listing.yaml` | `media[].template`, `etsy.variation_images`, `template_positions` keys, edited in place (ADR-0055). |
| Listing templates | The same three fields. |
| Garment profiles | `preview_template`. |
| Staging sessions and batches | The same three fields in the frozen document. A listing template's rename leaves this copy alone; here it cannot, because the copy points at a directory it does not own and confirming or retrying makes listings from it. |
| Render and preview caches | `.cache/renders/{listing}/{template}/` and the preview twin move. |
| Preparation queue | Retained predictions move, and the paths in job records, the current pointer and set manifests follow, so a rebuild still needs no worker. |
| Lockfile | The `etsy_media` stage's refs and `etsy_image_ids` keys. |

## Deployed listings

Etsy images are remembered by a ref that spells the template's name, so unchanged
refs would read as every image being replaced. The refs follow, and image ids and
content hashes stay.

The render stage's hashes also cover the name, and the lockfile does not hold what
is needed to recompute them. We leave them: the next apply re-renders those scenes
locally to identical bytes. Changing the recipe to drop the name would have
re-rendered every listing in the workspace instead. Until previews exist, the plan
reports those images as pending, as for any re-render, and apply then finds the
bytes unchanged and uploads nothing. It does repeat the idempotent `image_ids`
order call.

## Refusals

All of these leave everything as it was: a taken name (`409`, and names differing
only in case count as taken), an unusable name (`400`), a missing template
(`404`), any deploy run queued or in progress (`409`), a queued or running
preparation job for the template (`409`), and a file in the template held open
(`409`). The deploy check covers every run rather than only affected listings,
because a rename is rare and finding the affected listings would race with the
runs it is checking.

## Partial failure

The directory moves first, because it is the step a retry can fix. After that a
reference file that cannot be read or written, such as one with broken YAML or an
edit through an alias, does not stop the rest. The response lists it under
`unresolved` and the calibrator shows it beside the name, for the seller to fix by
hand. There is no rollback or journal: a crash part-way leaves references naming a
template that has gone, which the listing's issues already report, as they do
after a template is deleted by hand.

## Limits

This is a UI operation with no CLI command. As with listing rename, nothing guards
against a second process such as the CLI running beside the server. Unsaved
renderer switches, held in the calibrator's memory by name, do not follow; the
saved template does.
