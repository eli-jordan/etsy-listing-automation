# Printify API findings

What the Printify API actually does when you create a product, measured rather
than read. Named by [implementation-plan.md](implementation-plan.md)'s Phase 2
exit criteria as the place these answers live.

Everything below was produced by running
[`tests/e2e/test_printify_product_e2e.py`](../tests/e2e/test_printify_product_e2e.py)
and a throwaway probe script against the real API on **2026-09-08**, using the
project's own Printify account: one shop, `28819281 "My new store"`,
`sales_channel: disconnected`. Blueprint 706 (Comfort Colors® 1717), print
provider 29 (Monster Digital). Every claim here is a test in that file unless
it says otherwise; the ones that are not testable yet say why.

**No Etsy shop exists yet**, which bounds this document. Everything about
product *creation* is settled. Everything about *publishing* — the sync flags,
the publish lock, `external.id`, draft-vs-live — is either unanswerable here or
answered only in the negative, and is marked as such. Publishing moved to
Phase 3 for that reason.

**That bound has since been lifted.** A shop was connected on 2026-09-10 and
the publishing questions were measured against it; the answers live in
[printify-etsy-integration.md](printify-etsy-integration.md). Where the two
documents touch the same subject, that one is later and wins — including on
this one's claim that *errors have one shape*, which a wider sample falsified.

What this produced elsewhere: PRD decisions **37** (a garment change is refused,
not automated), **38** (a design must be within 10% of the print area), **39**
(what Printify's price integers are denominated in) and **40** (NOK goes to
Printify verbatim); and a correction to the implementation plan's
*Draft-vs-live* section, which was wrong about `visible`.

A **second round** of measurement, taken before Phase 2's implementation began
rather than after its recon, settled what the first round had not had to ask:
shop discovery, whether SKUs are ours, what the product list can be searched
by, and whether a variant entry may be partial. It produced PRD **42**–**48**
and amended **40**. Those sections are marked below.

**One conclusion in this document has since been corrected.** The first version
read Printify's `USD` badge as a currency assertion and recorded prices as USD
cents, which opened risk 12. The measurement was right; the inference was not.
See *Prices, costs, and the currency question* below.

---

## The happy path, in order

| Step | Call | Notes |
|---|---|---|
| 1 | `GET /v1/shops.json` | The shop id. Returns `{id, title, sales_channel}` per shop and nothing else — no currency, no settings. Scoped to the token: it lists exactly the shops those credentials can reach, which is what makes shop discovery a question `setup` can answer rather than one the user has to look up (PRD 42). |
| 2 | `GET /v1/catalog/blueprints/{bp}/print_providers/{pp}/variants.json` | Colour × size → integer variant id, plus per-variant print-area dimensions. Already implemented (`catalog/`). |
| 3 | `POST /v1/uploads/images.json` | The print file. `{file_name, contents}` where `contents` is base64. |
| 4 | `POST /v1/shops/{shop}/products.json` | The product. **200**, not 201. |
| 5 | `PUT /v1/shops/{shop}/products/{id}.json` | Updates. Partial bodies are honoured — with one exception, below. |
| 6 | `POST /v1/shops/{shop}/products/{id}/publish.json` | Requires a connected sales channel. Not reachable from this account. |
| 7 | `DELETE /v1/shops/{shop}/products/{id}.json` | Returns `200 {}`. |

There is no separate "upload a mockup" step and no way to supply our own
photographs: Printify generates its own mockups and that is the only image set
it holds. Our rendered mockups reach Etsy directly, in Phase 3, which is what
the PRD already assumes.

## Every data element a product needs

This is the whole of it. Anything not listed is optional or supplied by
Printify.

```jsonc
{
  "title":              "string",          // required
  "description":        "string",          // required
  "blueprint_id":       706,               // required, integer, immutable after create
  "print_provider_id":  29,                // required, integer, immutable after create
  "variants": [                            // required
    { "id": 73196, "price": 2499, "is_enabled": true }
  ],
  "print_areas": [                         // required
    {
      "variant_ids": [73196],              // see "the coverage rule" below
      "placeholders": [
        { "position": "front",
          "images": [ { "id": "<upload id>", "x": 0.5, "y": 0.5,
                        "scale": 1.0, "angle": 0 } ] }
      ]
    }
  ],
  "visible": false                         // optional, and *does* work — see below
}
```

