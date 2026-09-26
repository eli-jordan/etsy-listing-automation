# Phase 3: Etsy

How the listing half is built: publishing the Printify product, patching the
Etsy listing it creates, and owning the media on it.

Subsidiary to [prd.md](prd.md) and [implementation-plan.md](implementation-plan.md)
in the way [multi-placement-rendering.md](multi-placement-rendering.md) is —
detail those two point at rather than a third authority. Where it disagrees
with the PRD, the PRD wins. Its decisions are recorded there as **PRD 52–59**
and **A24–A28**, and listing videos as **PRD 72**; what this document adds is
the reasoning and the measurements behind them, which a one-row summary in a
decision log cannot carry.

Built on [printify-etsy-integration.md](printify-etsy-integration.md), which
measured the publish path against the real shops, and on Etsy's own API
reference for the write surface — checked field by field rather than
remembered, because two of the answers are not the obvious ones.

---

## The Etsy write surface, checked

| What we write | Call | Scope | Note |
|---|---|---|---|
| title, description, tags, materials | `updateListing` | `listings_w` | PATCH; partial bodies honoured |
| `shop_section_id` | `updateListing` | `listings_w` | A stale id fails the **whole** PATCH (measured) |
| `shipping_profile_id` | `updateListing` | `listings_w` | Resolved from `getShopShippingProfiles` (`shops_r`) by `title` |
| `return_policy_id` | `updateListing` | `listings_w` | Policies have no title; addressed by their terms instead (PRD 59) |
| `who_made`, `when_made`, `is_supply` | `updateListing` | `listings_w` | Etsy requires all three together |
| `production_partner_ids` | `updateListing` | `listings_w` | Partners are read from `getShopProductionPartners` (`shops_r`) and **cannot be created through the API** — a Shop Manager job |
| `should_auto_renew` | `updateListing` | `listings_w` | PRD 11 |
| image upload, at a rank, with `alt_text` | `uploadListingImage` | `listings_w` | Alt text is set **at upload**; there is no image-update endpoint, so changing it means re-uploading that image |
| image order and membership | `updateListing` `image_ids` | `listings_w` | Ordered full-replacement set — see PRD 57 |
| per-colour swatch images | `updateVariationImages` | `listings_w` | Overwrites all of them per call, and permits exactly **one** property |
| video upload, or re-attach by `video_id` | `uploadListingVideo` `?is_multi_video=true` | `listings_w` | No rank and no position parameter; placement follows attach order (decision 9) |
| video removal | `deleteListingVideo` | `listings_w` | Etsy keeps the file, so a deleted video can be re-attached by id |
| — | `updateListingInventory` | `listings_w` | **Never called.** PRD 55 |

Everything here fits inside the scopes already granted — `listings_r
listings_w shops_r` — so nothing in this phase sends anyone back through
consent (PRD 50). `getShopSections` needs no scope at all, which is why a
section can be resolved by name in a workspace whose OAuth consent has lapsed.

### Three measurements that shape the stages

- **The first publish sends Printify's mockups regardless of `{images:
  false}`**, an unknown number of them, arriving over minutes. So the media
  stage cannot count them, cannot wait for them, and must be able to displace
  whatever is there — including something that lands after it looked.
- **`image_ids` reorders and detaches without re-uploading**, which the PRD
  assumed impossible. Sent comma-separated it does exactly the right thing;
  sent as repeated form keys it answers `200` and **destroys the listing's
  images**. Both encodings look identical from the response.
- **Processing time is not a listing field on update.** Etsy's processing
  profile is a *readiness state definition*: no title, and attached per
  offering inside the inventory. It is on `createDraftListing`, which we never
  call, because Printify creates the listing.

---

## Decisions

### 1. Three stages, one PATCH each — A24

`STAGES` becomes `[Render(), PrintifyProduct(), Publish(), EtsyListing(),
EtsyMedia()]`.

Everything except images travels in a single `updateListing` PATCH, so a
single `etsy_listing` stage owns it: copy, tags, materials (from the garment
profile), section, the
`who_made` trio, production partners, shipping profile, return policy and
renewal. The plan's implementation-plan sketch called this stage `etsy_copy`,
which was accurate when copy was all it wrote and would now be a lie in the
stage list.

Rejected: splitting copy from settings into two stages. The argument for it is
that a Phase 4 copy regeneration and a `shop.yaml` edit are then separately
resumable, and that a plan showing a section rename under a stage called
"copy" reads badly. Neither survives contact with the `Change` vocabulary:
paths are already `etsy.title` and `etsy.shop_section`, so the plan output
distinguishes them without a stage boundary doing it, and two PATCHes where
one would do introduces a state — copy written, settings not — that one call
cannot produce.

### 2. A human writes a name; the tool resolves the id — PRD 53, 54; A25

`shop.yaml` gains `etsy.shop_section` and `etsy.shipping_profile`, both
names. `listing.yaml`'s `etsy:` block takes the same two keys as per-listing
overrides. This is PRD 51's rule ("the name is what a human recognises, the id
is what the API needs") applied one level down, and it is what makes the
per-listing override worth having at all: `shop_section_id: 4455667` in forty
listing files is forty numbers nobody can check.

Resolution happens **once per run, in memory** (A25): a small
`EtsyShopCatalog` holding sections, shipping profiles and production partners,
each fetched on first use. Not disk-cached, unlike Printify's catalog — a
stale section id is a `400` that fails the entire PATCH, and the three lists
are small, shop-scoped and cheap. Deleted shipping profiles are filtered
(`is_deleted`), and an unresolvable name is a `Blocked` naming every candidate
it did find, never a fall back to whatever Printify attached.

Neither of the two entities Etsy gives no *name* keeps an id in the config
either: a return policy is addressed by its terms (PRD 59, below), and a
processing profile is not written at all (PRD 55).

The applied document stores **both** the name and the id — the id because it
is what was sent, the name because `shop_section_id: 4455 → 5566` is not a
diff anyone can read. The cost is that renaming a section in Shop Manager and
updating `shop.yaml` to match produces one no-op PATCH; that is the right
trade against an unreadable plan.

### 3. `who_made: someone_else`, and the partner it requires — PRD 52

`shop.yaml`'s `etsy.who_made` default becomes `someone_else`. The shirt was
made by another company, and Etsy's listing form says so in as many words:
*Another company or person*, alongside *A finished product* and *Made To
Order*, with **"Production partners for this listing"** marked required.

The API states the same rule far less helpfully. Sent without a partner:

```
PATCH {who_made: someone_else, when_made: made_to_order, is_supply: false}
400 "There was a problem with /marketplace :
     Oh dear, you cannot sell this item on Etsy."
