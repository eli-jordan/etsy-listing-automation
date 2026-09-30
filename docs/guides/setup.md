# Account and workspace setup

Connect Printify to Etsy, capture credentials, then initialise a separate data
workspace. Local rendering needs no remote credentials; deploying a connected
product needs both integrations. These steps follow the current `auth` and
`setup` commands rather than the original implementation phases.

## Connect the accounts

Connect the Etsy store in Printify's store settings. That native connection
creates the Etsy listing and routes its orders to the printer; the application's
Etsy client subsequently patches the listing. Confirm the store publishes new
products as drafts before applying a listing you have not reviewed publicly.

Create a Printify API token with access to the catalog, shops, products and
uploads used by this tool. Register an Etsy developer app and obtain its
keystring and shared secret. The app must register the exact OAuth callback
`http://localhost:8517/oauth/callback`; `auth` requests `listings_r`,
`listings_w` and `shops_r`.

The Etsy shop needs the production partner and shipping profile appropriate
for the products being listed. Setup discovers shop reference data; the editor
and deployment checks report unresolved choices. A production partner must
be attached to each managed listing, not merely exist in the shop.

## Capture credentials and initialise the workspace

Run from the installed application or this checkout, choosing a data directory
outside the repository:

```bash
uv run etsy-listings auth --root ~/etsy-listings
uv run etsy-listings setup --root ~/etsy-listings
```

Auth writes credentials into the workspace's `.env` and rotating Etsy tokens
into `.auth/etsy-tokens.json`. It writes secret exclusions before storing the
first credential. Setup creates the directories, resolves shop ids, writes
`shop.yaml` and seeds the prompt files. Re-running setup keeps existing prompt
customisation and pre-fills configuration from the workspace.

You can manage one credential independently:

```bash
uv run etsy-listings auth printify --root ~/etsy-listings
uv run etsy-listings auth etsy --root ~/etsy-listings
uv run etsy-listings auth anthropic --root ~/etsy-listings
```

Local AI Mode uses the signed-in provider CLIs. Capturing an Anthropic API key
is a separate optional credential flow; it does not sign those CLIs in.

## Workspace files

| File or directory | Purpose |
|---|---|
| `shop.yaml` | Discovered shop ids, currency and listing defaults |
| `.env`, `.auth/` | Credentials and OAuth tokens; gitignored |
| `designs/` | Artwork |
| `garment-profiles/`, `pricing-plans/` | Reusable production settings and prices |
| `mockup-templates/` | Photos and calibrated render geometry |
| `listings/` | Saved listings and per-listing deployment lockfiles |
| `listing-templates/` | Reusable listing configurations, created when saved |
| `common-media/`, `common-copy/` | Shared gallery assets and description bodies |
| `test-designs/` | Calibration artwork |
| `prompts/` | Editable SEO, brief and market-query instructions |
| `.cache/` | Render, research, proposal and batch data created on demand |

Setup supplies commented configuration rather than requiring ids to be typed
by hand. The production default is `who_made: someone_else`, with a resolved
production partner. Retail prices carry the shop currency explicitly. See
[remote field ownership](../reference/field-ownership.md) for the values
Printify and Etsy each write.

Pass `--root` to commands or set `ETSY_LISTINGS_ROOT` to select this workspace.
Commands that use an existing workspace can also discover `shop.yaml` by walking
up from the current directory. File references follow the
[workspace and owner roots](../reference/workspace-references.md).

## Review the first deployment

Add a design at print-area resolution and calibrate its mockup template with
`etsy-listings ui`. Create a listing, fill the deployment issues the editor
reports, and review its plan before applying:

```bash
uv run etsy-listings plan <listing> --root ~/etsy-listings
uv run etsy-listings apply <listing> --root ~/etsy-listings
```

Confirm the resulting Etsy listing is a draft and review its copy, prices,
images, shipping profile and production partner. Run plan again to check the
unchanged listing converges without further writes. First publication remains
your action in Etsy; the tool also maintains listings after publication.

Credentials belong in the workspace, never the application repository or a
chat. The [API findings](../research/api-findings.md) retain the dated evidence
behind the integration rules; the [getting-started guide](getting-started.md)
walks through artwork, profiles, templates and listing content.