`x`/`y` are normalised centre coordinates within the placeholder, `scale` is
normalised to the placeholder width, `angle` is degrees. `price` is an integer
in minor units.

Omitting `print_areas` gives
`400 {"code": 8150, "errors": {"reason": "print_areas: The print areas field is required."}}`.

## What comes back is not what you sent

Five differences, each of which will produce a permanent spurious diff if
`printify_product.plan()` compares the response to the request directly.

1. **The whole variant matrix comes back.** A product created with 6 variants
   returns **238**, all but the 6 disabled. That is more than the catalog's own
   228 for the same pair: the extra ten are discontinued combinations
   (`is_available: false`, e.g. `Berry / 4XL`) the catalog no longer offers but
   the product still enumerates. `desired` must compare the **enabled subset**,
   keyed by variant id.
2. **`print_areas.variant_ids` is rewritten to cover everything.** We sent 6
   ids; the product came back with one print area over all 238.
3. **The placed image gains fields.** We send `{id, x, y, scale, angle}`; we get
   back that plus `name`, `type`, `width`, `height`, `flipX`, `flipY`, `src`,
   `layerType` and a per-placement `imageId` distinct from the upload id. A
   comparison must project down to the five we set.
4. **Unused placeholders appear.** We send `front`; `back` comes back with
   `images: []`.
5. **Tags arrive unasked.** We sent none; the product carries the blueprint's
   seventeen (`Unisex`, `DTG`, `Streetwear`, …). These are what a publish would
   push to Etsy, which is precisely what `{tags: false}` in the sync flags is
   for.

Also worth knowing: the **create** response's `images` array (36 entries) is not
the settled one. A subsequent `GET` returns 8 — four camera angles (`front`,
`back`, `folded`, `person-5-context`) for each of the two enabled colours. Read
the product back rather than trusting the create response.

`external` is **absent** from the response when unset, rather than present and
null. Decode it as optional-missing, not optional-null.

## Update semantics — where the surprises are

### `variants` merges by id; it does not replace

A `PUT` carrying three of the six enabled variants left all six enabled.
Omission means "no opinion", not "off". **Retiring a colour requires an explicit
`{"id": …, "is_enabled": false}` for every variant being retired**, which means
the lockfile has to remember the set it enabled — the desired document alone
cannot tell the stage what to turn off.

### The coverage rule: create and update disagree

On **create**, `print_areas.*.variant_ids` lists the variants being created. On
**update**, the union across all `print_areas` entries must cover **every
variant the product has** — all 238 — or Printify answers

```
400 {"code": 8251, "errors": {"reason": "Variants do not match selected blueprint
     and print provider. Please make sure that all product variants are present
     in the `print_areas.*.variant_ids` field"}}
```

The consequence is sharp: **the payload that created the product is rejected as
an update of it.** The stage's `apply` has to build two different print-area
bodies for the two operations, and the update one needs the live variant list,
so it must read the product before it can write it.

### Several print areas may carry different artwork

Partitioning the variants across two `print_areas` entries, each with its own
image, is accepted. This is the API support PRD 30's `on-light` / `on-dark`
artwork needs, and it was an open question until now: dark-ink and light-ink
files on one product, split by colour, work.

### Blueprint and print provider are immutable, silently

`PUT {"blueprint_id": 6}` answers **200** and changes nothing. The quietest
failure in this API.

**The tool refuses this rather than working around it** (PRD 37). The only
automated route Printify leaves is delete-and-recreate, which would take the
Etsy listing behind the product with it — reviews, favourites, search history —
to save retyping a short YAML file. So `plan` fails, names both values, and says
to start a new listing or make the change by hand. What the stage must not do is
PUT and report success, which is what a naive implementation gets for free.

### Partial bodies are otherwise honoured

A `PUT` carrying only `variants` left `title`, `description` and `print_areas`
untouched. The stage may send only what changed.

