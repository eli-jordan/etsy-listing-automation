# Workspace references

A command selects the data workspace through `--root`, `ETSY_LISTINGS_ROOT`
or upward discovery of `shop.yaml`. This is separate from the application's
checkout. Auth and setup accept an explicit root before `shop.yaml` exists.

Within a listing, an unprefixed file reference starts at the workspace root;
`./` starts at the listing directory. Subdirectories are allowed, `..` is
refused. These roots apply to designs, pricing plans, description refs and file
entries in media. A listing template uses its own directory as the owner root
for `./`; instantiation copies local assets into the new listing.

| Reference in `listings/sunrise/listing.yaml` | Resolved file |
|---|---|
| `designs/sunrise.png` | `<workspace>/designs/sunrise.png` |
| `./detail.png` | `<workspace>/listings/sunrise/detail.png` |
| `common-copy/care.md` | `<workspace>/common-copy/care.md` |

Every path is resolved through `Workspace` rather than the process's current
directory. The `media` list names the gallery and determines which mockup
scenes render; selling a colour does not by itself request a photo of it.
Colour-matrix entries name a template and colour, while single and multiple
templates resolve their scene through the template kind.

The cache can be removed, but that also discards staging uploads, batch review
state and cached proposals. It leaves ordinary listings, designs and templates
intact. A later plan notices missing render outputs and schedules work again.

The enforcing sources are
[`workspace.py`](../../src/etsy_listings/workspace/workspace.py),
[`layout.py`](../../src/etsy_listings/workspace/layout.py) and
[`listing_template.py`](../../src/etsy_listings/config/listing_template.py).