```

Nothing in that sentence says "partner", which is how it was misread once
already — as the *combination* being illegal, on the strength of three
controls that each passed by dodging the partner requirement rather than by
satisfying it (vintage resale is allowed, supplies are exempt, `collective`
means shop members made it). Recorded because the next reader will meet the
same sentence.

So the two fields are one setting: **`someone_else` is the declaration, and a
non-empty `production_partner_ids` is its precondition.** Neither is optional
in the presence of the other.

And "attached to the listing" is the operative phrase, not "present in the
shop": with a partner sitting in Shop Manager but not named on the listing, the
same PATCH still answers `400`. Sent with `production_partner_ids`, it answers
`200`.

#### Resolving the partner: the shop's, not the printer's

The first version of this decision derived the partner from
`garment_profile.print_provider` and matched on the name. **Measured against the real
shop, that is wrong:**

| | |
|---|---|
| `garment_profile.print_provider` | `Monster Digital` |
| Etsy's `partner_name` | **`The Print Provider`** |

The `location` — `Miami Gardens, FL` — *is* Monster Digital's, so the identity
is right and the name is deliberately generic, which is exactly what Printify's
guidance to its sellers produces: one anonymous partner standing in for
whichever printer fulfils an order. The two fields describe different things —
a printer this tool picks per garment, against a fulfilment relationship the
shop declares once — so a rule that expected them to agree would have failed on
the first shop it met.

The resolution ladder is therefore the one the return policy uses (PRD 59),
for the same reason: when Etsy offers exactly one, do not make anyone name it.

1. **Named explicitly** — `production_partner:` on the listing, else the
   garment profile, else `listing_defaults` — matched against `partner_name` under the
   same normalisation blueprint matching uses (PRD 23).
2. **Omitted, and the shop has exactly one partner** — use it. The common case,
   and this shop's.
3. **Omitted, and the shop has several** — an error listing them by name *and
   location*, since generic names make the location the distinguishing half.

**A listing whose partner does not resolve is `Blocked`, not warned** — under
`who_made: someone_else` that is not a policy nicety but the difference between
a PATCH and a `400`. A shop with **no** partner at all gets a message naming
the Shop Manager step, because the API is read-only for that resource: there is
no `createShopProductionPartner`.

### 4. The tool never writes Etsy inventory — PRD 55

Recorded as an invariant, not a preference. Printify owns the variant matrix
(PRD 41); `updateListingInventory` is a full-replace PUT over exactly that
document, including the disabled zero-price cells Etsy materialises to keep
the grid rectangular. Echoing a Printify-authored matrix back through it to
change one field per offering is the riskiest write this tool could make, and
it is the one write whose failure mode is an unsellable listing rather than a
wrong word.

Processing time was a ladder of three possible levers, and the probe knocked
out the top two:

1. **The shipping profile carries it** — false here. The shop *is* on Etsy's
   processing profiles: one definition (`made_to_order`, 2–5 days), already
   applied to every offering by Printify's own publish.
2. **`updateListing` accepts the fields anyway** — false, and quietly.
   `processing_min`/`processing_max` answer `200` and change nothing: asked
   for 7/9, read back 2/5. The second silent-`200` in this project after
   Printify's `blueprint_id`, and the more dangerous one, because both fields
   *are* documented as writable on `createDraftListing`.
   `readiness_state_id` also answered `200`, and proves nothing — the shop has
   one definition and it was already the value in place. Testing a real change
   needs a second profile made by hand, or `shops_w`, which costs every user a
   second trip through consent (PRD 50).
3. **So: the tool reads processing time and never writes it.** It surfaces
   `readiness_state_id` and `processing_min`/`max` in `plan` and reports drift
   — the same treatment as the shop's draft setting, which it also cannot
   verify (PRD risk 5).

The practical cost is near zero, which is worth saying plainly rather than
leaving as a disappointment: the shop has exactly one processing profile,
Printify applies it to every offering at publish, and there is nothing this
tool would change if it could. If a second profile is ever wanted per listing,
the two routes are `shops_w` in the scopes or Shop Manager — and that is a
decision to take then, with a reason, not now.

### 5. Media: upload what changed, then set `image_ids` — PRD 57, superseding PRD 12

PRD 12 mandates full delete-and-re-upload on the premise that "there is no
update-image endpoint" and therefore no way to reorder. The premise is false,
so the decision built on it goes:

1. Upload each media entry whose bytes are new or changed, at its rank, with
   its alt text.
2. `PATCH updateListing` with `image_ids` set to our ordered id list, **as one
   comma-separated value**.

That second call does three jobs at once. It fixes the order, which
`uploadListingImage`'s `rank` does not — a rank collision produces two images
sharing a rank rather than pushing one down. It detaches everything not in the
list, which is how Printify's mockups leave without a delete-loop that Etsy
would refuse to finish ("Listings must have at least 1 image"). And it is one
request rather than ten whenever a single mockup re-renders.

Detachment is recoverable — `uploadListingImage` takes a `listing_image_id`
for exactly that — so nothing is destroyed by an ordering mistake. The
encoding is the sharp edge, and it gets a contract test of its own rather than
a comment: repeated keys answer `200` and leave one image standing.

Retained from PRD 12: media sync is still driven by a per-file hash, still
full-replacement in meaning, and the manifest is still explicit and ordered.
What changes is the mechanism, and that ids now survive a reorder — which is
what makes decision 6 practical.

**`overwrite: true` earns a second path, measured.** Uploading at an occupied
rank with the flag *replaces* — count unchanged, neighbouring ranks untouched,
a new id at that rank — where without it two images end up sharing a rank. So
the common case, a mockup whose bytes changed but whose position did not, is
one call: replace in place, no `image_ids` PATCH at all. The two-step above
stays for the first pass, where Printify's mockups have to be detached, and
for genuine reorders.

The flag does not make the reorder call optional for *decision 6*, though: the
replacement mints a new image id, and every swatch link pointing at the old one
silently dangles. That is measured, and it is why the variation links are
re-asserted whenever any id changed.

### 6. Per-colour variation images — PRD 56

`updateVariationImages` binds an `image_id` to a `(property_id, value_id)`
pair, so Etsy's colour selector shows the shirt in that colour instead of a
plain swatch. It needs only `listings_w`, and `getListingVariationImages`
reads the links back with no scope at all — so this is drift-checkable like
everything else.

The whole of the feature is one join, and it is worth writing out because none
of its three links is obvious.

#### The join, with the values the probe actually returned

```
listing.yaml                 Etsy inventory                    Etsy images
─────────────────────────    ────────────────────────────      ───────────────
colors: [black, ...]         property_id 513                   listing_image_id
                             "Comfort Colors® Colors"            6234