### But a variant entry is not partial: `price` is always required

Sending the one field that expresses the intent is rejected:

```
PUT {"variants": [{"id": 73196, "is_enabled": false}]}
400 {"code": 8150, "errors": {"reason": "variants.0.price: The variants.0.price
     field is required."}}
```

Identically on the way in — `{"id": …, "is_enabled": true}` with no price is the
same 400. So **retiring a colour means sending a price for the variant being
switched off**, which is the second reason the lockfile has to remember the
enabled set: not just which ids, but what each was priced at. The desired
document cannot supply a price for a colour it no longer offers.

A disabled variant is not price-less on Printify's side either — the spare
variant this was measured against read back `price: 1304`, exactly its `cost`.
Printify seeds the field from the manufacturing cost rather than leaving it
null, so a naive "is the live price what we set?" comparison over the *whole*
matrix would see 232 spurious differences. Another reason `read_live` projects
down to the enabled subset.

## SKUs are ours to set, and we decline to

`variants[].sku` is writable, on create and on update, and reads back verbatim
— `ELA-PROBE-73196` on create, changed to `ELA-CHANGED-XYZ` by a later `PUT`.
Printify auto-generates one only when the field is absent. This was worth
measuring because the API reference does not make it obvious and because a
SKU we controlled would have been the natural key the product API otherwise
lacks.

**We leave it to Printify anyway** (PRD 47). The only thing our own SKU bought
was the duplicate guard below, and that guard has a workable key without it;
against that, a SKU is one more piece of state to keep in sync on a matrix
where every entry already has to carry a price.

## Listing products: a paginator with no filters

`GET /v1/shops/{shop}/products.json` returns a Laravel paginator —
`current_page`, `data`, `first_page_url`, `from`, `last_page`, `last_page_url`,
`links`, `next_page_url`, `path`, `per_page` (50), `prev_page_url`, `to`,
`total`. `limit` and `page` are honoured.

**Nothing filters.** `?title=`, `?search=` and `?sku=` were each accepted with
a `200` and silently ignored, every one returning the full set. So finding a
product by anything other than its id is a walk of every product in the shop,
matched client-side.

That is what shapes the duplicate guard (PRD 48). `POST products.json` has no
idempotency key and no conflict — an identical spec makes a second product —
so the window is: create succeeds, the process dies before the lockfile is
written, and the next run creates a duplicate. The lockfile's
`printify_product_id` closes it in every case but that one. The walk closes
that one too, matching on **title and description**, which are exactly the
concrete seller-owned values PRD 44 requires. It runs only when a create is
already pending, so a normal no-op `plan` never pays for it.

Each product record in the list carries `id`, `title`, `description`,
`blueprint_id`, `print_provider_id`, `variants`, `print_areas`, `images`,
`tags`, `options`, `visible`, **`is_locked`**, `is_deleted`, `created_at`,
`updated_at`, `shop_id`, `user_id`, `views`, `original_product_id`,
`sales_channel_properties`, `print_details`, and the Printify Express flags.
`is_locked` is the field `unlock` will read (risk 6) — visible here even
though nothing on this account can currently set it.

## Uploads are content-addressed

The same bytes uploaded twice return the same `id` and the same `upload_time`,
and the `file_name` takes no part in it — rename the file, same id. So
re-uploading is *safe*; it is merely wasteful, since it still ships the
megabytes. Cache the upload id in the lockfile keyed on the design's content
hash and skip the call.

**Printify validates nothing about resolution.** A 120×140 PNG uploaded happily
and became a product on a 4200×4800 print area without a warning. Nothing
downstream catches a blurry print, which is what makes the PRD's design
validation (17) a real gate rather than a courtesy.

