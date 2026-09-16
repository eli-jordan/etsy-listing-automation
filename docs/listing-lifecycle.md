# Delete and retire

Companion to [prd.md](prd.md) (PRD 61–67). This is the product: what a
listing's end looks like, and why pause and retraction are not the same verb.

Where this disagrees with [printify-etsy-integration.md](printify-etsy-integration.md)
or [phase-3-etsy.md](phase-3-etsy.md) on what Printify `DELETE` does to an
Etsy draft, this file and the PRD are right — those two measured different
sequences and then generalised (see *The cascade* below).

---

## Two operations

A listing that has never been for sale and a listing that has are different
objects. The first can go away. The second has reviews, favourites and search
history — PRD 37 already refused to throw those away to change a garment.
Delete is not that route with a new name.

**Delete** retracts something that was never published on Etsy: local-only,
a Printify product that never minted a listing, or an Etsy `draft`. Files go;
remotes go.

**Retire** pauses something that has been published. Etsy `state=inactive`.
The Printify product stays, so a later reactivate still has somewhere to push
variants. Local files stay.

Once a listing has left `draft` — `active`, `inactive`, `sold_out`,
`expired`, `removed` — delete is `Blocked`. The first line of the refusal is
the consequence (this listing has been published; retracting it would discard
its history); the rest says to retire it. The other direction is also
`Blocked`: `lifecycle: retired` on a never-live listing, because there is
nothing to pause.

Rejected: one cleanup that does not care about state. That is how a
fat-finger retracts a listing with reviews. Rejected: adding `listings_d`.
PRD 50 stands; changing scopes re-consents every user, and this tool still
does not call Etsy's `deleteListing`. Draft retraction is Printify's cascade,
not Etsy's delete.

---

## The field

`listing.yaml` carries an optional `lifecycle:` key. Named that, not
`status`, because the listings table already has a Status column (`draft` /
`deployed` / `live` / `dirty` / …) derived from files and Etsy, and the two
enums must not share a word.

| Value | Meaning |
|---|---|
| omitted | Working listing, including after Un-retire. |
| `retired` | We want it paused. Apply sends `state=inactive`. |
| `deleted` | We want never-live remotes gone. Apply retracts, then wipes files. |
| `renew` | One-shot. Apply sends `state=active`, then omits the key. |

Working listings do not carry a third value (`active`, `draft`). Un-retire is
deleting the key, not writing `active`. `renew` is only a pending mark, like
`deleted` — it is not present once apply has consumed it.

The field is desired state. `plan` never writes `listing.yaml`. Etsy becoming
`inactive` on its own does not adopt `retired` into the file.

Wrong verb is `Blocked`, never rewritten as the right one. Same shape as the
garment-change refusal (PRD 37).

---

## Delete

### Never pushed

No `printify_product_id`, no `etsy_listing_id`. A confirm dialog (no typing
the name), then `listings/{name}/` and `.cache/renders/{name}/` are removed
now. `plan` never sees the listing: `listing_names()` requires
`listing.yaml`, and that is the point. Designs, garment profiles and pricing
plans stay — they are reusable.

Rejected: putting this through `plan`/`apply`. There is nothing to preview
that `rm` does not say.

### Printify product, and/or an Etsy draft

Confirm, write `lifecycle: deleted`. The row stays in the table with a
pending-delete badge so `apply --all` is visible. The mark is the approval;
`apply --all` executing every marked deletion is intended, not a hazard.

Apply is **retract-only**: no render, no product PUT, no copy or media PATCH.
Updating a listing we are about to destroy is wasted writes and a way to
recreate a Printify product `read_live` just said was missing.

Printify `DELETE` on the **still-connected** product — never `unpublish.json`
first. If an Etsy listing id is on record, `GET` it: `404` means the draft
went with the product; still there means apply **fails** and local files
stay. After a confirmed 404 (or no Etsy id), wipe the listing directory and
the render cache.

Wiping local while an Etsy draft survived is how you lose the handle on an
orphan. `listings_d` stays closed; the message names the listing id and says
to remove it in Shop Manager, then re-apply.

### The cascade

Three documents used to disagree because they measured different sequences.

The 2026-09-10 recon ([printify-etsy-integration.md](printify-etsy-integration.md))
called `unpublish.json` then `DELETE`. Unpublish cleared `external`; DELETE
then left the Etsy draft behind, still `state: "draft"`. That measurement
stands. The generalisation — "so deleting a Printify product orphans its Etsy
listing" — does not.

E2E teardown deletes the still-connected product, no unpublish. Asking for
the listing a previous run had minted returns `404` for the listing and for
the product. That is the path this tool takes.

