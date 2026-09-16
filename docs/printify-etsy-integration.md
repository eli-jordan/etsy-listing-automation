# Printify → Etsy integration findings

What happens when Printify publishes a product to a natively-connected Etsy
shop, measured rather than read. The companion to
[api-findings.md](api-findings.md), which stops exactly where this starts: that
document was written against a `sales_channel: disconnected` shop and had to
mark every publishing question unanswerable.

Everything below was produced on **2026-09-10** by a staged probe script
against the real APIs, using the project's own accounts:

| | |
|---|---|
| Printify shop | `28877318 "NaturallyInkedStudio"`, `sales_channel: etsy` |
| Etsy shop | `67961328 NaturallyInkedStudio`, `currency_code: NOK`, `shipping_from_country_iso: NO` |
| Etsy app | `application_id 1514749864135`, granted `listings_r listings_w shops_r` |
| Garment | Blueprint 706 (Comfort Colors® 1717), provider 29 (Monster Digital), `price: 18000` |
| Round 1 | Product `6aa27b63279c4459f80f45c3` → Etsy listing `4572537111` |
| Round 2 | Product `6aa28234e786908bc80ffe38` → Etsy listing `4572550919` |

Two rounds, because the first answered only half the question.

**Round 1 — does publishing work, and do the flags hold?** One product created
`visible: false`, published with **every selective-sync flag off**, read back
through the Etsy API, then forced into disagreement with Etsy and republished.

**Round 2 — can we actually write the listing, and does a variant change
survive it?** A second product taken through the full production cycle: delete
Printify's images, upload our renders in rank order, write our copy, then change
variants on the Printify side and republish `{variants: true}`. This is the one
that exercises what the Phase 3 stages will do.

Both products were unpublished and deleted afterwards. Both Etsy drafts
survived — see *Cleanup does not clean up*. That sequence (unpublish, then
DELETE) is not the one the tool will use; connected DELETE takes the draft
(PRD 63).

**One conclusion from round 1 was corrected by round 2**: the number of images
Printify sends. See *The first publish sends images regardless*.

**The Printify shop id changed since api-findings.md was written.** Connecting
the Etsy store replaced the API store: `28819281` is gone and its token now
answers `401`. That is not incidental — it produced a defect, recorded under
*Three answers for one absence* below.

---

## What this settles

| Risk | Was | Now |
|---|---|---|
| 1 — Etsy API approval | Unknown lead time, hard prerequisite | **Retired.** The key pair authenticates |
| 2 — do the selective-sync booleans work? | Open; unreachable | **Confirmed.** They do |
| 3 — does `{variants: true}` disturb an active listing? | Open | **Answered for a draft:** it does not. Still open for an *active* listing, deliberately not created |
| 4 — does `updateListing` interact badly with Printify-managed variations? | Open | **Answered.** Copy, tags, media and policy writes all left inventory intact |
| 5 — draft or live? | Open; `visible` writable but meaning unknown | **Confirmed.** `visible: false` publishes as a draft |
| 6 — is `unlock` real? | Partly; the lock was never observed | **The lock is real.** Its remedy still is not |
| 12 — NOK passthrough | Closed on documentation; one measurement owed | **Measured.** `18000` → `180,00 kr` |
| 13 — shipping rates publish as bare numerals | Named, undecided, blocking | **Confirmed, and the documented lever does not prevent it** |
| Open question 7 — does the first publish send images anyway? | Open, and it changes the media stage | **Yes.** Several, arriving asynchronously, one at rank 1 |
| Open question 9 — is `image_ids` a cheaper media sync? | Open; the PRD assumed no reorder existed | **Yes**, and one of its two encodings destroys images |

---

## The publish path, in order

| Step | Call | What came back |
|---|---|---|
| 1 | `POST /v1/shops/{shop}/products.json` with `"visible": false` | `200`. Reads back `visible: false`, plus **17 blueprint tags Printify invented** (`TikTok`, `US Elections Season`, `Back to School`) |
| 2 | `POST /v1/shops/{shop}/products/{id}/publish.json` | `200 {}`, immediately. The body is the sync flags |
| 3 | poll `GET .../products/{id}.json` | `is_locked: true` for roughly 8 seconds, then `false` with `external` populated |
| 4 | `GET /v3/application/listings/{listing_id}` | The Etsy listing |

`external` on the finished product:

```json
{"id": "4572537111",
 "handle": "https://www.etsy.com/listing/4572537111/experiment-phase-3-publish-probe-do-not",
 "shipping_template_id": "314944410819",
 "type": 4}
```