media:
  - template: flat-lay-01      value_id 50135267836
    colour: black             value "Black"
```

**Step 1 — find the colour property, by its values.** Not by its name: it is
called `"Comfort Colors® Colors"` here, the *blueprint's* own option name,
which changes with every garment. Not by its id either: `513` is Printify's,
against `514` for `"Clothing sizes"`. The colour property is **the one whose
values slugify onto this listing's `colors`** — sizes slugify to `s`, `m`, `l`
and can never collide, so the overlap is decisive rather than merely
suggestive. No overlap at all, or two properties overlapping equally, and the
feature reports and does nothing; it never guesses.

**Step 2 — Etsy's value string → our colour slug.** `slugify("Black")` is
`black`, through `config/slug.py` and its exceptions file. This is the same
convention that already names `black.png` in a `colour-matrix` template (PRD
7a), which is the quiet part worth noticing: one slug spans all three systems
— Printify's variant colour, the mockup filename, and Etsy's variation value —
because Printify's colour names reach Etsy verbatim. A colour that needs an
entry in `exceptions.yaml` for its filename needs no second entry here.

**Step 3 — colour slug → image id.** The media stage keys
`lock.remote.etsy_image_ids` by manifest ref (`"flat-lay-01:black"`), so the
colour resolves to a ref, and the ref to the id Etsy minted at upload.

**Step 4 — one call.** `updateVariationImages` overwrites every link on the
listing and permits exactly one property, so the complete set of triples goes
in a single POST. There is no partial update to make, which conveniently means
there is no partial state to reason about.

#### Which media entry supplies the swatch

`variation_images` **names the template** whose renders are the swatches:

```yaml
etsy:
  variation_images: flat-lay-01
