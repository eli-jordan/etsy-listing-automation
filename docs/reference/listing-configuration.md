# Listing configuration rules

The validators define exact fields. This page explains the precedence and
resolution rules that are easy to miss when reading a YAML example.

## Prices

A price carries the Etsy shop's currency. For one colour and size, resolution
tries the listing's colour-specific `price_overrides`, then its per-size
`prices`, then the referenced pricing plan's colour override and per-size
price. A pricing plan can supply a shared starting table while a listing
overrides only the cells it needs. A missing price is an error after all four
sources have been tried.

`pricing_plan` is a path reference, using the same
[workspace and owner roots](workspace-references.md) as design files. Loading
it belongs to the caller; the listing model resolves prices from an already
loaded plan. See [listing.py](../../src/etsy_listings/core/config/listing.py) and
[pricing_plan.py](../../src/etsy_listings/core/config/pricing_plan.py).

The `new` wizard can convert Printify's USD production cost into the shop
currency to help choose a retail price. Saved prices remain explicit amounts;
deployment never performs that conversion. Price-above-cost checks use the
live product's cost, because the catalog does not provide it reliably.

## Artwork and media

For a garment colour, artwork resolution tries the listing's explicit colour
override, then the template placement's artwork override, then an
`on-light` or `on-dark` key matching the garment profile's colour tone, then
the sole design key if there is exactly one. An explicit key that is absent
from the design map refuses the operation. Rendering and Printify product
creation share this resolver so the photograph and printed shirt use the same
file. See [placement.py](../../src/etsy_listings/core/engine/stages/placement.py) and
the [rendering specification](../features/multi-placement-rendering-20260903/spec.md).

`colors` chooses sellable variants. `media` chooses which mockup scenes render
and the Etsy gallery order. Selecting a colour alone does not request a photo.
The [gallery and path decisions](../adr/README.md) explain image/video ordering
and reusable versus listing-local assets.

A requested colour that matches no catalog colour is refused. A requested
size that no colour offers is also refused. A missing colour/size cell is
reported and skipped, because the printer may offer a sparse matrix. See
[resolve.py](../../src/etsy_listings/core/clients/printify/resolve.py).

## Etsy resource names

A shop section is chosen by name per listing; it has no shop-wide default.
The Details editor can create a section through the signed-in Etsy client and
then save its returned name. That explicit action requires `shops_w`; an
unresolvable configured name still refuses deployment rather than creating one.
A shipping profile is also named by its title, with a listing override over
the shop default. Return policies have no title, so they are matched by their
return, exchange and deadline terms. These resources resolve against the live
shop once per run, and a name or terms miss refuses the listing instead of
choosing another resource. See
[shopcatalog.py](../../src/etsy_listings/core/clients/etsy/shopcatalog.py) and the
[Etsy specification](../features/etsy-listing-20260910/spec.md).