`type: 4` is undocumented and unexplained; it is recorded here only so the next
reader does not think it means something. `shipping_template_id` is the
important one, and it is discussed under *Shipping* below.

**The lock is real, and it is the thing `unlock` was designed for.** `is_locked`
genuinely cycles `true` → `false` across a publish, so PRD risk 6's premise —
that there is a lock state worth clearing — holds. What remains unverified is
the *remedy*: `publishing_failed.json` was never exercised against a genuinely
stuck publish, because no publish got stuck. `unlock` should be built, but its
one job is still unobserved.

---

## The sync flags work — with one exception that matters

Sent on every publish in this probe:

```json
{"title": false, "description": false, "images": false, "variants": false,
 "tags": false, "keyFeatures": false, "shipping_template": false}
```

**On a republish, they are honoured.** The conclusive test made the two sides
genuinely disagree — Etsy carrying `"OUR COPY - written by the tool, must
survive republish"` and tags `["experiment", "donotbuy"]` written through
`updateListing`, Printify still carrying its own title — and then republished.
A real publish cycle ran (`is_locked` observed `true`, then `false`) and Etsy
kept our copy, our description and our tags. PRD risk 2 is answered: the
architecture's central assumption holds.

An earlier attempt at the same test proved nothing and is recorded so nobody
repeats it: republishing with **nothing changed on Printify's side** completed
with `is_locked` never observed true. A republish that does no work overwrites
nothing, so the copy surviving it is not evidence. Force a divergence first.

**Tags never arrive at all.** Printify's 17 invented blueprint tags did not
reach Etsy even on the first publish, which arrived with `tags: []`. Good news,
but it is the flag being honoured on a field Etsy treats as optional — not a
general rule, as the next section shows.

### The first publish sends images regardless — open question 7, answered

Printify's mockups arrive despite `{images: false}`. Selective sync applies only
to a *previously published* product, exactly as its documentation says, and this
is the answer that costs the media stage work.

**How many arrive is not fixed, and they arrive late.** Reading the second
probe's listing a few seconds after `external.id` appeared showed one image;
reading it again minutes later showed **four**, two of them sharing `rank: 1`.
The first round was measured once, early, and recorded "one image" — that
number was a race, not a result. Anything that counts a freshly published
listing's images is reading a value still being written.

Two consequences, and they shape the stage:

- The media stage must treat Printify's image set as **an unknown number of
  images, settled at an unknown time**. It cannot branch on having seen one.
- Rank 1 is the listing thumbnail, and Printify lands there. Ours have to
  displace it. PRD 41's full-replace media sync is the right shape; this is why
  it cannot be an append.

The PRD anticipated Printify's full mockup set — 8 images on the Phase 2 probe
product — arriving and needing to be cleared. Four is closer to that fear than
to the one image the first round appeared to show.

### Reading images back needs the listing, not the images endpoint

`GET /v3/application/shops/{shop}/listings/{listing}/images` returns
`404 {"error": "Resource not found"}` for **every** id, valid or invented, so a
404 there says nothing about whether images exist. It cost one wrong conclusion
during this probe before the cross-check caught it.

Use `GET /v3/application/listings/{listing_id}?includes=Images` instead, which
returns the images inline and is how every count here was established.

`GET /v3/application/listings/{listing_id}` is also the only working read for a
single listing: the shop-scoped `/shops/{shop}/listings/{listing}` path exists
for `PATCH` and `DELETE` but **404s on `GET`**. That asymmetry cost a false
"our copy was overwritten" verdict during the first round, because a failed read
and an overwritten field look identical if the status code is not checked.

---

## The Etsy write surface

What the copy and media stages actually have to call, measured against a
published draft.

### A listing cannot be emptied of images

`DELETE .../listings/{listing}/images/{image_id}` returns `204` and works —
until the last one:

```
400 {"error": "Listings must have at least 1 image.
                Please add another ListingImage before trying to delete."}
```

**So the media stage must upload before it deletes**, not the reverse. A stage
written as "clear what is there, then upload ours" strands one of Printify's
mockups on every listing, and the one it strands is whichever Etsy refused to
remove.

### Uploads work, and are laxer than Etsy's guidance suggests

`POST .../listings/{listing}/images` (multipart, `listings_w`) returned `201`
for every render tried, including a **480×576** one — below the 500px shortest
side Etsy's own seller guidance asks for. Do not rely on the API to reject an
undersized render; the tool's own validation is the only thing that will.

