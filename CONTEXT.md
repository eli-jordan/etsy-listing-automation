# Etsy listing automation

This tool turns a print-on-demand design into a reviewable Etsy draft by way of
Printify. These are the terms the code and its reviews use for the seller's
workspace.

## Language

**Listing**:
One product for sale. Its identity is its directory name under `listings/`.
_Avoid_: product (Printify's word for the remote copy), item

**Listing document**:
A listing's `listing.yaml`, as written. It is edited only by reading it,
changing it and writing it back, all under the listing's lock.
_Avoid_: listing config, listing file

**Template position**:
A listing's own position for artwork on one mockup template, or one placement
within a template showing several garments. It changes the mockup only.
_Avoid_: print placement, template calibration, per-colour position

**Template state**:
What a mockup template's saved files amount to: absent (no `template.yaml` yet),
unreadable (one that will not load), needs repair (a calibration transaction
stands in the way) or loaded.
_Avoid_: calibration status, which the rail derives from a loaded config

**Label**:
Free-form text a seller tags a mockup template with, for finding it, such as
`shot:flat lay`. The text before a colon is its group. A label exists only while
a template holds it, and it never changes a render.
_Avoid_: tag, category

**Listing artifacts**:
Everything in the workspace keyed by a listing's name: its directory, render
cache, previews, market snapshot and cached proposal. They are moved and
removed together.
_Avoid_: listing files, caches (which names only some of them)

**Free name**:
A listing name that no directory under `listings/` holds. A directory holding
only a lockfile is not a listing, but its name is not free.
_Avoid_: available name, unused name