The gate is now concrete (PRD 38): **a design must be within 10% of the
garment profile's print area** — at least 90% of its width and 90% of its height. That
replaces "~300 DPI for the print area", which said the same thing less
checkably: Printify's placeholder dimensions already are the pixels it wants at
its own print resolution, and the editor states the figure outright ("Print area
size: 4200 × 4800 px", matching the garment profile `new` wrote).

The tolerance was set by the first file it was pointed at. The workspace's own
`designs/duke-java-developer.png` is **4000×4800** — 4.8% short on the width
against a 4200×4800 area, a difference no printed shirt will show — and a gate
at exactly 100% would have rejected it. The failure worth catching is the
120×140 file, not the 4000×4800 one, and a rule that fires on work nobody would
call wrong is a rule that gets switched off.

`scale: 1.0` means *fit the image inside the print area*, confirmed against the
editor's canvas: the placed design's bounding box sits exactly on the print-area
outline.

## Prices, costs, and the currency question

`variants[].cost` is a **documented, per-variant manufacturing cost** on every
product response — 1304 for a Comfort Colors 1717 in S/M/L. That is not a
replacement for `newcmd/unofficial_variant_costs.py` (A17, PRD 35), because
`new` needs the cost *before* a product exists, but it is an independent
cross-check on one: the workspace's generated pricing plan quotes $17.53 cost +
shipping for S, and $13.04 manufacturing + $4.49 shipping is exactly that. The
undocumented endpoint is telling the truth.

`price` is accepted **below cost** without complaint — 1 cent against a 1304
cost. No server-side margin guard exists; ours is the only one there will be.

**Nothing in any response names a currency.** Not the product, not the variant,
not the shop. `price` and `cost` are bare integers in minor units of
*something*.

The web app answers it (PRD 39). The product's Pricing tab carries a **`USD`**
badge and reads back the same numbers as the API — retail `USD 29.99` against
`price: 2999`, production cost `USD 13.04` against `cost: 1304` — and states
under the variant table:

> All retail prices are shown in USD. Product costs convert to your preferred
> billing currency set on the Payments page.

The obvious reading of that badge — **`price` is USD cents, always** — is what
this document first recorded, and it is wrong.

### The correction: the badge is a label, and Printify converts nothing

Everything measured above stands. What does not is the currency attached to the
integers, which was inferred from a UI string rather than observed.

Printify's own documentation, in three places, says the retail price is **not
converted on publish**. It is sent to the sales channel as a bare number, and
the channel renders it in the shop's own currency:

> If your store currency isn't USD, make sure to enter a numeric value for the
> product's retail price in Printify, since only numeric values are published to
> your sales channel without conversion. […] if your store currency is British
> Pounds (GBP) and you want to sell the product for GBP 24.99, enter 24.99 as
> the retail price in Printify and ignore the "USD" label.

So `variants[].price` is an integer in **minor units of the connected sales
channel's currency**. Against an NOK Etsy shop, `29900` is `kr 299,00`. Against
the disconnected shop this document was written from, USD is simply the honest
default, which is why the badge and the measurement agreed.

Three corroborating facts, all from Printify's documentation rather than this
account:

- **Changing the billing currency would not have helped.** It converts *costs*
  only — retail price and profit are explicitly excluded, "due to a technical
  limitation".
- **NOK is not offered anyway.** Printify's billing currencies are AUD, CAD,
  EUR, GBP and USD.
- **The profit figures Printify shows become meaningless**, by its own
  admission, once the channel currency differs — an NOK number minus a USD cost.
  Its Listing-health "Pricing: too high" flag goes the same way. Both were
  already advisory; now they are noise.

There is one real server-side consequence. **Printify refuses to publish when
the numeric retail price is below the numeric USD production cost** — it reads
that as negative profit. NOK clears it by roughly 10× (299 against 13.04), so
it will not fire in normal use, which is exactly why `plan` should assert it:
the check that never fires is the one that catches a mis-scaled price.

Recorded as PRD **39** (restated) and **40**. Risk 12 is closed — not decided
between its two options, but dissolved, since both assumed a conversion that
does not happen. What remains is an observation, not a choice: publish one
product at `29900` into the NOK shop and read back what Etsy stored. Until then
this section is documentation, not measurement, and is marked as such.

### Shipping is the same mechanism with the opposite consequence

Printify sends shipping rates to Etsy as bare numerals too. A `$4.49` rate on an
NOK shop publishes as `kr 4,49` — about a 90% shortfall per shipment. Printify
documents this and offers only two ways out: an Etsy shop in USD, or shipping
profiles maintained on Etsy that Printify never overwrites. `publish.json`'s
`shipping_template` boolean is the lever ("Used by Etsy and Amazon sales
channels only. If set to false, product shipping template will not be
updated"), and nothing in this tool sets it yet.

This is PRD **risk 13**, and unlike risk 12 it is a genuine open decision that
blocks Phase 3 rather than a misreading to correct.

## Publishing, as far as this account can see

`POST publish.json` against a shop with no sales channel returns

```
400 {"code": 8254, "errors": {"reason": "Shop #28819281 of product \"…\" is not
     connected to sales channel"}}
```

and leaves the product **unlocked**. So the publish path cannot be exercised at
all from here, and neither can the lock it is supposed to create.

The lock endpoints do exist and answer: `publishing_succeeded.json` (with an
`{external: {id, handle}}` body) sets `external` on the product and returns
`{"product_id": …}`; `publishing_failed.json` returns the same and cleared
nothing, because nothing was locked; `unpublish.json` returns `200 {}` and
clears `external` back to absent. These are the callbacks a *sales channel*
makes, not calls this tool should be making — with the exception of
`publishing_failed.json`, which the PRD's `unlock` command is built on, and
which remains unverified in the state it exists for.

### Rate limits, confirmed from response headers

| Endpoint group | `X-RateLimit-Limit` |
|---|---|
| `/v1/catalog/*` | 100 |
| shop + upload endpoints | 600 |
| `publish.json` | 200 |

Which matches the plan's `printify:catalog` / `printify:global` /
`printify:publish` buckets. The headers are per-response, so the limiter can be
corrected from them rather than trusting the constants.

### Errors have one shape

Every failure observed:

```json
{"status": "error", "code": 8251, "message": "Validation failed.",
 "errors": {"reason": "…", "code": 8251}}
```

`errors.reason` is a human sentence naming the field. The client's error
decoding can rely on this shape and should surface `reason` verbatim.

## `visible` is writable — the plan is wrong about this

[implementation-plan.md](implementation-plan.md)'s section *"Draft-vs-live cannot
be set through the API — PRD risk 5, resolved in one direction"* concludes, from
the API reference marking `visible` read-only and omitting it from the request
bodies, that **nothing this tool sends can affect whether a publish lands as a
draft**.

That premise is false. Measured:

- `POST products.json` with `"visible": false` creates the product hidden, and
  it reads back `visible: false`.
- `PUT {"visible": false}` on an existing product sticks, and `true` puts it
  back.

What this does **not** yet establish is the thing risk 5 actually cares about:
whether a hidden product publishes to Etsy as a draft. That needs a connected
Etsy shop. But the plan's stated reason for treating the question as closed — no
API surface at all — is gone, and the section needs amending rather than being
left to mislead the next reader. The tripwire it describes (warn if a managed
product comes back `visible: true`) may turn into an actual lever.

## What the web app shows for an API-created product

Worth its own section, because it is the check that a product is *configured*
rather than merely accepted. Opening the probe product in Printify's own UI:

- **My Products** lists it as `Monster Digital · Comfort Colors® 1717`,
  *"2 comfort colors® colors · 3 clothing sizes · Total 6 variants"*, all in
  stock. The enabled subset is what the UI counts — the other 232 variants are
  invisible there, which is a second reason to treat the enabled set as the
  product's real content.
- The **Pricing** tab reads back exactly the API's integers, in USD, as above.
- The **editor** draws the design inside the print-area outline at the placement
  we sent, and states *"Print area size: 4200 × 4800 px"* and *"Production cost:
  USD 13.04"*.
- **Publishing settings** says *"Oops! You haven't connected a store"* — the
  disconnected shop, from the other side.
- The product carried a red **"Publishing error"** status, which is what
  `publishing_failed.json` puts there. Useful: that endpoint has a visible
  effect in the UI even when it clears no lock, so `unlock` will be observable
  when there is finally something to unlock.
- **Listing health** flagged *"Pricing: Too high"* against Printify's own
  category data ($24.99–$25.99 typical). Advisory only; nothing blocks.

One discrepancy: immediately after load the UI said *"0 mockups selected"* while
the API reported all 8 with `is_selected_for_publishing: true`; it settled to
*"8 mockups selected"* a moment later. Treat the UI's count as a lagging view,
not a second source of truth. Writing `images` back through `PUT` with
`is_selected_for_publishing` flipped had no effect, so mockup selection is not
API-controllable — which costs us nothing, since our own mockups go to Etsy
directly.

## PRD risk register, updated

| Risk | Status |
|---|---|
| 2 — do the selective-sync booleans stop Printify overwriting our copy? | **Open.** `publish.json` is unreachable without a sales channel. Phase 3. |
| 3 — does republishing `{variants: true}` disturb an active listing? | **Open**, same reason. |
| 5 — can a publish be made to land as a draft? | **Reframed.** `visible` *is* settable (above); whether that produces an Etsy draft is untested. The shop-side setting remains the documented lever. |
| 6 — is `unlock` real? | **Partly.** `publishing_failed.json` exists and returns 200, and the product record carries `is_locked`, so the state `unlock` acts on is at least observable. Whether the endpoint clears a genuine publish lock is untestable here. |
| 7 — better blueprint category filter than keyword matching? | Unchanged; nothing in the product API offers one. |
| 11 — the undocumented cost endpoint | **Corroborated.** Its numbers match `variants[].cost` on a real product. |
| 12 — Printify prices in USD, this shop's in NOK | **Closed.** The conflict came from reading a UI badge as a currency. Printify converts nothing: `price` is minor units of the *channel's* currency, so NOK passes through unchanged. One confirmation still owed against a live NOK shop. |
| 13 — Printify's shipping rates publish as bare numerals | **New.** `$4.49` becomes `kr 4,49`. `shipping_template: false` is the lever; what shipping the tool should own is undecided and blocks Phase 3. |

## Open questions, for when an Etsy shop exists

**The shop now exists.** Questions 1, 2, 3 and 7 are answered in
[printify-etsy-integration.md](printify-etsy-integration.md), and 5 is half
answered there — the publish lock is real, its remedy still unobserved.
Questions 4, 6, 8 and 9 remain open. The list is kept as written because what
was asked, and why, is the useful part; go there for what came back.

1. **Does `29900` land on the NOK listing as `299,00`?** Printify's
   documentation says yes and risk 12 is closed on that basis; this is the
   measurement that would make it a fact. The same run answers whether the
   published shipping rate arrives as `kr 4,49` (risk 13).
2. Does a `visible: false` product publish to Etsy as a draft?
3. Do the selective-sync booleans behave as documented (risk 2)?
4. Does `{variants: true}` republishing disturb an active listing (risk 3)?
5. Does a publish lock the product, and does `publishing_failed.json` clear it
   (risk 6)?
6. Is the shop's draft setting a persistent per-shop default, or does it revert?
   (The question the plan's Phase 2 exit criteria names.)
7. **Does the first publish send images regardless of the sync flags?** Printify
   documents selective sync as appearing only for a *previously published*
   product — "when publishing a product for the first time, all mandatory
   product details will be published". The web app's known wrinkle for title and
   description is already recorded in the PRD as harmless; images are not
   harmless. If `publish.json` ignores `{images: false}` on a first publish,
   every listing is born carrying Printify's generated mockups — 8 of them on
   the probe product, against Etsy's 20-image cap — and the media stage has to
   **delete** them before uploading ours, not merely add. That changes what the
   stage does, so it needs answering before the stage is written (PRD 41).
8. **How do per-colour variation images get set?** Etsy shows a thumbnail per
   colour swatch, and Printify's connector sets those natively because its
   mockups are linked to variants. Ours are not: the `colour-matrix` renders are
   plain listing images. Etsy's `updateVariationImages`
   (`POST .../variation-images`) is the endpoint — it binds `image_id` to a
   `property_id`/`value_id` pair, overwrites *all* variation images on every
   call, and permits only one property. Nothing in the plan accounts for it.
   Cosmetic on day one, but it is the difference between a colour selector that
   previews the shirt and one that does not.
9. **Is `updateListing`'s `image_ids` a cheaper media sync than delete-and-
   re-upload?** The PRD states flatly that there is no update-image endpoint and
   builds full-replace media sync on that premise. The v3 reference lists
   `image_ids` on `updateListing` as "an array of numeric image IDs of the
   images in a listing, which can include up to 20 images" — an ordered set,
   which reads like reorder-and-subset without re-uploading bytes. If it works
   that way, reordering media stops costing ten uploads. (The same line says 20
   where the PRD's constraints say 10; one of the two is stale.)

### Custom mockups are a web-app feature, not an API one

Recorded here because the UI offering it makes the opposite look plausible.
Printify's Mockup Library does accept uploaded mockups (JPG/PNG/SVG, up to
30,000 px square) and links them to variants — but there is no endpoint behind
it. The API reference marks the product's `images` array **READ-ONLY**
("Mock-up images are read only values"), which matches what this account
measured: writing `images` back through `PUT` with `is_selected_for_publishing`
flipped had no effect. The Library is further documented as available for every
sales channel "except PrestaShop and API stores".

A natively-connected Etsy shop is not an API store, so the Library *will* be
available in Printify's web UI — as a per-product manual click-through. Which
means this is not a choice between two automatable paths. Our mockups reach Etsy
directly, as the PRD already assumed; the only thing the Printify route would
have bought is the variant linking in open question 8, which Etsy's own endpoint
can do instead.

## What this means for the `printify_product` stage

Concretely, from the above:

- `desired` is `{title, description, blueprint_id, print_provider_id,
  enabled: {variant_id: price}, print_areas: {variant_id_group: placement}}` —
  the *enabled subset*, nothing more. `title`/`description` are in there because
  the API demands them at create and because they are the duplicate guard's
  match key (PRD 44, 48), not because Printify owns them: the publish flags stay
  `{title: false, description: false}` so they never reach Etsy through Printify
  (PRD 41).
- `read_live` reads the product and projects it the same way: enabled variants
  only, placement fields down to the five we set, `visible` kept as a tripwire.
  Live variants also carry `cost` and `is_available`, which the projection drops
  — they are Printify's facts, not our desired state.
- `read_live` returns `None` without a request when the lockfile has no
  `printify_product_id`. There is nothing to read before the first `apply`, and
  demanding a token to discover that would break every workspace that has not
  reached Phase 2 yet.
- `apply` branches on whether `remote.printify_product_id` exists, because the
  create and update bodies genuinely differ (the coverage rule), and update
  needs the live variant list first.
- The create branch walks `products.json` first and refuses if a product already
  matches on title and description (PRD 48). Only that branch pays for it.
- The lockfile needs `remote.printify_product_id` (a **string**),
  `remote.printify_upload_id` per artwork, and the enabled variant set **with
  prices** — because omission cannot disable and a disable cannot omit a price.
- A changed `blueprint`/`print_provider` is a hard error at `plan` time, not an
  update and not a recreate (PRD 37).
- Design validation gets the concrete rule it was missing: pixel dimensions
  within 10% of the print area on each axis (PRD 38). It belongs at `plan` time,
  before the upload, since nothing after it will object.
- Prices stay `Money` all the way to the stage boundary and are serialised to
  minor units of the shop currency, unconverted (PRD 39, 40). No FX anywhere in
  `apply`.
- **The price-above-cost assertion belongs to the publish stage, not this one**
  (PRD 40, amended). Printify enforces it at publish, and `variants[].cost` only
  exists on a product that already exists — before the first create there is no
  documented source for it at all, and the undocumented one is walled off from
  the engine by design (A17). Phase 3 gets the check for free from its own
  `read_live`; asserting it here would mean either skipping it on the run that
  matters or breaching A17 to reach cost data.
- Placement is fixed: centred, `scale: 1.0`, `angle: 0`, into
  `garment_profile.placeholder` (PRD 45). PRD 38's ≥90% gate is what makes that the
  right constant rather than a default nobody chose.
- A colour × size cell the catalog does not offer is reported and skipped, not
  fatal (PRD 46) — a discontinued combination is Printify's fact, not the
  user's mistake.