`rank` does not insert. Uploading at a rank another image already holds
produces **two images sharing that rank** rather than pushing the other down —
observed with a leftover Printify image and a new upload both sitting at rank 3.
The `overwrite` parameter exists for this case and was not exercised.

### `image_ids` reorders without re-uploading — open question 9, answered

The PRD builds full-replace media sync on the premise that there is no way to
reorder without re-uploading. **There is.** `PATCH updateListing` with
`image_ids` set to an ordered id list returned `200` and produced exactly that
order, no bytes re-sent.

**But the encoding decides whether it reorders or destroys.** Sent as repeated
form keys (`image_ids=a&image_ids=b&image_ids=c`) Etsy answered `200` and left
the listing holding **one image** — it took a single value and dropped the rest.
Sent as one comma-separated value (`image_ids=a,b,c`) it did the right thing.

| Encoding | Status | Result |
|---|---|---|
| repeated keys | `200` | **three images became one** |
| comma-separated | `200` | exact order, nothing lost |

Both answer `200`. A media stage that gets this wrong deletes a listing's
photographs and reports success, which makes it worth a test of its own rather
than a comment.

`image_ids` is an **ordered full-replacement set**: any id omitted is detached
from the listing. Detachment is recoverable — the dropped ids were re-attached
by the very next call, and `uploadListingImage` documents `listing_image_id` for
exactly this — but nothing about the response says work was lost.

### The ids `setup` resolves must exist

`PATCH` with the placeholder `shop_section_id` that was sitting in this
workspace's `shop.yaml`:

```
400 {"error": "There was a problem with /shop/section/id : Shop section not found."}
```

`return_policy_id` re-asserted explicitly returned `200`. So both ids are real
levers, and a stale one fails the whole `updateListing` rather than being
ignored — which is the right behaviour and makes `setup`'s id resolution
load-bearing.

---

## The production cycle: edit on Etsy, change variants in Printify — risk 3

The workflow the whole design depends on, run end to end against a draft:

1. Printify's mockups deleted, three of our renders uploaded in rank order.
2. Our title, description and tags written through `updateListing`.
3. On the **Printify** side: one variant repriced (`18000` → `19900`), a whole
   size added (L, both colours), and one variant retired (Red/M).
4. Republished with `{variants: true}` and every other flag `false`.

**Everything of ours survived.**

| | Before | After |
|---|---|---|
| Title | ours | **ours** |
| Tags | `["roundtwo", "probe"]` | **unchanged** |
| Images | our 3 renders, our order | **unchanged — no mockups re-added** |
| `state` | `draft` | `draft` |

And the variant change landed correctly:

| Offering | Price | `is_enabled` |
|---|---|---|
| Black / S | **`19900/100`** — repriced | `true` |
| Black / M | `18000/100` | `true` |
| **Black / L** — added | `18000/100` | `true` |
| Red / S | `18000/100` | `true` |
| **Red / M** — retired | **`0/100`** | **`false`** |
| **Red / L** — added | `18000/100` | `true` |

This is PRD risk 3's question answered **for a draft**: republishing
`{variants: true}` does not disturb the copy, tags or media this tool owns. The
post-publish price-change workflow works.

**It is not answered for an active listing**, which is what risk 3 literally
asks and what this probe deliberately would not create. A draft and an active
listing differ in ways Etsy cares about — an active one is indexed, has a
`state_timestamp` that matters, and can be renewed — so the risk stays open in
the register even though the mechanism now looks sound.

**A retired variant is indistinguishable from one never offered.** Both read
`price: 0, is_enabled: false`. Nothing in the Etsy response says which, so drift
detection cannot use the listing to tell "we retired this colour" from "this
cell was never in the matrix".

### Printify reuses one shipping profile across products

The second product's publish attached **the same** `shipping_template_id`
(`314944410819`) the first had created, rather than making another. So the
US-origin, USD-numeral profile described above is a per-shop artefact created
once, not per-listing litter — which makes it easier to replace by hand, and
makes the `updateListing` reassignment a per-listing job against a single known
bad id.

---

## Draft, not live — risk 5

The listing arrived as `state: "draft"` and stayed there through a republish. A
product created `visible: false` publishes to Etsy as a draft.

This is the whole of PRD risk 5's practical concern, and the lever is one the
tool already pulls: `create_product` sets `visible: false` unconditionally.
Whether `visible: true` publishes as *active* was deliberately not tested — it
would mean putting a live listing in a real shop to learn something the tool
never needs to do.