```

Absent means off, so the feature is opt-in without a boolean, and the entry
that supplies each colour is stated rather than inferred. That matters because
a listing may legitimately carry two `colour-matrix` templates and a shared
sizing chart, and "the first entry naming that colour" is a rule you have to
know to predict — it makes media *order* silently decide swatch content.

Rejected: `variation_images: true` with first-match-wins, which is one
character shorter and one rule heavier; and an explicit `{colour: media ref}`
map, which is the only shape that handles swatches drawn from two templates at
once — a listing nobody has wanted yet, and a map that would have to be
rewritten every time `colors` changed.

A named template that is not `colour-matrix` kind is a config error: `multiple`
and `single` templates have exactly one output and no colour, so they have
nothing to bind.

#### Deferred: swatches can only come from a `colour-matrix` template

That restriction is accepted for now and worth stating precisely, because the
obvious summary of it is wrong. The blocker is not the template *kind*. It is
that **`colour` on a media entry is a render-addressing key — "which of this
template's per-colour outputs" — and a swatch needs a different fact: "which
colour this photograph depicts."** For a `colour-matrix` entry the two
coincide, which is exactly why the feature works there and only there.

So the three things one might plausibly want later all need the same missing
annotation, not a change to this join:

- a `single`-kind lifestyle shot photographed in one colour, referenced once
  per colour;
- a shared asset under `common-media/` standing in for a colour;
- swatches drawn from two templates at once.

The tempting move when that day comes is to let `single` entries carry
`colour:` too. **That would overload one key with two meanings** — an
addressing key that selects an output, and a claim about image content — and
the render stage would then have to ignore a field the media stage obeys. A
separate annotation (`depicts: black`, say) keeps each key answering one
question, and `colour-matrix` entries would derive theirs rather than
repeating it.

The config shape leaves room for it: `variation_images` is a scalar template
name today, and a scalar can grow into a mapping without invalidating a file
anyone has already written.

#### What happens when it cannot be done

Every one of these reports and continues, on PRD 46's principle — a swatch is
a decoration, and refusing a listing over one would be the tool inventing a
requirement Etsy does not have:

Two colours may share one image, measured — Etsy's "no duplicates" rule is
about duplicate `(property, value)` pairs, not repeated `image_id`s — so a
listing whose black and navy were shot once is legal.

| Case | Result |
|---|---|
| A colour with no media entry in the named template | that colour gets no swatch |
| A colour Printify never made a variant for (PRD 46) | absent from the inventory, so absent here |
| No property's values overlap `colors` | the whole feature is skipped, loudly |
| Two properties overlap equally | skipped, loudly — never a coin toss |
| The named template is not in `media` at all | a config error at plan time, not a skip |

#### Idempotency

The applied document stores `{colour: manifest ref}` — stable, hashable, no
remote ids. `read_live` reads `getListingVariationImages` and projects it back
into the same space by reversing the two maps: `value_id → value → slug`, and
`image_id → ref` through `lock.remote.etsy_image_ids`.

That projection is what makes a re-render self-healing. When a mockup changes
and the media stage uploads a new image, the old id is detached and the live
link now points at an id no ref claims — which reads as a mismatch, and the
links are re-asserted in the same run that replaced the image. No special case,
no "always re-run", just the same three-way comparison as everything else.

**And it is load-bearing, not a precaution.** Measured: replacing an image
leaves every variation link that referenced it pointing at an id no longer on
the listing, and `getListingVariationImages` reports that state as `200` with
a full `count` — no error, no null, no absence. A dangling swatch is invisible
from the API, so comparing linked ids against the ids actually on the listing
is the only thing that can notice one.

The live read is also cheaper than it looks: `getListingVariationImages`
returns the value **string** alongside each id, so `value_id → value → slug`
comes free with it. The inventory read is needed only to *build* a link for a
colour not yet bound — never to compare one.

**Owned by the media stage**, not a stage of its own: the links are a function
of the image ids that stage mints, and a separate stage would be one that has
to run whenever its neighbour does.

### 7. Shipping: risk 13 closes by design, not by a flag — PRD 58

`shipping_template: false` does **not** stop Printify creating a US-origin
profile carrying USD numerals as NOK and attaching it — measured, and roughly
a 90% shortfall per shipment. The findings document leaves two questions open:
whether the flag at least prevents *re-attachment*, and whether an
`updateListing`-assigned profile survives a later republish.

Under this design, neither blocks the phase. `etsy_listing.read_live()` reads
the listing's actual `shipping_profile_id`; if Printify has attached its own,
that is **drift**, `plan` says so, and `apply` re-asserts ours. The three-way
comparison the whole tool is built on is exactly the mechanism this needs, so
there is no "always re-write this field" special case and no dependence on a
flag Printify honours only sometimes.

Free versus paid shipping (the PRD's requirement that both work) therefore
becomes a choice of *which named profile*, made in `shop.yaml` or per listing
— not a code path, not a mode, and not something the tool computes.

The flag is still sent `false`, because a hint that sometimes works is better
than no hint.

### 8. A stage may read what an earlier stage produced *this run* — A26

Three places in this phase need something an earlier stage in the same `apply`
is about to make:

| Needs | Produced by | Available at plan time? |
|---|---|---|
| the Etsy listing id | `publish` | No — on a first run it does not exist |
| the rendered PNG's bytes | `render` | No — the cache may be empty |
| the uploaded image ids | `etsy_media` itself | Within one stage; fine |

`execute` currently hands every stage the **previous** lockfile, deliberately,
so that stage order cannot change what a stage sees. That rule is right for
`applied` — a document from the last run — and wrong for `remote`, which is
ids an API just handed back. A first `apply` that creates a Printify product,
publishes it, and then cannot find the listing id it just minted is not a
safer design; it is a design that needs `apply` run twice.

So: `execute` threads the **accumulating `remote` block** through the run
while continuing to hand each stage the previous run's `applied`. Narrow, and
it says what it means — an id minted this run is the same id it will be next
run.

The rendered bytes take the other answer, the one the PRD already uses for
copy: a file that does not exist yet is **pending**, not zero-length. The
media stage's desired document carries a hash where the file exists and a
pending marker where it does not, `plan` renders "4 images (pending render)",
and `apply` hashes at upload time and records what it actually sent.

### 9. Videos are placed by attach order — PRD 72

Etsy's video surface is two calls. `uploadListingVideo` takes a file or the
`video_id` of one the shop already has, and `deleteListingVideo` removes one.
There is no rank, no position field on the video, the listing or any other
schema in the OpenAPI document, and no ordering call. Etsy's own tutorial
describes a fixed layout, and a developer who asked in
[open-api#1714](https://github.com/etsy/open-api/discussions/1714) how to
place a video among images got no answer. Everything below was measured on
2026-09-25, against the `duke-java-developer` draft and a throwaway draft
built for it. That draft carried images labelled IMG 1–5 and videos labelled
VIDEO A and B, and its gallery was read **by eye in Shop Manager**, because
nothing in the API reports where a video sits.

#### What the API does

| Probe | Result |
|---|---|
| Upload an 8 MB, 1440×1440 MP4 | `201`, `active` immediately. There is no processing state to poll. Etsy transcodes it to 1280 px and strips the audio |
| Upload a third with `is_multi_video=true` | `409` "maximum number of videos", after the bytes had been sent |
| Upload a third *without* the flag | The new one goes active and the others turn `inactive` **but stay in every list**. Re-attaching one by id reactivates it |
| `PATCH image_ids`, and a Printify republish with the publish stage's flags | Videos untouched. The listing stayed a draft |
| A 3 s and a 20 s clip | Both accepted. The documented 3–15 s is not enforced here |
| The test suite's 3.2 s, 512×512 H.264 fixtures, 2–4 KB each, one carrying audio (the e2e layer, [2026-09-25](https://github.com/eli-jordan/etsy-listing-automation/actions/runs/36159006791)) | Both `active` straight after upload. Deleting the second, cutting `image_ids` to three images, re-attaching it by id and restoring all four kept its `video_id` and left it `active`. Nothing about the file's size or bitrate was refused |
| A PNG renamed `.mp4` | A bare `500` |
| A video id inside `image_ids` | `400` "That ListingImage does not exist". Nothing changed |
| An undocumented `rank`, as form field and query | Silently ignored |
| An 11th association within 24 h, fresh upload or re-attach | `400` "maximum number of videos", on a listing holding none. A genuinely full listing answers `409` with the same text. Per listing, not per shop: a second draft accepted uploads at the same moment |

The list endpoints return videos newest-upload first. That is an ordering of
the *response*, and it says nothing about the gallery.

#### Where a video appears

| Step | Gallery, as Shop Manager showed it |
|---|---|
| IMG 1–4, then VIDEO A, then VIDEO B, then IMG 5 | 1, A, 2, 3, 4, **B**, 5 |
| `image_ids` reversed to 5…1 | 5, A, 4, 3, 2, **B**, 1 |
| B deleted, `image_ids` cut to IMG 5 alone, B re-attached, all five restored | 5, A, **B**, 4, 3, 2, 1 |
| A deleted | 5, **B**, 4, 3, 2, 1 |
| A re-attached | 5, B, 4, 3, 2, 1, **A** |

Three rules come out of that, and the tutorial states only the first half of
the first:

- **The video attached longest is featured**, pinned at position 2 behind
  the thumbnail. Delete it and the other is promoted.
- **Any other video is anchored "after *n* images"**, *n* being the number
  of images on the listing when it was attached. Reordering the images
  leaves it at that count. Adding images after it does too.
- **Re-attaching counts as attaching.** A video brought back by id is
  anchored afresh, so position can change without re-sending a byte.

#### How the stage places them

`media:` is the gallery (PRD 72), so the desired layout reads straight off it:
the featured video is the one at position 2, and the second video's anchor is
the number of images before it. `etsy_videos` runs after `etsy_media`, once
the images are uploaded and ordered, and brings the listing to that layout:

1. Delete every video on the listing that is not one of ours, `active` or
   `inactive`. This happens first because a stranger may be holding one of
   the two slots. Foreign videos are swept when the stage runs; they never
   make it run, which is how `image_ids` already treats foreign images.
2. If the featured video differs from the one last applied, delete **both**
   of ours, because a survivor would be promoted to featured. Then attach the
   featured one: uploaded if its bytes are new, re-attached by id if Etsy
   already has it. The second video then goes through step 3 regardless.
3. If the second video, or its anchor, differs from what was last applied,
   delete it. Then cut `image_ids` to the first *n* image ids, attach it, and
   `PATCH` the full list back.
4. Re-assert the swatch links through the helper `etsy_media` uses, whenever
   step 3 ran.

Drift is handled as for images: one of ours missing or `inactive` on the
listing is reported by `plan`, and `apply` uploads it again.

#### What it costs

- **Detaching an image deletes its swatch link, permanently.** Measured on
  duke: after cutting `image_ids` to one image and restoring all five, one of
  the five links survived. Restoring the images restores nothing else. This
  is why step 4 exists, and why it cannot be skipped because "the image ids
  did not change". The link-setting helper therefore has two callers and one
  implementation.
- **For about a second the listing shows only the images before the
  video.** On a live listing, a buyer could see that. Accepted: positioning is
  the point of the feature, and the window is one round trip.
- **A crash between the cut and the restore leaves the listing short.** It
  heals on the next run without new code, because `etsy_media` already
  reports "one of our images is gone" as drift, re-asserts `image_ids`, and
  re-sets the swatches.
- **Ten associations per listing per day**, re-attaches included. Etsy's
  refusal says "maximum number of videos". The client re-words it into what
  it is, the daily budget, rather than the tool predicting it.
- **A position changed by hand in Shop Manager is invisible.** The API cannot
  report positions, so `plan` has nothing to compare against. The stage
  re-asserts only when its own desired layout changes, and says so.

Two things worth knowing about Shop Manager. Saving the listing editor
replaced the videos on the listing, which is how two API uploads disappeared
during the probe. And before multi-video was switched on, its gallery showed
only the latest video
([open-api#1670](https://github.com/etsy/open-api/discussions/1670)).

#### Local checks

The help page
([How to Add Listing Videos](https://help.etsy.com/hc/en-us/articles/360053206073-How-to-Add-Listing-Videos))
is the specification, and anything outside it is blocked before an upload is
spent on it:
- `.mp4` or `.mov`: of Etsy's seven listed types, the two a browser previews
- at most 100 MB
- 3–15 seconds
- a shorter side of at least 500 px
- a file PyAV can open that contains a video stream

The last check is there because a non-video is otherwise a bare `500`. The
page's "aspect ratio should be 2:1 or 1:2" is not enforced: a 1:1 video
uploaded every time. That Etsy strips audio is stated as a note on the video,
not as a warning.

---

## Config, after this phase

```yaml
# shop.yaml
etsy:
  shop_name: NaturallyInkedStudio
  shop_id: 67961328
  currency: NOK

  # Every field a listing inherits, and nothing that identifies the shop.
  # Anything here may be overridden in a listing's own `etsy:` block.
  listing_defaults:
    who_made: someone_else             # requires a production partner (PRD 52)
    when_made: made_to_order
    is_supply: false
    renewal: manual
    shipping_profile: NOK standard tee # by name (PRD 54)
    return_policy:                     # by its terms, not its id (PRD 59)
      accepts_returns: true
      accepts_exchanges: true
      within_days: 30
    production_partner: The Print Provider  # optional -- omit when the shop
                                            # has exactly one (PRD 52)
