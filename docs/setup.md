# Infrastructure setup

What has to exist outside this repository before Phase 2 (Printify) can run.
Phase 0 and 1 needed none of it — they are entirely local.

> **This is a real shop, not a throwaway.** The plan's exit criteria were
> written assuming a disposable test shop. They aren't disposable here, so the
> sequence below is ordered to make the first real write boring: confirm the
> draft setting *before* the first publish, and use a deliberately unattractive
> first product. See "Making the first write safe".

---

## 1. Printify

### 1.1 Connect the Etsy store

In Printify: **My stores → Add new store → Etsy**, and complete the Etsy
authorisation. This is Printify's own integration and uses Etsy's OAuth from
Printify's side — it does **not** need an Etsy developer app, and is not
blocked by Etsy API approval.

This connection is what makes `external.id` appear on a published product, and
`external.id` *is* the Etsy listing id — the only bridge between the two
systems. Without it, Phase 2's exit criteria cannot be met.

### 1.2 Confirm products publish as DRAFT — this has to be done by hand

**Do this before anything else touches the shop.** This section used to say
that nothing the tool sends can affect it, citing Printify's API Reference,
which documents `visible` as read-only and omits it from every request body.
**The reference is wrong**: measured against the live API, `visible` is
accepted on create and on update and reads back as sent
([api-findings.md](api-findings.md)).

What that does *not* establish is the thing this section cares about —
whether a hidden product publishes to Etsy as a draft. That needs a connected
Etsy shop and is unanswered. So the shop-side setting remains the lever to
trust: find it in the Etsy store's settings inside Printify, by hand, and
confirm it publishes as a draft before running `apply` against this shop for
the first time. Whether that setting is a persistent per-shop default or
something that reverts is still open, so re-check it before every publish.
Getting it wrong means a listing goes public before you've reviewed it, and
costs the $0.20 listing fee.

### 1.3 Generate an API token

Printify → **account settings → Connections** (`printify.com/app/account/connections`)
→ generate a personal access token.

Scopes to select:

| Scope | Why |
|---|---|
| `shops.read` | resolve your shop id |
| `catalog.read` | blueprints, print providers, variants (already used in Phase 0) |
| `products.read` | `GET products/{id}` — the `printify_product` stage's live read |
| `products.write` | create and update the product |
| `uploads.read`, `uploads.write` | upload the design image the print area references |

The token is shown **once**. If you lose it, generate a new one.

### 1.4 Shipping and production partner

Etsy requires a production partner declaration, and a listing needs a shipping
profile. Printify supplies both on publish, but a store that has never
published anything can have them unset. If the first publish fails validation,
this is the usual cause.

---

## 2. Etsy

### 2.1 The shop itself

Must be an open shop that can accept listings — payment method set, policies
configured. Printify publishes *into* it.

### 2.2 Register the developer app — do this now

**Not needed for Phase 2. Start it anyway.**

<https://www.etsy.com/developers/register> — register an app for the Open API
v3. You get a **keystring** (API key) and a shared secret. Approval is manual
and the lead time is unknown (PRD risk 1).

It is a form, not engineering work, and Phase 3 is blocked cold without it. The
implementation plan's standing advice is to file it early; that is now overdue
rather than early.

### 2.3 Shop section and return policy

Create at least one shop section and one return policy in Etsy's shop manager.
You do **not** need their numeric ids yet — `shop_section_id` and
`return_policy_id` are optional in `shop.yaml` and are only demanded by the
Etsy stages in Phase 3, whose setup flow reads them back from the API. Leave
them out until then.

---

## 3. The workspace

The workspace is a **separate directory you own**, never this repository.
`setup` creates one:

```bash
uv run etsy-listings setup --root ~/etsy-listings
```

It writes the skeleton, captures and **verifies** the Printify token from
section 1.3, discovers the shop id from that same call, and writes `shop.yaml`
and a `.gitignore` covering `.env`, `.auth/` and `.cache/`. Re-running it is
safe — each question comes pre-filled with the current value.