**The shop-side setting remains invisible to the API.** `/v1/shops/{id}.json`
and `/v1/shops/{id}/settings.json` both `404`; `GET /v1/shops.json` returns only
`{id, title, sales_channel}`. So the tool can never *verify* the draft setting,
and should not pretend to. `visible: false` is the guarantee; the shop setting
is a second line of defence the user configures once, unobserved.

### A draft is invisible to the default listing query

`GET /v3/application/shops/{shop}/listings` returned `count: 0` with the draft
sitting in the shop. Drafts appear only under `?state=draft`; `?state=active`
returned `count: 0` correctly.

Anything that reconciles our listings against the shop must pass `state`
explicitly, or it will conclude that every listing it has ever created has
vanished — and, worse, that the correct repair is to create them again.

---

## Prices: NOK passes through, exactly as documented — risk 12

The measurement PRD risk 12 still owed:

```json
"price": {"amount": 18000, "divisor": 100, "currency_code": "NOK"}
```

`18000` was sent to Printify as a bare integer. It arrived on the NOK listing as
**180,00 kr**. No conversion, no rate, nothing volatile anywhere near a hash.
PRD 39 and 40 are correct and risk 12 is now closed on measurement rather than
on Printify's documentation.

Per-variant inventory agrees: `price_on_property: [513, 514]` — price varies on
**both** colour and size — with each enabled offering reading `18000/100 NOK`.

### Etsy materialises the full matrix and disables what Printify did not enable

Three variants were created (Black/S, Black/M, Red/S). Etsy's inventory came
back with **four** offerings, the fourth being the cross-product cell nobody
asked for:

| Offering | Price | `is_enabled` |
|---|---|---|
| Black / S | `18000/100` | `true` |
| Black / M | `18000/100` | `true` |
| Red / S | `18000/100` | `true` |
| **Red / M** | **`0/100`** | **`false`** |

A `0`-priced offering looks alarming and is not: it is disabled, and Etsy
requires the grid to be rectangular. Recorded because a future check that
asserts "no offering costs nothing" would fire on every listing whose colour ×
size matrix is not complete.

---

## Shipping: the documented lever does not stop it — risk 13

**This is the finding that costs money, and it is worse than the PRD assumed.**

The PRD identified `shipping_template: false` as the way to stop Printify
overwriting Etsy shipping. It was sent `false` on every publish in this probe.
Printify created and attached a shipping profile anyway:

| | |
|---|---|
| Title | `Standard: Monster Digital, Kids clothes, Long-sleeve, T-Shirt, Tank Top, V-neck` |
| `origin_country_iso` | **`US`** — the shop ships from `NO` |
| `profile_type` | `manual` |

And the rates, read back from the NOK shop:

| Destination | Primary | Secondary |
|---|---|---|
| default (`none`) | **`kr 10,39`** | `kr 4,00` |
| US | **`kr 4,95`** | `kr 2,40` |
| Canada | `kr 9,69` | `kr 4,39` |
| Australia | `kr 12,99` | `kr 4,99` |
| EU (27 countries) | `kr 13,49` | `kr 4,00` |

These are Printify's USD rates rendered as NOK numerals: `$10.39` became
`kr 10,39`. At roughly 10 NOK to the dollar that is a **~90% shortfall on every
shipment**, exactly the mechanism risk 13 describes — now measured rather than
predicted. The `origin_country_iso: US` is a second, independent error: Printify
set the origin to the print provider's country rather than the shop's.

**What this changes.** The requirement was already that this tool owns a
shipping profile on the Etsy side. The finding is that owning one is not enough,
because `shipping_template: false` does not prevent Printify's profile being
created and attached on first publish. The tool must **set
`shipping_profile_id` through `updateListing` after every publish**, treating
the flag as a hint rather than a guarantee.

Two things this probe could not separate, both worth one measurement before the
shipping stage is written:

1. Whether `shipping_template: false` at least prevents *re-attachment* on a
   republish. The id was unchanged across the second publish, which is equally
   consistent with the flag working and with Printify reusing the profile it
   made.
2. Whether an `updateListing`-assigned profile survives a subsequent Printify
   republish at all.

**A profile is referenced by title, and titles are free text.** Resolution goes
through `GET /v3/application/shops/{shop}/shipping-profiles` (scope `shops_r`),
matching on `title`. That list includes profiles with `is_deleted: true`, so the
resolver must filter them, and a rename in Shop Manager breaks the reference —
which must fail loudly rather than fall back to whatever Printify attached.

### Printify also created a return policy