```

The `listing_defaults` block is what a listing inherits; everything outside it
identifies or configures the shop. That line is worth drawing because the two
have different failure modes: a wrong `shop_id` means nothing works, while a
wrong default means every listing is quietly slightly wrong.

**No section and no swatch setting live here.** Which part of the shop a
listing belongs in, and which of its mockups become colour swatches, are facts
about that listing — a shop-wide default for either would be a value that is
right for the first listing and wrong from the second onwards.

```yaml
# listings/take-a-hike/listing.yaml   (the etsy: block only)
etsy:
  title: ""
  tags: []
  description:
    lead: ""
    ref: common-copy/comfort-colors.md
  renewal: manual                      # overrides shop.yaml
  section: Retro Tees                  # optional; listing-only, by name
  shipping_profile: NOK heavy tee      # optional; overrides shop.yaml
  variation_images: flat-lay-01        # optional; see below
```

`setup` changes to match: it writes the `listing_defaults` block, and stops
resolving a shop section altogether — `etsy.shop_section_id` leaves `shop.yaml`
(an amendment to PRD 43/49, which had `setup` writing four ids; it now writes
two, plus a return policy it names by terms).

### Referring to a return policy without an id — PRD 59

Etsy gives a return policy no title: the resource is `{return_policy_id,
shop_id, accepts_returns, accepts_exchanges, return_deadline}` and nothing
else. But the three terms **are** its identity — `return_deadline` is
constrained to `[7, 14, 21, 30, 45, 60, 90]`, and Etsy ships a
`consolidateShopReturnPolicies` endpoint precisely because duplicate term-sets
are something it merges rather than keeps. So a policy is addressable by what
it says, and resolution is an exact match on the three fields against
`getShopReturnPolicies`.

That leaves an id in the file only for someone who wants one, and it makes the
plan output legible: `return_policy: returns and exchanges within 30 days`
renders straight from the fields — the `describe()` that `clients/etsy/models`
already has, written for the `setup` picker for exactly this reason.

**Omitting it is the zero-config path**: a shop with exactly one return policy
needs no reference at all, and this shop has exactly one. Two or more, and an
omitted `return_policy` is an error listing them by their terms, because
guessing which is meant is not something a tool should do with a refund
policy.

---

## The stages

### `publish`

| | |
|---|---|
| `desired` | the sync flags, plus the enabled variant matrix `{variant_id: price}` it intends Etsy to receive |
| `read_live` | the product's `external` block and its enabled variants (including `cost`); `None` without a request when there is no product id |
| `plan` | publish when `applied` is `None` or `external` is absent; republish when the matrix differs; drift when `applied` says published and `external` is gone |
| `apply` | `POST publish.json`, then poll `get_product` — 2s to 60s backoff against a ~10 minute ceiling — until `is_locked` is false and `external.id` is present |
| `remote` | `etsy_listing_id`, `etsy_listing_handle`, `printify_publish_locked` |

The desired matrix is rebuilt through the same pure `product_document` builder
the product stage uses, rather than read out of that stage's lockfile subtree.
It costs one extra resolution pass per listing per run (the catalog is
disk-cached; the rest is arithmetic) and buys stage independence: a stage
reading a neighbour's applied document is a stage that breaks when the
neighbour's document changes shape.

**PRD 40's price-above-cost assertion lands here**, as the PRD's amendment
says it must: `variants[].cost` exists only on a product that already exists,
and `read_live` has one in hand. Printify refuses to publish below cost, so
the check turns a remote `400` into a plan-time refusal naming the size.

It is spoken as `Verdict.refused(...)`, not as a verdict that will not run
carrying a `reason`. A refusal this stage can only reach *after* `read_live`
is still a refusal, and has to render as one — `plan` prints a `reason` only
for stages that run, so the first shape of this check was invisible: the
listing was skipped under a plan reading "No changes."

On a poll timeout the product is recorded locked and the listing is abandoned
with a message naming `unlock` — which is also built in this phase, and whose
one job (`publishing_failed.json` clearing a genuine lock) remains
**unobserved**: the lock is real, no publish in the probe ever got stuck, and
one cannot be manufactured on demand.

### `etsy_listing`

| | |
|---|---|
| `desired` | title, description, tags, materials, section (name + id), shipping profile (name + id), return policy (terms + id), `who_made`/`when_made`/`is_supply`, production partner ids (+ names), `should_auto_renew` |
| `read_live` | `getListing` — `None` without a request when there is no listing id |
| `plan` | field-by-field against `applied`; anything `live` disagrees with `applied` is drift, which includes Printify re-attaching its own shipping profile |
| `apply` | one `PATCH updateListing` carrying only what changed |

Blocked when: the workspace has no `etsy.shop_id`; title or the final composed
description is not concrete and non-empty (PRD 44's gate, reused); a section,
shipping profile or production partner name does not resolve; `who_made` is
`someone_else` and no partner resolved, which Etsy refuses outright.

Read back with `GET /v3/application/listings/{id}` — the *unscoped* single
listing read. The shop-scoped path exists for `PATCH` and `DELETE` and
**404s on `GET`**, which cost the probe a false "our copy was overwritten"
verdict; a comment says so at the call site.

`production_partner_ids` may turn out not to be readable back (Etsy's schema
carries `production_partners` but does not list it among `getListing`'s
`includes` values). If it is not, it becomes a **write-only field**: compared
desired-against-applied, excluded from drift, and documented as such rather
than silently reporting no drift because it read `None`.

`state` is never sent. Etsy's update enum is `active | inactive`, a draft
cannot be re-drafted, and the one thing this tool must never do by accident is
activate a listing (PRD non-goal 1).

### `etsy_media`

| | |
|---|---|
| `desired` | the ordered manifest — `(ref, content hash \| pending, alt text)` — plus the variation-image links when enabled |
| `read_live` | `getListing?includes=Images` for the current images and their ids; `getListingInventory` when variation images are on |
| `plan` | per-entry: upload (new/changed bytes), reorder (same ids, different order), detach (present on Etsy, absent from the manifest) |
| `apply` | upload the changed → `PATCH image_ids` (comma-separated) → `updateVariationImages` when enabled |
| `remote` | `etsy_image_ids`, keyed by manifest ref so a reorder does not churn them |

`GET .../listings/{listing}/images` is never used: it returns `404` for
**every** id, valid or invented, so a 404 there says nothing. The listing read
with `includes=Images` is the only working route, and it is the one every
count in the findings document came from.

The image count gate (≤20, PRD) stays a plan-time validation over the
manifest, not a check against what Etsy currently holds — Printify's stragglers
would otherwise make a valid listing look over the cap. It counts images only;
videos are PRD 72's, and have a cap of their own.

### `etsy_videos`

Its own stage, so its lockfile entry, its progress events and its failure are
its own. A video upload is the slow, large, fragile part of a media sync, and
a failure there must not cost the images a re-upload. It carries a display
group of `etsy_media`, so the CLI plan, the API and the editor show it under
the one "Etsy media" heading.

| | |
|---|---|
| `desired` | the videos in `media:` in gallery order — `(ref, content hash, anchor)` — where the anchor is the number of images before the second video |
| `read_live` | `getListing?includes=Videos`, filtered to ours by `etsy_video_ids`, with each one's `video_state`; foreign videos counted separately |
| `plan` | work when the featured ref, the second ref, either hash or the anchor differs from the last applied; drift when one of ours is missing or `inactive` |
| `apply` | sweep foreign → attach featured → cut `image_ids`, attach second, restore → re-assert swatches (decision 9) |
| `remote` | `etsy_video_ids`, keyed by media ref |

---

## The lockfile after Phase 3

```json
{
  "applied": {
    "publish": { "sync_flags": {"variants": true, "images": false, "...": false},
                 "variants": {"73196": 29900} },
    "etsy_listing": { "title": "...", "description": "...", "tags": [],
                      "materials": ["cotton"],
                      "shop_section": "Retro Tees", "shop_section_id": 4455667,
                      "shipping_profile": "NOK standard tee",
                      "shipping_profile_id": 314944410819,
                      "return_policy": {"accepts_returns": true,
                                        "accepts_exchanges": true,
                                        "within_days": 30},
                      "return_policy_id": 1513785862328,
                      "who_made": "someone_else", "when_made": "made_to_order",
                      "is_supply": false,
                      "production_partners": ["Monster Digital"],
                      "production_partner_ids": [12345],
                      "should_auto_renew": false },
    "etsy_media": { "manifest": [{"ref": "flat-lay-01:black", "hash": "sha256:..."}],
                    "variation_images": {"black": "flat-lay-01:black"} },
    "etsy_videos": { "videos": [{"ref": "common-media/size-guide.mp4", "hash": "sha256:..."},
                                {"ref": "./close-up.mp4", "hash": "sha256:...",
                                 "after_images": 2}] }
  },
  "remote": { "etsy_listing_id": 4572550919,
              "etsy_listing_handle": "https://www.etsy.com/listing/...",
              "etsy_image_ids": {"flat-lay-01:black": 6234},
              "etsy_video_ids": {"common-media/size-guide.mp4": 844252820,
                                 "./close-up.mp4": 844278141},
              "etsy_listing_state": "draft",
              "printify_publish_locked": false }
}
```

Names sit in `applied` beside their ids for decision 2's reason. Ids handed
back by Etsy sit in `remote`, excluded from every hash, under this phase's
documented `etsy_*` prefix (A20).

---

## Clients

```
clients/etsy/
  listings.py   EtsyListingClient + HttpEtsyListingClient   (new)
  shopcatalog.py  per-run name resolution: sections, shipping profiles,
                  production partners                        (new)
  models.py     + Listing, ListingImage, Inventory, ShippingProfile,
                  ProductionPartner                          (extended)
  fakes.py      + an in-memory listing client                (extended)
  shops.py      unchanged — `setup`'s four unscoped reads
