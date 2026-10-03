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

**Listing artifacts**:
Everything in the workspace keyed by a listing's name: its directory, render
cache, previews, market snapshot and cached proposal. They are moved and
removed together.
_Avoid_: listing files, caches (which names only some of them)

**Free name**:
A listing name that no directory under `listings/` holds. A directory holding
only a lockfile is not a listing, but its name is not free.
_Avoid_: available name, unused name