`return_policy_id: 1513785862328` — `accepts_returns: true`,
`accepts_exchanges: true`, `return_deadline: 30`. The shop had **zero** return
policies before the publish and one after. Not a problem, but it means the
shop's policy set is something Printify writes to, so `setup` resolving a
`return_policy_id` is resolving against a moving target.

---

## `updateListing` against a Printify-managed listing — risk 4

A `PATCH` setting `title`, `description` and `tags` on the published draft
returned `200` and left the Printify-managed inventory untouched:
`quantity: 2997` unchanged, all four offerings intact with their prices and
`is_enabled` flags. Risk 4 asked whether Etsy writes against a listing carrying
external inventory would disturb the variations. On the copy fields, they do
not.

Round 2 widened this to the rest of the surface — `image_ids`,
`return_policy_id`, `shop_section_id`, and image upload and delete — all
against a listing Printify was managing, and all without disturbing its
inventory. Together with the variant republish above, risk 4 is answered as far
as this tool's own writes go.

One case remains untested: `updateListing` called **while a publish holds the
lock**. Every write here was made between publishes, and the stage ordering
should keep it that way rather than discover what concurrent writes do.

**Printify rejects titles with too many capitals.** A `PUT` setting the product
title to `PRINTIFY SIDE TITLE - should NOT reach Etsy` was refused with
`400 code 61003: "Product is invalid. Title contains excessive caps."` Phase 4's
copy validation should know this rule before a generator produces a title that
trips it.

---

## Three answers for one absence

`GET /v1/shops/{shop}/products/{id}.json` has **four** distinct failure shapes,
three of which mean "this shop does not have that product":

| Situation | Status | Body |
|---|---|---|
| Id unknown to any shop | `404` | `{"error": "Not found", "request_id": …}` |
| **Id real, but held by another shop** | **`400`** | `{"code": 8104, "errors": {"reason": "Product \"…\" does not belongs to shop #…"}}` |
| Shop unreachable by this token | `401` | `{}` |
| Malformed id | `422` | `{"error": "Invalid product ID format."}` |

`get_product` treated only `404` as absence, so the `8104` case propagated as a
`PrintifyApiError` and ended the listing. It is not a corner case: **reconnecting
a store changes the shop id**, and every lockfile written against the old one
then names a product the new shop has never held. This workspace was in exactly
that state, and the next `plan` would have failed rather than re-created.

Fixed — `8104` now reads as absence, by code rather than by "any 400", so a
genuine validation error still raises instead of silently becoming a create.

Two smaller shapes are worth recording against api-findings.md's claim that
*"errors have one shape"*: the `404` and `422` bodies above carry neither `code`
nor `errors.reason`, and Printify's `decode_error` does not read a top-level
`error` key — where Etsy's does — so those two surface as a raw JSON blob
including `request_id`.

---

## Etsy scopes, measured

The scope a call needs is not uniform across a resource, so it was measured
rather than assumed. With **only the app key pair** and no bearer:

| Call | Result |
|---|---|
| `openapi-ping` | `200` |
| `findShops` | `200` |
| `getShop` | `200` |
| `getShopSections` | `200` |
| `getShopReturnPolicies` | `200` |
| `getShopShippingProfiles` | `401` — *requires scope: shops_r* |
| `getListingsByShop` | `401` — *requires scope: listings_r* |

This confirms the claim in `clients/etsy/shops.py` that `setup`'s four calls are
unscoped, and therefore that a workspace can resolve every id in `shop.yaml`
before anyone opens a browser (PRD 49).

**The granted set `(listings_r, listings_w, shops_r)` is sufficient for Phase 3
as scoped**, given that shipping profiles are created by hand in Shop Manager
rather than by this tool. Reading a profile to resolve a title needs `shops_r`;
attaching it needs `listings_w` on `updateListing`. Only
`createShopShippingProfile` needs `shops_w`, and nothing calls it. Since
changing `SCOPES` forces every user through consent again (PRD 50), this is
worth stating plainly rather than rediscovering.

`uploadListingImage` and `updateVariationImages` both need only `listings_w`,
so the media work of Phases 3 and beyond needs no further consent either.

### A missing scope is a 401, not a 403

Etsy answers a missing scope with `401` and an error string naming the scope:
`"Access token is required for this request (requires scope: shops_r)."`

Both transports discard that. `Transport.request` branches on
`status_code in (401, 403)` and raises an auth error built from the status code
alone, so a scope problem is reported as "check your keystring" — pointing at a
credential that is fine. Printify has the same defect with a sharper edge: an
unreachable shop id is a `401`, so a stale `shop.yaml` reads as an invalid
token. **Not fixed**; it is a design question about whether the auth errors
should carry the server's own text.