```

Two protocols over one transport, exactly as Printify's split works and for
the same reason (A22): a caller holding `EtsyShopClient` cannot reach
`updateListing`, because the method is not on its type.

`RunContext` gains `etsy: EtsyListingClient | None` and `require_etsy()`,
mirroring `require_printify()`. Optional for the same reason: `plan` in a
Phase 1 workspace must not demand a token.

One defect to fix while here, recorded in the findings: **a missing Etsy scope
is a `401`, not a `403`**, and the transport currently branches on the status
alone and reports "check your keystring" — pointing at a credential that is
fine. Phase 3 is the first phase where a scope error is plausible (`shops_r`
for shipping profiles), so the auth error carries the server's own text from
here on.

---

## Probes

Recon first, as Phase 2 did. Run on 2026-09-10 against the connected shop;
what came back is written up in
[printify-etsy-integration.md](printify-etsy-integration.md) under *Phase 3
recon*.

| # | Question | Answer |
|---|---|---|
| 1 | Is this shop on processing profiles? | **Yes** — one definition, `made_to_order`, 2–5 days, already on every offering |
| 2 | Does `updateListing` accept the processing fields? | **No.** `processing_min`/`max` are a silent `200`; `readiness_state_id` untestable with one profile |
| 3 | Can `production_partner_ids` be read back? | **Yes** — `production_partners` is on `getListing`. But the shop has **no partners**, and no API creates one |
| 3b | Is `who_made: someone_else` legal for a made-to-order finished item? | **Yes, with a production partner** — the `400` is the missing partner. The passing case is owed a measurement once one exists |
| 4 | What is the colour property? | `513`, named `"Comfort Colors® Colors"` — the blueprint's name. Match on values, not names |
| 5 | Does `shipping_template: false` prevent re-attachment? | **Blocked** — needs a second shipping profile to exist |
| 6 | Does an assigned shipping profile survive a republish? | **Blocked** — same |
| 7 | What does `overwrite: true` do on `uploadListingImage`? | **Replaces in place.** Count and neighbouring ranks unchanged, a new id at that rank |
| 8 | Does an empty `variation_images` array clear the links? | **Yes.** Turning the feature off is a write, not a message |
| 9 | Does `someone_else` + `made_to_order` pass with a real partner? | **Yes** — `200` with `production_partner_ids`, `400` without, partner in the shop either way. And the partner is **not** named after the print provider |

Everything reachable is answered. **Only the two shipping questions remain,
and they need a second shipping profile to exist.** The shop has exactly one,
the US-origin profile Printify made, and with only that one a republish leaving
`shipping_profile_id` unchanged is equally consistent with "the flag worked"
and "Printify reused its own" — precisely the ambiguity round 2 recorded.
Creating one needs `shops_w`, outside `SCOPES` (PRD 50), so it is a Shop
Manager step. Publishing before then would cost a permanent Etsy draft to
reproduce an answer we already have.

They unblock the moment an NOK profile exists, and then ride along with one
publish — the same run that exercises the media stage end to end.

### Video recon, 2026-09-25

Written up in decision 9. It ran against `duke-java-developer`'s draft
(4572960161) until that listing's daily video budget ran out, which is how the
budget was found. It then moved to a throwaway draft created for the purpose
("ZZ video probe - delete me", 4582417670), which needs deleting in Shop
Manager because `listings_d` is outside `SCOPES`. One side effect, repaired
the same day: the swatch probe on duke deleted four of its five links, and
they were re-set from the recorded triples.

### Shop Manager work this uncovered

Three of the four things a listing must reference do not exist in this shop
yet, and none can be created within the granted scopes:

| Missing | Consequence |
|---|---|
| ~~Any production partner~~ | **Done** — `The Print Provider` (5785693), and being the shop's only one it needs no reference in config |
| Any shop section | any listing naming a `section:` blocks; `shop.yaml`'s `shop_section_id` is dropped either way |
| An NOK shipping profile | The only profile is Printify's US-origin one with USD numerals — risk 13's actual loss |

`shop.yaml` also carries `return_policy_id: 1122334`, which does not exist;
the real one is `1513785862328`. `setup` should notice all four and name the
Shop Manager step, rather than resolving names that cannot match.

---

## Build order

Each step is a commit, and each leaves the suite green.

| # | Step | Notes |
|---|---|---|
| 1 | ~~Probe + findings update~~ | **Done** — 1–4 answered; 5–7 ride along with step 10 |
| 2 | ~~Docs: PRD 52–59, A24–A28, risk 13 closed~~ | **Done** — folded into the two authority documents in their own commit |
| 3 | `clients/etsy/listings.py` + models + fakes | Protocol, HTTP impl, in-memory fake |
| 4 | Contract cassettes | Payload shape, both `image_ids` encodings, error decoding, the 401-scope text |
| 5 | `shopcatalog.py` — names to ids | Sections, shipping profiles, partners; unresolved names name the candidates |
| 6 | Config + `setup` | `shop.yaml`/`listing.yaml` fields, `who_made` default, validation gates |
| 7 | Engine: the `remote` handoff (A26) + `RunContext.etsy` | Behaviour test: one `apply` from nothing to a patched draft |
| 8 | `publish` stage + `unlock` | Polling, the lock, PRD 40's cost assertion |
| 9 | `etsy_listing` stage | The single PATCH, drift, the blocked reasons |
| 10 | `etsy_media` stage | Upload → `image_ids` → variation images |
| 11 | CLI: LIVE banner, drift rendering, `unlock` | `Plan.is_live` already exists on the type |
| 12 | e2e + the PRD's live-edit check | Against the throwaway shop |

---

## Testing

| Layer | What Phase 3 adds |
|---|---|
| Unit | name normalisation and resolution failure messages; the manifest diff (upload/reorder/detach) as a pure function; the variation-image matcher |
| Behaviour | first apply from nothing to a patched draft; second apply a no-op; a re-attached Printify shipping profile reported as drift and repaired; publish poll timeout leaving a recoverable lock; a colour with no media entry skipped, not fatal |
| Contract | `image_ids` **both** encodings — the comma one preserving three images, the repeated-key one reducing them to one, which is the whole reason this is a test and not a comment; the multipart upload; a 401 carrying a scope name |
| E2E | the full cycle against the throwaway shop: publish, patch, re-render one mockup, re-apply, confirm order and swatches; then the live-edit check |

The behaviour layer needs a fake listing client that reproduces two measured
behaviours or it will bless a broken stage: `image_ids` as a full-replacement
set that detaches omissions, and a refusal to delete the last remaining image.

`etsy_videos` adds four more to that fake, each measured in decision 9:
- a gallery that promotes the survivor when the featured video goes
- a second video anchored by the image count at attach time
- swatch links deleted when their image is detached
- the eleventh association in a day refused with a `400`

The fake is also the only place the gallery *can* be asserted, since the real
API never reports it.

---

## What stays open

1. **Does republishing `{variants: true}` disturb an *active* listing?** PRD
   risk 3. Proven on a draft; an active listing means a live listing in a real
   shop. The one item that may be worth simply accepting.
2. **Does `publishing_failed.json` clear a genuine publish lock?** `unlock`
   ships unverified, as it has since Phase 2.
3. **Etsy's cleanup asymmetry — settled, not open.** Unpublish-then-DELETE
   orphans the Etsy draft (this recon). DELETE of a still-connected product
   takes the draft with it (e2e teardown, `404`). The tool takes the second
   path and never unpublishes first. `listings_d` stays outside `SCOPES`; live
   listings are never deleted this way. PRD 63,
   [listing-lifecycle.md](listing-lifecycle.md).
4. **Where does a second video go when the images before it drop below its
   anchor?** Untested. It only arises for a moment: `etsy_media` removes the
   images, and `etsy_videos`, which runs next, re-anchors to the new count.
   Only a hand edit in Shop Manager could leave it standing, and that is
   invisible anyway.
5. **Does the layout survive Etsy's 2026-10-21 cut-over?** Etsy says only
   that the legacy replace mode goes away, and this tool never uses it. Since
   `plan` cannot see positions, the check is decision 9's labelled probe, run
   once more after that date and read by eye.