```
etsy-listings/
  shop.yaml
  .gitignore               # written by setup
  .env                     # secrets, gitignored
  designs/
  mockup-templates/
  listings/
  profiles/
  pricing-plans/
  common-media/
  test-designs/
  prompts/
```

`shop.yaml` — everything Phase 2 needs, and nothing it doesn't:

```yaml
printify:
  shop_id: 28819281        # read back from your token; setup writes it
etsy:
  who_made: i_did
  when_made: made_to_order
  is_supply: false
  renewal: manual
  # shop_id, shop_section_id and return_policy_id are Phase 3; add them then.
currency: NOK
preferred_print_provider: Monster Digital
```

Point the tool at it with `--root`, or `export ETSY_LISTINGS_ROOT=...` in
`~/.zshenv`. Cygwin paths work (`/home/Admin/etsy-listings`), for `setup` too.

---

## 4. Where the secrets go — and where they don't

**In the workspace's `.env`:**

```
PRINTIFY_API_TOKEN=...
ANTHROPIC_API_KEY=...        # not needed until Phase 4
```

Etsy OAuth tokens land in `.auth/etsy-tokens.json`, written by `auth` in Phase
3 — you won't create that by hand.

**Do not paste any of these into a chat with me, or into a file in this
repository.** I don't need them: the tool reads them from that file at runtime,
and I can write and test every code path against fakes and cassettes without
ever seeing a real credential. If a command needs the token, it picks it up
from the environment on your machine. If you ever do paste one somewhere it
shouldn't be, rotate it rather than deleting the message — Printify tokens are
regenerable from the same Connections page.

---

## 5. Real assets you'll need

Phase 2 pushes a real product, so `apply` runs the render stage first and needs
real inputs:

- **A design file** — RGBA PNG, sized within 10% of the profile's print area (a
  4500×5400 print area wants at least 4050×4860). Validation rejects anything
  smaller with the required size named; it never upscales.
- **A calibrated mockup template** — at least one template set, calibrated in
  the browser (`etsy-listings ui`). Until Phase 3 the mockups aren't uploaded
  anywhere, but `apply` still renders them.

---

## 6. Making the first write safe

On a shop you intend to keep:

1. Confirm the draft setting (1.2) before any publish.
2. First product: use a real design you'd genuinely list, but expect to delete
   it. Create it, confirm `external.id` appears, confirm it is a **draft** in
   Etsy, then run `apply` again and confirm it is a no-op — that is the whole
   exit criterion.
3. Delete the test product from Printify (which removes the Etsy draft) once
   the findings are written up.
4. A draft costs nothing. Only activation triggers the $0.20 listing fee — so
   nothing above costs money unless the draft setting is wrong, which is why it
   is step one.

`create_product` is the only non-idempotent call in the system — there is no
idempotency key and no conflict, so an identical spec simply makes a second
product. It is guarded by the lockfile's `printify_product_id`, plus a
pre-flight **walk** of the shop's products matched on title and description
(PRD 48). A walk rather than a lookup because `GET products.json` accepts
`title`, `search` and `sku` and ignores all three. That guard is the first
thing to get a behaviour test in Phase 2, before anything talks to a real shop.

---

## Checklist

- [ ] Printify account with the Etsy store connected
- [ ] Publish-as-draft confirmed in Printify's store settings
- [ ] Printify API token generated with the five scopes above
- [ ] Etsy shop open and able to accept listings
- [ ] Etsy developer app **submitted** (for Phase 3)
- [ ] At least one Etsy shop section and one return policy created (ids not needed until Phase 3)
- [ ] `etsy-listings setup` run: workspace created, token verified, `shop.yaml` and `.env` written
- [ ] One real design at print-area resolution
- [ ] One calibrated mockup template