An `active` listing has never been deleted this way. Delete is `Blocked` for
anything that has left `draft`, so the live cascade stays unmeasured on
purpose.

---

## Retire and reactivate

Non-goal 1 still holds for **first** publish: `updateListing` never sends
`state` on a `draft`. `draft` is birth-only; Etsy's update enum is
`active | inactive`. Shop Manager remains the review gate that turns a
deployed draft into a live listing.

What is amended: pause and resume of something a human already published.

**We paused it.** Retire writes `lifecycle: retired`. Until apply, the badge
is pending-retire — Etsy is still `active`, calling it `inactive` would lie.
Apply sends `state=inactive`. Badge becomes `inactive`. Copy and media still
sync; this is not retract-only. The Printify product is left alone.

Un-retire deletes the key. Badge becomes `draft`: the workspace wants it on
sale, Etsy does not. Etsy cannot go back to `draft` — that is birth-only —
so the badge is ours, not Etsy's. Apply sends `state=active`. Plan calls this
out. The only way `apply --all` reactivates a listing we paused is this
explicit Un-retire.

Edits while `retired` stay retired. A typo fix does not put the listing back
on sale. That is why Un-retire is a gesture of its own, not a side-effect of
saving the yaml.

**Etsy paused it.** Expiry, a Shop Manager pause, `removed`. Plan **reads**
Etsy `state`. It does not write the yaml. It does not send `active`. The
plan names the remote state and says apply will not reactivate. Two buttons
in that state only: **Retire** (write `retired`, we agree it is parked) and
**Renew** (write `renew`, apply sends `active` and omits the key). Expired
reactivation can cost $0.20; the plan names `expired` so that is visible.

`sold_out` is inventory, not a pause. It stays `live`. Apply does not treat
it as a remote retirement.

Rejected: auto-writing `lifecycle: retired` when Etsy flips. That makes Etsy
the author of `listing.yaml`, and `plan` is not a writer of listing
documents. Rejected: `apply --all` reactivating a remote pause because the
field was omitted. Omitted means "we did not retire it", not "put it back on
sale." The only sends of `active` are Un-retire (last applied was `retired`,
now omitted) and `renew`.

CLI users have no extra verb. They write `lifecycle: retired` or
`lifecycle: renew` by hand and run `plan` / `apply`, the same as any other
desired-state edit.

---

## Badges

The original four remain, from the same two facts (applied-and-edited? live
on Etsy?). These add:

| Badge | When |
|---|---|
| pending-delete | `lifecycle: deleted`, apply not yet run |
| pending-retire | `lifecycle: retired`, Etsy still `active` |
| inactive | `lifecycle: retired` applied, Etsy `inactive`; or Etsy `inactive`/`removed` and we have not Renewed |
| expired | Etsy `expired` (named, because money) |
| draft | also Un-retire and pending `renew`: workspace wants it on sale, Etsy does not |

`sold_out` stays `live`. Filter pills are derived from the badge set, so a
new badge cannot arrive without a way to filter for it.

---

## Gestures

The listings table, rightmost column. No copy on the editor page — a retract
button next to autosave is how drafts die by accident. No CLI twins.

| Row | Button(s) |
|---|---|
| never-live | **Delete** (rm now if no remotes; else write `lifecycle: deleted`) |
| live, no `lifecycle` | **Retire** |
| pending-retire, or retired applied | **Un-retire** (deletes the key) |
| pending-delete | **Cancel** (deletes the key) |
| Etsy paused us, field omitted | **Retire** \| **Renew** |

Delete confirms with a dialog, no typing the listing name. Retire does not —
Un-retire reverses it before or after apply. Yaml hand-edit still works.

---

## Accidents

`listing.yaml` gone, `state.lock.json` still there: the row still appears,
named from the directory. `Blocked`: restore `listing.yaml`. Never retire,
never delete remotes, never send `state`. A missing file is not consent.
Create of the same name already 409s on the directory, so the lockfile cannot
donate its `etsy_listing_id` to a new listing either.

The whole `listings/{name}/` tree gone, lockfile included: invisible to
`listing_names()` and to this detection. Out of scope. No shop-wide
Printify/Etsy crawl for ids no local file names. Restore from backup.

---

## What this does not do

- Activate a `draft`. First publish stays in Shop Manager.
- Delete a published listing, on Etsy or via Printify.
- Delete designs, garment profiles, or pricing plans with a listing.
- Unpublish a Printify product as a prelude to deleting it.
- Write `listing.yaml` from `plan`.