---

## Cleanup does not clean up

This probe called `unpublish.json` then `DELETE`. That sequence is what the
measurements below describe; it is not what the tool will do (PRD 63).

`POST unpublish.json` returned `200 {}` and cleared `external`;
`DELETE products.json` returned `200 {}`. The **Etsy listing survived both**,
still `state: "draft"`, still carrying our copy.

So **unpublish then delete** orphans the Etsy listing rather than retracting
it. A later e2e teardown — `DELETE` of a still-connected product, no
unpublish — returned `404` for the listing that product had minted. The
generalisation this section originally drew (any Printify delete orphans
Etsy) mixed the two sequences. The tool deletes connected, never unpublished
first, and fails the apply rather than wiping local files if the draft
survives. `listings_d` stays outside `SCOPES` (PRD 50). Live listings are
never deleted this way.

Both probe listings — `4572537111` and `4572550919` — were left behind by the
unpublish-then-delete path and needed deleting by hand.

---

## What is still open

1. **Does republishing `{variants: true}` disturb an *active* listing?** PRD
   risk 3. The mechanism is now proven on a draft — copy, tags and media all
   survived — but an active listing is a different object to Etsy, and creating
   one means a live listing in a real shop. The residual risk is small and the
   test is expensive; it is the one open item that may be worth simply accepting.
2. **Does `publishing_failed.json` clear a genuine publish lock?** The lock is
   now known to be real; its remedy is still inferred. No publish in this probe
   got stuck, and one cannot be manufactured on demand.
3. **The two shipping questions above** — whether the flag prevents
   re-attachment, and whether an `updateListing`-assigned profile survives a
   republish. Both block the shipping stage.
4. **Per-colour variation images.** `updateVariationImages` needs only
   `listings_w` and overwrites all variation images per call, permitting one
   property. Untested. Cosmetic, but it is the difference between a colour
   selector that previews the shirt and one that does not.
5. **Does `shipping_template: false` prevent re-attachment, or was the profile
   merely reused?** Listed again here because it is the only shipping question
   that a single further probe could close, and the shipping stage cannot be
   written without it.
6. **What `overwrite: true` does on `uploadListingImage`.** It is the documented
   answer to the rank collision above and would likely replace the
   upload-then-delete dance with a single call, but it was not exercised.

---

## Phase 3 recon: the fields the listing stages will write

A third round, on **2026-09-10**, against the same shops — read-only except
for PATCHes against the two orphaned drafts round 2 left behind, which are
being deleted by hand anyway. It answers what
[phase-3-etsy.md](phase-3-etsy.md) has to know before its stages are written,
and two of the answers are the inconvenient ones.

### The shop is on Etsy's processing profiles, and the legacy fields are a lie

`getShopReadinessStateDefinitions` returns exactly one:

```json
{"readiness_state_id": 1513785863458, "readiness_state": "made_to_order",
 "min_processing_days": 2, "max_processing_days": 5,
 "processing_days_display_label": "2-5 days"}
```

Every offering on both probe listings already carries it, so Printify's
publish set processing time to the shop's own profile with no help from us.

**`processing_min`/`processing_max` on `updateListing` answer `200` and change
nothing.** Asked for `7`/`9`, read back `2`/`5`; asked again for `2`/`5`, still
`2`/`5`. This is the second silent-`200` in this project after Printify's
`blueprint_id`, and it is the more dangerous of the two because the field is
*documented as writable on `createDraftListing`* — so the obvious reading is
that a PATCH does the same thing, and the obvious reading is wrong.

`readiness_state_id` on `updateListing` also answered `200`, and that proves
nothing either: the shop has exactly one definition and it was already the
value in place. Testing a real change needs a second processing profile made
by hand in Shop Manager, or `shops_w` in the scopes — and `shops_w` costs
every user a second trip through consent (PRD 50).

The practical consequence is smaller than it looks: with one processing
profile in the shop and Printify already applying it to every offering, there
is currently nothing for this tool to change.

### `who_made: someone_else` is refused *without a production partner*

```
PATCH {who_made: someone_else, when_made: made_to_order, is_supply: false}
400 {"error": "There was a problem with /marketplace :
                Oh dear, you cannot sell this item on Etsy."}
```

Measured on the same listing, in the same run:

