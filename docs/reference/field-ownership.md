# Remote field ownership

Printify creates the connected Etsy listing and routes orders to the printer.
Subsequent writes follow this ownership boundary so a variant update does not
overwrite buyer-facing edits.

| Fields | Writer | Mechanism |
|---|---|---|
| Blueprint and print provider | Printify at creation | Later changes are refused |
| Colour/size matrix, price and SKU | Printify | Product update, then variants-only selective publish |
| Title, description, tags and materials | Etsy client | Listing PATCH |
| Section, production partner, shipping profile, return policy and renewal | Etsy client | Listing PATCH |
| Shop-section resource | Seller action in Details | Explicit signed-in section creation, followed by saving its name on the listing |
| Images, order, alt text and variation-image links | Etsy media stage | Hash-driven uploads and ordered image-id associations |
| Videos and their gallery placement | Etsy video stage | Upload or reattach after image sync |
| Processing time | Observed from Etsy | Drift is reported; inventory is never replaced |

The Printify product also carries real title and description because its API
requires them and they identify the product. Selective publishing leaves those
fields disabled. Retail prices remain in the Etsy shop currency; Printify's
USD display label is not a currency conversion instruction.

A managed Etsy shipping profile is read and asserted as ordinary desired
state, because Printify can attach its own profile on publish despite the
selective-sync flag. Variation-image links must be re-asserted when image ids
change. The tool creates drafts; first publication remains the seller's action.
Retirement and resumption apply to listings that have already left draft.

The enforcing code lives in
[`engine/stages`](../../src/etsy_listings/engine/stages) and the typed
[`Etsy`](../../src/etsy_listings/clients/etsy) and
[`Printify`](../../src/etsy_listings/clients/printify) clients. Rationale for
the integration boundary is in the [architecture decisions](../adr/README.md).