| `who_made` | `when_made` | `is_supply` | | needs a partner? |
|---|---|---|---|---|
| `someone_else` | `made_to_order` | false | **400** | **yes** — and none exists |
| `someone_else` | `before_2007` | false | `200` | no — vintage resale is allowed |
| `someone_else` | `made_to_order` | **true** | `200` | no — supplies are exempt |
| `collective` | `made_to_order` | false | `200` | no — shop members made it |
| `i_did` | `made_to_order` | false | `200` | no |

**The missing partner is what the 400 is about, not the combination.** Every
row that passed avoids Etsy's production-partner requirement by a different
route, so none of them is a control for the row that failed — which is exactly
how this table was misread once already: as "a made-to-order finished item may
not be declared as made by someone else". Etsy's own listing form disproves
that. It offers *Another company or person* alongside *A finished product* and
*Made To Order*, and marks **"Production partners for this listing"**
required — the same rule, stated in the UI, that the API states as an
unhelpful sentence about the marketplace.

So `someone_else` is the correct declaration for print-on-demand — the shirt
genuinely was made by another company — and `production_partner_ids` is not an
alternative to it but its **precondition**.

**Still unmeasured, and the one that matters:** `someone_else` +
`made_to_order` + a real `production_partner_ids`. It cannot be run until a
partner exists, which is the next section's problem.

### Production partners: none exist, and no endpoint creates one

`getShopProductionPartners` returns `count: 0`. The API is read-only for this
resource — there is no `createShopProductionPartner` — so declaring the
printer is a **Shop Manager step a human has to take once**, before any
listing can name it.

Which also means `production_partner_ids` could not be exercised at all in
this round. What *was* settled is that it reads back: `getListing` and
`getListingsByShop` both return a `production_partners` array (empty today),
so the field is drift-checkable rather than write-only.

### A draft returns the fields the reference says only an active listing does

`readiness_state_id`, `processing_min` and `processing_max` all come back on a
`draft`, against the reference's "returned only when the listing is `active`".
Worth knowing, because a stage that skipped reading them on drafts would be
skipping the only listings this tool ever looks at.

### The colour property is named after the blueprint, not "Color"

From `getListingInventory` on a Printify-managed listing:

| `property_id` | `property_name` | values |
|---|---|---|
| 513 | **`Comfort Colors® Colors`** | `Black`, … |
| 514 | `Clothing sizes` | `S`, `M`, … |

The name is the *blueprint's* option name, so it changes with the garment, and
513/514 are Printify's ids rather than Etsy's standard ones. A media stage
that matched on the name `"Color"`, or hardcoded 513, would work on this shirt
and silently pick the wrong property on the next one.

**Match on the values instead**: the colour property is the one whose values
slugify onto the listing's own `colors`. Printify's colour names arrive
verbatim (`"Black"` → `black`), which is the same convention the mockup
filenames already use (PRD 7a), so the bridge is the slugifier that exists.

### What the shop actually contains today

| | |
|---|---|
| Shop sections | **none** (`count: 0`) — `shop.yaml`'s `shop_section_id: 4455667` names nothing |
| Return policies | one: `1513785862328`, the one Printify created — `shop.yaml`'s `1122334` names nothing |
| Shipping profiles | one: `314944410819`, Printify's US-origin profile with USD numerals as NOK |
| Production partners | none |
| Printify products | none — both probe products were deleted |
| Etsy drafts | both survive: `4572537111`, `4572550919` |

So three of the four things a listing must reference — a section, a shipping
profile worth attaching, a production partner — **do not exist in this shop
yet**, and none of the three can be created through the API within the granted
scopes. They are Shop Manager work, and `setup` should say so by name rather
than resolving a name that will never match.

---

## Phase 3 recon, round C: variation images and image replacement

Same day, against the orphaned round-2 draft (`4572550919`), which still
carries three of our renders and a Printify-authored inventory — everything
these questions need, so **none of this created a listing**.

### The colour join works, end to end, on real data

Run exactly as the media stage will:

| `property_id` | name | slugified values | overlap with `colors: [black, red]` |
|---|---|---|---|
| 513 | `Comfort Colors® Colors` | `black`, `red` | **both** — this is the colour property |
| 514 | `Clothing sizes` | `l`, `m`, `s` | none |

So identifying the colour property by value overlap is not merely defensible,
it is unambiguous: sizes cannot collide with colour slugs, and the slugifier
that names `black.png` maps Etsy's `"Black"` onto `black` with nothing added.

### `updateVariationImages`, measured

| Question | Answer |
|---|---|
| Does it take our triples? | `200`, and `getListingVariationImages` reads them straight back |
| Does the read carry the value **string**? | **Yes** — `{property_id, value_id, value, image_id}`. So the reverse map `value_id → value → slug` comes free with the read; the inventory is needed only to *build* a link, never to compare one |
| Does an empty array clear them? | **Yes**, `200` and `count: 0`. Turning the feature off is a write, not a message |
| May two values share one image? | **Yes**, `200`. The reference's "should not contain any duplicates" means duplicate *(property, value)* pairs — two colours sharing one photograph is legal |
| Scope to read | **none** — `getListingVariationImages` needs only the app key |
| Path to read | **shop-scoped**, `GET /v3/application/shops/{shop}/listings/{id}/variation-images` — unlike every other read this client makes, and the trap below |

The read being shop-scoped is worth its own line because getting it wrong is
invisible. The unscoped `/v3/application/listings/{id}/variation-images`
answers `404` for **every** listing, linked or not — which reads exactly like
"this listing has no swatches yet", and was once written into the client as
that rule. On the correct path an unlinked listing answers `200` with
`count: 0`, the same envelope as every other list read, so there is no special
case to make: a `404` there means the listing is gone.

### `overwrite: true` replaces in place — open question 6, answered

Uploading at rank 1 with `overwrite: true` against three existing images:

```
before: [(1, 8503331196), (2, 8503331086), (3, 8503330926)]
after : [(1, 8503578806), (2, 8503331086), (3, 8503330926)]
```

`201`, count unchanged, ranks 2 and 3 untouched, and rank 1 carries a **new
id**. So it genuinely replaces rather than colliding — the rank-sharing
behaviour recorded in round 2 is what happens *without* the flag.

That is worth an optimisation in the media stage: a mockup whose bytes changed
but whose position did not can be replaced with one call, leaving the order
alone and skipping the `image_ids` PATCH entirely. `image_ids` is still needed
for the first pass (detaching Printify's mockups) and for genuine reorders.

### A replaced image leaves its swatch link dangling, silently

The sharp edge, and the reason the previous section is an optimisation rather
than a free win. With both colours linked to image `8503331196`, that image was
replaced at rank 1. Afterwards:

```
Red    -> image 8503331196   DANGLING -- no longer on the listing
Black  -> image 8503331196   DANGLING -- no longer on the listing
```

`getListingVariationImages` still answers `200` with `count: 2`. **Nothing in
the API says the swatch is broken** — not an error, not a null, not an absence.
Etsy neither repoints the link nor drops it.

So any image replacement invalidates the variation links that referenced it,
and the only way to notice is to compare the linked ids against the ids
actually on the listing. That is precisely what the media stage's live
projection does — a link whose `image_id` matches no current manifest ref
reads as a mismatch and is re-asserted in the same run — so the design holds,
but it is now a measured requirement rather than a precaution.

---

## Phase 3 recon, round D: the production partner, with one that exists

A partner was created in Shop Manager, which made available the control the
earlier round could not run: the same three fields on the same listing, once
without a partner attached and once with.

```
PATCH {who_made: someone_else, when_made: made_to_order, is_supply: false}
400 "Oh dear, you cannot sell this item on Etsy."          <- partner exists in
                                                              the shop, but is
                                                              not on the listing

PATCH {..., production_partner_ids: 5785693}
200   who_made reads back "someone_else"
```

So the rule is exact: **`who_made: someone_else` requires a partner attached to
the *listing*, not merely present in the shop.** The earlier reading — that the
combination itself was illegal — is now disproved rather than merely doubted.

`production_partner_ids` also holds on its own, without `who_made` resent, and
reads back in full:

```json
{"production_partner_id": 5785693,
 "partner_name": "The Print Provider",
 "location": "Miami Gardens, FL"}
```

Name and location both, so the field is drift-checkable against something a
human can read rather than against an id.

### The partner is not named after the print provider

The name matters, because the plan was to derive the partner from
`garment_profile.print_provider` and match on it. Measured:

| | |
|---|---|
| `garment_profile.print_provider` | `Monster Digital` |
| Etsy `partner_name` | **`The Print Provider`** |
| `normalise()` match | **False** |

The location — `Miami Gardens, FL` — *is* Monster Digital's. The identity is
right and the name is deliberately generic, which is what Printify's own
guidance to sellers produces: one anonymous production partner standing in for
whichever of its printers fulfils an order.

**So deriving the partner from the print provider is wrong, and would have
failed on the first shop it ran against.** It is not that the names sometimes
disagree; it is that they describe different things — a printer this tool
chooses per garment, against a fulfilment relationship the shop declares once.
The resolution rule changes accordingly (phase-3-etsy.md, decision 3).
